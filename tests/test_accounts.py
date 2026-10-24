"""账号安全与真实 HTTP 接口验证，全部使用临时目录。"""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "project")]
import config
from core.accounts import AccountStore, AccountError, COOKIE, digest
from core.workspaces import WorkspaceRegistry, UserPaths, WorkspaceScope


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.store = AccountStore(Path(self.temp.name) / 'accounts.sqlite3', clock=lambda: self.now)

    def test_hashes_sessions_expiry_and_password_recovery(self):
        user, recovery = self.store.register('Alice', '小林', 'my-password-123')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM users').fetchone()
            self.assertNotIn('my-password-123', row['password'])
            self.assertNotEqual(recovery, row['recovery'])
        self.assertEqual(self.store.login('ALICE', 'my-password-123')['id'], user['id'])
        token, _ = self.store.new_session(user['id'])
        self.assertEqual(self.store.user(token)['id'], user['id'])
        self.assertIsNone(self.store.user('forged-token'))
        self.now += 86401
        self.assertIsNone(self.store.user(token))
        token, _ = self.store.new_session(user['id'])
        replacement = self.store.recover('alice', recovery, 'new-password-456')
        self.assertIsNone(self.store.user(token))
        with self.assertRaises(AccountError):
            self.store.login('alice', 'my-password-123')
        with self.assertRaises(AccountError):
            self.store.recover('alice', recovery, 'third-password-789')
        self.assertNotEqual(replacement, recovery)

    def test_challenge_is_visitor_and_action_bound_expiring_and_single_use(self):
        token = self.store.challenge('visitor', 'login')
        with self.assertRaises(AccountError):
            self.store.consume_challenge(token, 'other-visitor', 'login')
        with self.assertRaises(AccountError):
            self.store.consume_challenge(token, 'visitor', 'login')
        token = self.store.challenge('visitor', 'login')
        self.store.consume_challenge(token, 'visitor', 'login')
        with self.assertRaises(AccountError):
            self.store.consume_challenge(token, 'visitor', 'login')
        token = self.store.challenge('visitor', 'login')
        with self.assertRaises(AccountError):
            self.store.consume_challenge(token, 'visitor', 'register')
        token = self.store.challenge('visitor', 'login')
        self.now += 301
        with self.assertRaises(AccountError):
            self.store.consume_challenge(token, 'visitor', 'login')

    def test_rate_limits_username_validation_and_duplicates(self):
        self.store.limit('ip', 2, 60)
        self.store.limit('ip', 2, 60)
        with self.assertRaises(AccountError):
            self.store.limit('ip', 2, 60)
        self.now += 61
        self.store.limit('ip', 2, 60)
        for username in ['../alice', 'a', '<script>', 'a' * 25]:
            with self.assertRaises(AccountError):
                self.store.register(username, 'name', 'good-password-123')
        self.store.register('alice', 'name', 'good-password-123')
        with self.assertRaises(AccountError):
            self.store.register('ALICE', 'name', 'good-password-123')

    def test_real_qdrant_and_parent_store_use_separate_user_paths(self):
        from core.rag_system import RAGSystem
        from test_model_apis import LocalSparseEmbeddings
        from qdrant_client import models
        root = Path(self.temp.name)
        paths = [UserPaths.for_user(letter * 32, root / 'users') for letter in ['a', 'b']]
        with patch.multiple(config, DEEPSEEK_API_KEY='test-only', EMBEDDING_API_KEY='test-only',
                            QDRANT_DB_PATH=str(root / 'legacy-vectors'), PARENT_STORE_PATH=str(root / 'legacy-parents')), \
                patch('db.vector_db_manager.FastEmbedSparse', LocalSparseEmbeddings):
            systems = []
            try:
                systems = [RAGSystem(paths=path) for path in paths]
                for system in systems:
                    system.vector_db.create_collection(system.collection_name)
                clients = [s.vector_db._VectorDbManager__client for s in systems]
                clients[0].upsert(systems[0].collection_name, [models.PointStruct(id=1, vector=[1.0] * config.DENSE_DIMENSIONS)])
                self.assertEqual(clients[0].count(systems[0].collection_name).count, 1)
                self.assertEqual(clients[1].count(systems[1].collection_name).count, 0)
                systems[0].parent_store.save('p1', 'private A', {'source': 'a.md'})
                self.assertEqual(systems[1].parent_store.load_content('p1'), {})
                self.assertEqual(systems[0].markdown_dir, paths[0].markdown)
                self.assertFalse((root / 'legacy-vectors').exists())
            finally:
                for system in systems:
                    system.vector_db.close()


class AccountHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from account_server import create_app
        from fastapi.testclient import TestClient
        from account_fixture import OfflineWorkspace, FakeVerifier
        cls.temp = tempfile.TemporaryDirectory()
        cls.accounts = AccountStore(Path(cls.temp.name) / 'accounts.sqlite3')
        cls.registry = WorkspaceRegistry(cls.accounts, base=Path(cls.temp.name) / 'users', factory=OfflineWorkspace)
        cls.app = create_app(cls.accounts, cls.registry, FakeVerifier())
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def setUp(self):
        self.client.cookies.clear()

    def data(self, action='register', **extra):
        challenge = self.client.get('/account/challenge', params={'action':action}).json()
        return dict(username='http_user', password='http-password-123', display_name='访客甲',
                    confirm_password='http-password-123', accepted=True,
                    challenge_id=challenge['id'], verification_token='test-valid-token', **extra)

    def post(self, path, data):
        return self.client.post('/account/' + path, json=data, headers={'X-Knowva-Request': '1'})

    def test_guest_landing_is_public_but_upload_and_callbacks_are_protected(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertIsNone(self.client.get('/account/me').json()['user'])
        self.assertEqual(self.client.post('/gradio_api/upload', files={'files': ('test.md', b'private')}).status_code, 401)
        result = self.client.post('/gradio_api/api/file_updates', json={'data': []})
        self.assertIn(result.status_code, [400, 500])
        self.assertEqual(len(self.registry._items), 0)
        self.assertFalse((Path(self.temp.name) / 'users').exists())

    def test_registration_cookie_logout_and_revocation(self):
        result = self.post('register', self.data())
        self.assertEqual(result.status_code, 200, result.text)
        token = self.client.cookies.get(COOKIE)
        self.assertTrue(token)
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        self.assertEqual(self.client.get('/account/me').json()['user']['username'], 'http_user')
        self.assertEqual(self.post('logout', {}).status_code, 200)
        self.assertIsNone(self.accounts.user(token))
        self.assertIsNone(self.client.get('/account/me').json()['user'])

    def test_csrf_and_captcha_bypass_are_rejected(self):
        data = self.data()
        result = self.client.post('/account/login', json=data)
        self.assertEqual(result.status_code, 403)
        result = self.client.post('/account/login', json=data, headers={
            'X-Knowva-Request': '1', 'Origin': 'https://evil.example'})
        self.assertEqual(result.status_code, 403)
        data['verification_token'] = 'forged-token'
        self.assertEqual(self.post('register', data).status_code, 400)
        data['verification_token'] = 'test-valid-token'
        self.assertEqual(self.post('register', data).status_code, 400)

    def test_login_recovery_and_https_cookie(self):
        username = 'recover_http'
        _, recovery = self.accounts.register(username, '恢复测试', 'my-password-123')
        data = self.data(action='login')
        data.update(username=username, password='incorrect-pass-123')
        self.assertEqual(self.post('login', data).status_code, 401)
        data = self.data(action='login')
        data.update(username=username, password='my-password-123')
        self.assertEqual(self.post('login', data).status_code, 200)
        token = self.client.cookies.get(COOKIE)
        data = self.data(action='recover')
        data.update(username=username, password='new-password-456', confirm_password='new-password-456', recovery_code=recovery)
        result = self.post('recover', data)
        self.assertEqual(result.status_code, 200)
        self.assertNotEqual(result.json()['recovery_code'], recovery)
        self.assertIsNone(self.accounts.user(token))
        data = self.data(action='login')
        data.update(username=username, password='new-password-456')
        from fastapi.testclient import TestClient
        secure = TestClient(self.app, base_url='https://testserver')
        try:
            secure.cookies.update(self.client.cookies)
            response = secure.post('/account/login', json=data, headers={'X-Knowva-Request': '1'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('Secure', response.headers['set-cookie'])
        finally:
            secure.close()

    def test_validation_never_echoes_password(self):
        value = 'sensitive-password-' * 30
        result = self.post('login', {'username': 'user', 'password': value})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn(value, result.text)

    def test_two_accounts_uploads_queue_and_data_are_isolated(self):
        from fastapi import Request
        from gradio import Request as GradioRequest
        from core.document_manager import DocumentManager
        from db.parent_store_manager import ParentStoreManager
        from rag_agent.tools import ToolFactory
        users = [self.accounts.register(name, name, 'private-password-123')[0] for name in ['isolate_a', 'isolate_b']]
        tokens = [self.accounts.new_session(u['id'])[0] for u in users]
        def request(token):
            return GradioRequest(Request({'type':'http', 'headers':[(b'cookie', f'{COOKIE}={token}'.encode())]}))
        a, b = [self.registry.resolve(request(token)) for token in tokens]
        self.assertEqual(a.store.list_conversations(), [])
        self.assertEqual(b.store.list_conversations(), [])
        a.store.save('shared-id', [{'role':'user', 'content':'A 的机密'}], {})
        self.assertEqual(b.store.get('shared-id')['messages'], [])
        self.assertFalse(b.store.delete('shared-id'))
        self.assertTrue(a.store.exists('shared-id'))
        parents = [ParentStoreManager(w.paths.parents) for w in (a,b)]
        parents[0].save('p1', 'A 的机密文档', {'source':'secret.md'})
        self.assertEqual(parents[1].load_content('p1'), {})
        tool = ToolFactory(SimpleNamespace(), parent_store=parents[1])
        self.assertEqual(tool._retrieve_parent_chunks('p1'), 'NO_PARENT_DOCUMENT')
        docs = [DocumentManager(SimpleNamespace(markdown_dir=w.paths.markdown,parent_store=p)) for w,p in zip((a,b), parents)]
        self.assertEqual(docs[0].get_markdown_files(), ['secret.md'])
        self.assertEqual(docs[1].get_markdown_files(), [])
        for invalid in ['../escape', '../../etc', 'alice']:
            with self.assertRaises(ValueError):
                UserPaths.for_user(invalid)
        self.accounts.bind_queue('hash-A', users[0]['id'])
        with self.assertRaises(AccountError):
            self.accounts.bind_queue('hash-A', users[1]['id'])
        self.accounts.record_event('event-A', users[0]['id'])
        self.client.cookies.set(COOKIE, tokens[1])
        self.assertEqual(self.client.get('/gradio_api/call/file_updates/event-A').status_code, 403)
        self.assertEqual(self.client.post('/gradio_api/cancel', json={
            'event_id': 'event-A', 'session_hash': 'hash-A', 'fn_index': 0}).status_code, 403)
        self.assertEqual(self.client.post('/gradio_api/component_server', json={
            'session_hash': 'hash-A', 'component_id': 0, 'fn_name': 'test', 'data': {}}).status_code, 403)
        secret = Path(self.temp.name) / 'uploaded.md'
        secret.write_text('A private', encoding='utf-8')
        self.accounts.record_upload(secret, users[0]['id'])
        self.assertFalse(self.accounts.owns_upload(secret, users[1]['id']))
        self.client.cookies.set(COOKIE, tokens[0])
        upload = self.client.post('/gradio_api/upload', files={'files': ('mine.md', b'# my document')})
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertTrue(self.accounts.owns_upload(upload.json()[0], users[0]['id']))
        call = self.client.post('/gradio_api/call/file_updates', json={'data': []})
        self.assertEqual(call.status_code, 200, call.text)
        event_id = call.json()['event_id']
        # POST /call only accepts a queued callback. Drain its real completion
        # before replacing this session or deleting its temporary workspace:
        # a still-running sync callback can otherwise recreate directories while
        # TestClient shutdown and TemporaryDirectory cleanup are in progress.
        completed = self.client.get('/gradio_api/call/file_updates/' + event_id)
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertIn('event: complete', completed.text)
        self.assertNotIn('event: error', completed.text)
        self.assertIn('secret.md', completed.text)
        with self.assertRaises(AccountError):
            self.accounts.bind_queue(event_id, users[1]['id'])
        self.client.cookies.set(COOKIE, tokens[1])
        # Verify injection of the real HTTP cookie into a protected Gradio callback.
        files = self.client.post('/gradio_api/api/file_updates', json={'data': []})
        self.assertEqual(files.status_code, 200, files.text)
        self.assertNotIn('secret.md', files.text)
        self.assertEqual(self.client.get('/gradio_api/file=' + secret.as_posix()).status_code, 403)
        with self.assertRaises(Exception):
            self.registry.validate_uploads([upload.json()[0]], request(tokens[1]))
        # Real callback sees cookies from Gradio Request, not a client-provided user ID.
        scope = WorkspaceScope(self.registry)
        proxy = scope.proxy('store')
        @scope.guard
        def history():
            return proxy.list_conversations()
        self.assertEqual(history(request=request(tokens[1])), [])
        self.assertEqual(history(request=request(tokens[0]))[0][1], 'shared-id')


if __name__ == '__main__':
    unittest.main()
