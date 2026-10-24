"""资料、头像、密码与 Turnstile 的信任边界。"""
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock

import httpx
from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'project')]
from core.accounts import AccountStore, AccountError, COOKIE
from core.human_verification import TurnstileVerifier


class TurnstileTests(unittest.TestCase):
    def verifier(self, result=None):
        client = Mock()
        client.post.return_value.json.return_value = result or dict(
            success=True, hostname='knowva.xin', action='register', cdata='bound-id')
        return TurnstileVerifier('real-site-key', 'private-secret', ['knowva.xin'], client=client)

    def verify(self, verifier, token='browser-token'):
        return verifier.verify(token, ip='127.0.0.1', hostname='knowva.xin',
                               action='register', challenge_id='bound-id')

    def test_service_checks_success_hostname_action_and_visitor_binding(self):
        verifier = self.verifier()
        self.verify(verifier)
        self.assertEqual(verifier.client.post.call_args.kwargs['data']['response'], 'browser-token')
        for key, value in [('success', False), ('hostname', 'evil.example'),
                           ('action', 'login'), ('cdata', 'other-visitor')]:
            result = dict(success=True, hostname='knowva.xin', action='register', cdata='bound-id')
            result[key] = value
            with self.assertRaises(AccountError):
                self.verify(self.verifier(result))

    def test_missing_test_keys_network_error_and_bad_tokens_fail_closed(self):
        for site, secret in [('', ''), ('1x00000000000000000000AA', 'real-secret'),
                             ('real-site', '1x0000000000000000000000000000000AA')]:
            with self.assertRaises(AccountError) as error:
                self.verify(TurnstileVerifier(site, secret, ['knowva.xin']))
            self.assertEqual(error.exception.status, 503)
        verifier = self.verifier()
        verifier.client.post.side_effect = httpx.ConnectError('offline')
        with self.assertRaises(AccountError) as error:
            self.verify(verifier)
        self.assertEqual(error.exception.status, 503)
        for token in ['', 'x' * 2049]:
            with self.assertRaises(AccountError):
                self.verify(self.verifier(), token)


class ProfileHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from account_server import create_app
        from account_fixture import OfflineWorkspace, FakeVerifier
        from core.workspaces import WorkspaceRegistry
        cls.temp = tempfile.TemporaryDirectory()
        cls.accounts = AccountStore(Path(cls.temp.name) / 'accounts.sqlite3')
        cls.registry = WorkspaceRegistry(cls.accounts, base=Path(cls.temp.name)/'users', factory=OfflineWorkspace)
        cls.app = create_app(cls.accounts, cls.registry, FakeVerifier())
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def setUp(self):
        import uuid
        self.client.cookies.clear()
        self.user, _ = self.accounts.register('u'+uuid.uuid4().hex[:16], '原姓名', 'original-password-123')
        self.token, _ = self.accounts.new_session(self.user['id'])
        self.client.cookies.set(COOKIE, self.token)

    def post(self, path, data):
        return self.client.post('/account/'+path, json=data, headers={'X-Knowva-Request':'1'})

    def test_profile_requires_cookie_csrf_and_survives_reload(self):
        self.assertEqual(self.client.post('/account/profile', json={'display_name':'新姓名'}).status_code, 403)
        result = self.post('profile', {'display_name':'林知夏'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['user']['id'], self.user['id'])
        self.assertEqual(self.client.get('/account/me').json()['user']['display_name'], '林知夏')
        self.assertEqual(self.post('profile', {'display_name':'   '}).status_code, 400)
        self.assertEqual(self.post('profile', {'display_name':'<img src=x onerror=1>', 'id':'other-user'}).status_code, 422)
        self.client.cookies.clear()
        self.assertEqual(self.post('profile', {'display_name':'访客'}).status_code, 401)

    def test_avatar_is_decoded_resized_private_and_removable(self):
        output = io.BytesIO()
        Image.new('RGB', (800, 400), '#40566c').save(output, format='PNG')
        result = self.client.post('/account/avatar', content=output.getvalue(),
            headers={'X-Knowva-Request':'1', 'Content-Type':'application/octet-stream'})
        self.assertEqual(result.status_code, 200, result.text)
        url = result.json()['user']['avatar_url']
        image = self.client.get(url)
        self.assertEqual(image.headers['content-type'], 'image/webp')
        self.assertIn('no-store', image.headers['cache-control'])
        with Image.open(io.BytesIO(image.content)) as value:
            self.assertEqual(value.size, (256,256))
        other, _ = self.accounts.register('avatar_other', '其他人', 'another-password-123')
        token, _ = self.accounts.new_session(other['id'])
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, token)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, self.token)
        for data, expected in [(b'<svg onload="alert(1)"></svg>',400), (b'x'*(2*1024*1024+1),413)]:
            result = self.client.post('/account/avatar', content=data, headers={'X-Knowva-Request':'1'})
            self.assertEqual(result.status_code, expected)
        self.assertEqual(self.post('avatar/remove', {}).status_code, 200)
        self.assertIsNone(self.client.get('/account/me').json()['user']['avatar_url'])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_password_change_requires_old_password_rotates_session_and_revokes_others(self):
        other_token, _ = self.accounts.new_session(self.user['id'])
        data = dict(current_password='wrong-password', new_password='updated-password-456', confirm_password='updated-password-456')
        self.assertEqual(self.post('password', data).status_code, 401)
        self.assertIsNotNone(self.accounts.user(other_token))
        data['current_password'] = 'original-password-123'
        result = self.post('password', data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(self.accounts.user(self.token))
        self.assertIsNone(self.accounts.user(other_token))
        self.assertIsNotNone(self.client.get('/account/me').json()['user'])
        with self.assertRaises(AccountError):
            self.accounts.login(self.user['username'], 'original-password-123')
        self.assertEqual(self.accounts.login(self.user['username'], 'updated-password-456')['id'], self.user['id'])

    def test_browser_title_and_sidebar_metadata(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(self.client.get('/config').json()['title'], 'knowva')


class AccountMigrationTests(unittest.TestCase):
    def test_previous_account_database_keeps_users_and_passwords(self):
        from core.accounts import password_hash, digest
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.sqlite3'
            from contextlib import closing
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, password TEXT NOT NULL, recovery TEXT NOT NULL, created REAL NOT NULL)')
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',
                    ('a'*32,'legacy_user','旧姓名',password_hash('legacy-password-123'),digest('recovery'),1000))
                db.commit()
            store = AccountStore(path)
            user = store.login('legacy_user', 'legacy-password-123')
            self.assertEqual(user['id'], 'a'*32)
            self.assertIsNone(user['avatar_url'])
            store.update_profile(user['id'], '新姓名')
            self.assertEqual(store.login('legacy_user','legacy-password-123')['display_name'], '新姓名')
