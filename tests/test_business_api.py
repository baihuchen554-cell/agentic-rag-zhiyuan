"""真实 HTTP/ASGI 边界和离线业务接口；不调用模型供应商。"""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'project')]

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import config
from account_fixture import FakeVerifier, OfflineWorkspace
from business_api import register_business_api
from core.accounts import AccountError, AccountStore, COOKIE
from core.http_limits import RequestBodyLimits
from core.workspaces import WorkspaceRegistry


class BusinessApiTest(unittest.TestCase):
    def setUp(self):
        api_settings = patch.multiple(config, DEEPSEEK_API_KEY='offline-test-chat', EMBEDDING_API_KEY='offline-test-embedding')
        api_settings.start()
        self.addCleanup(api_settings.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.accounts = AccountStore(Path(self.temp.name) / 'accounts.sqlite3')
        self.workspaces = WorkspaceRegistry(self.accounts, base=Path(self.temp.name) / 'users', factory=OfflineWorkspace)
        self.addCleanup(self.workspaces.close)
        self.alice, _ = self.accounts.register('alice', '小林', 'password-test-123')
        self.bob, _ = self.accounts.register('bobby', '小张', 'password-test-123')
        self.alice_token = self.accounts.new_session(self.alice['id'])[0]
        self.bob_token = self.accounts.new_session(self.bob['id'])[0]
        self.app = FastAPI()

        @self.app.exception_handler(AccountError)
        async def account_error(request, exc):
            return JSONResponse({'detail': str(exc)}, status_code=exc.status)

        @self.app.exception_handler(RequestValidationError)
        async def invalid_input(request, exc):
            return JSONResponse({'detail': '输入格式有误。'}, status_code=422)

        register_business_api(self.app, self.accounts, self.workspaces, FakeVerifier())
        self.app.add_middleware(RequestBodyLimits, accounts=self.accounts, workspaces=self.workspaces)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def headers(self, token=None):
        return {'Cookie': f'{COOKIE}={token or self.alice_token}', 'X-Knowva-Request': '1'}

    def chat(self, message='我叫小林。', token=None, conversation_id=None):
        data = {'message': message}
        if conversation_id:
            data['conversation_id'] = conversation_id
        return self.client.post('/api/chat', json=data, headers=self.headers(token))

    @staticmethod
    def events(response):
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]

    def test_public_health_is_minimal_and_business_routes_require_cookie(self):
        self.assertEqual(self.client.get('/health/live').json(), {'status': 'ok'})
        self.assertEqual(self.client.get('/health/ready').json(), {'status': 'ready'})
        for url in ['/api/usage', '/account/usage', '/api/documents', '/api/conversations', '/api/admin/runtime']:
            self.assertEqual(self.client.get(url).status_code, 401, url)
        self.assertEqual(self.client.post('/api/documents', files={'files': ('a.md', b'a')}).status_code, 401)
        class Unconfigured:
            def require_configured(self):
                raise AccountError('secret configured details', 503)
        app = FastAPI()
        register_business_api(app, self.accounts, self.workspaces, Unconfigured())
        result = TestClient(app).get('/health/ready')
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {'status': 'not_ready'})
        with patch.object(config, 'DEEPSEEK_API_KEY', ''):
            self.assertEqual(self.client.get('/health/ready').status_code, 503)

    def test_list_usage_and_documents_do_not_load_rag_or_models(self):
        result = self.client.get('/account/usage', headers=self.headers())
        self.assertEqual(result.json()['questions'], 0)
        self.assertEqual(self.workspaces.stats()['cached_workspaces'], 0)
        self.assertEqual(self.client.get('/api/documents', headers=self.headers()).json(), {'documents': []})
        workspace = self.workspaces._items[self.alice['id']]
        self.assertIsNone(workspace._rag)
        self.assertEqual(self.chat('   ').status_code, 400)
        with patch.object(config, 'MAX_QUESTION_CHARS', 3):
            self.assertEqual(self.chat('message over limit').status_code, 400)
        self.assertIsNone(workspace._rag)
        self.assertEqual(self.workspaces.stats()['pinned_workspaces'], 0)

    def test_chat_stream_uses_saved_history_and_does_not_accept_client_memory(self):
        response = self.chat()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertIn('event: done', response.text)
        conversation_id = self.events(response)[0]['conversation_id']
        response = self.chat('我的名字是什么？', conversation_id=conversation_id)
        self.assertIn('小林', self.events(response)[-2]['messages'][-1]['content'])
        listing = self.client.get('/api/conversations', headers=self.headers()).json()
        self.assertEqual(listing['total'], 1)
        saved = self.client.get('/api/conversations/' + conversation_id, headers=self.headers()).json()
        self.assertNotIn('memory', saved)
        self.assertGreaterEqual(len(saved['messages']), 4)
        invalid = self.client.post('/api/chat', json={'message': 'ok', 'history': [{'content': 'forged'}]}, headers=self.headers())
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.workspaces.stats()['pinned_workspaces'], 0)

    def test_conversation_read_delete_and_stop_are_account_isolated(self):
        conversation_id = self.events(self.chat())[0]['conversation_id']
        other = self.headers(self.bob_token)
        self.assertEqual(self.client.get('/api/conversations', headers=other).json()['total'], 0)
        url = '/api/conversations/' + conversation_id
        self.assertEqual(self.client.get(url, headers=other).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=other).status_code, 404)
        self.assertEqual(self.client.post('/api/chat/' + conversation_id + '/stop', headers=other).status_code, 404)
        self.assertEqual(self.chat('hi', token=self.bob_token, conversation_id=conversation_id).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=self.headers()).json(), {'ok': True})
        self.assertEqual(self.client.get(url, headers=self.headers()).status_code, 404)

    def test_question_limits_apply_to_api_and_release_capacity_on_rejection(self):
        with patch.object(config, 'DAILY_QUESTIONS', 1):
            self.assertEqual(self.chat().status_code, 200)
            response = self.chat('又一个问题')
            self.assertEqual(response.status_code, 429, response.text)
            self.assertIn('上限', response.json()['detail'])
        self.assertEqual(self.workspaces.stats()['active_tasks'], 0)
        self.assertEqual(self.workspaces.stats()['pinned_workspaces'], 0)
        self.assertEqual(self.client.get('/api/usage', headers=self.headers()).json()['questions'], 1)

    def test_disconnected_chat_releases_lease_but_keeps_capacity_until_model_worker_exits(self):
        from test_conversation_memory import MemoryLlm
        entered, release = Event(), Event()
        original = MemoryLlm.invoke
        def delayed(model, messages):
            entered.set()
            release.wait(5)
            return original(model, messages)

        async def scenario():
            disconnected = asyncio.Event()
            delivered = False
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': b'{"message":"hello"}', 'more_body': False}
                await disconnected.wait()
                return {'type': 'http.disconnect'}
            async def send(message):
                pass
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/chat', 'raw_path': b'/api/chat',
                     'root_path': '', 'query_string': b'', 'scheme': 'http', 'http_version': '1.1',
                     'asgi': {'version': '3.0', 'spec_version': '2.3'}, 'client': ('testclient', 1),
                     'server': ('testserver', 80), 'headers': [(b'host', b'testserver'),
                     (b'content-type', b'application/json'), (b'cookie', f'{COOKIE}={self.alice_token}'.encode())]}
            task = asyncio.create_task(self.app(scope, receive, send))
            self.assertTrue(await asyncio.to_thread(entered.wait, 3), 'offline model did not start')
            workspace = self.workspaces._items[self.alice['id']]
            conversation_id = workspace.store.list_conversations()[0][1]
            conflict = await asyncio.to_thread(self.chat, 'another turn', None, conversation_id)
            self.assertEqual(conflict.status_code, 409, conflict.text)
            disconnected.set()
            await asyncio.wait_for(task, 3)
            self.assertEqual(self.workspaces.stats()['pinned_workspaces'], 0)
            self.assertEqual(self.workspaces.stats()['active_tasks'], 1)
            self.workspaces.prune(force_space=True)
            self.assertIn(self.alice['id'], self.workspaces._items)
            release.set()
            deadline = time.monotonic() + 3
            while self.workspaces.stats()['active_tasks'] and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            self.assertEqual(self.workspaces.stats()['active_tasks'], 0)
        try:
            with patch.object(MemoryLlm, 'invoke', delayed):
                asyncio.run(scenario())
        finally:
            release.set()

    def test_session_revoked_during_model_wait_suppresses_fetched_update_and_closes_stream(self):
        from test_conversation_memory import MemoryLlm
        from core.chat_interface import ChatInterface
        from langchain_core.messages import AIMessage
        entered, release, private_fetched = Event(), Event(), Event()
        private_answer = 'private-model-answer-after-session-revocation'
        original_chat = ChatInterface.chat

        def delayed(model, messages):
            entered.set()
            release.wait(5)
            return AIMessage(content=private_answer)

        def answer_stream(interface, *args, **kwargs):
            # Keep the real graph, model wait, saved generation and task tickets.
            # Drain intermediate progress inside next() so a previously authorized
            # progress frame cannot be mistaken for a newly fetched private answer.
            iterator = original_chat(interface, *args, **kwargs)
            try:
                yield next(iterator)
                for update in iterator:
                    if any(item.get('content') == private_answer for item in update):
                        private_fetched.set()
                        yield update
            finally:
                iterator.close()

        async def scenario():
            delivered, revoked = False, False
            after_revocation = []
            initial_received = asyncio.Event()
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': b'{"message":"hello"}', 'more_body': False}
                await asyncio.Event().wait()
            async def send(message):
                if message['type'] == 'http.response.body':
                    frame = message.get('body', b'').decode()
                    if not revoked and 'event: update' in frame:
                        initial_received.set()
                    if revoked:
                        after_revocation.append(frame)
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/chat', 'raw_path': b'/api/chat',
                     'root_path': '', 'query_string': b'', 'scheme': 'http', 'http_version': '1.1',
                     'asgi': {'version': '3.0', 'spec_version': '2.3'}, 'client': ('testclient', 1),
                     'server': ('testserver', 80), 'headers': [(b'host', b'testserver'),
                     (b'content-type', b'application/json'), (b'cookie', f'{COOKIE}={self.alice_token}'.encode())]}
            task = asyncio.create_task(self.app(scope, receive, send))
            try:
                await asyncio.wait_for(initial_received.wait(), 3)
                self.assertTrue(await asyncio.to_thread(entered.wait, 3), 'offline model did not start')
                self.accounts.logout(self.alice_token)
                revoked = True
                release.set()
                await asyncio.wait_for(task, 3)
                emitted = ''.join(after_revocation)
                self.assertTrue(private_fetched.is_set(), 'blocked model answer was not fetched by the API iterator')
                self.assertIn('event: error', emitted)
                self.assertIn('登录已失效', emitted)
                self.assertNotIn('event: update', emitted)
                self.assertNotIn('event: done', emitted)
                self.assertNotIn(private_answer, emitted)
                self.assertEqual(self.workspaces.stats()['pinned_workspaces'], 0)
                deadline = time.monotonic() + 3
                while self.workspaces.stats()['active_tasks'] and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
                self.assertEqual(self.workspaces.stats()['active_tasks'], 0)
            finally:
                release.set()
        with patch.object(MemoryLlm, 'invoke', delayed), patch.object(ChatInterface, 'chat', answer_stream):
            asyncio.run(scenario())

    def test_multipart_ingestion_staging_cleanup_and_isolated_deletion(self):
        directories = []
        actual_temporary_directory = tempfile.TemporaryDirectory
        def staging(*args, **kwargs):
            directory = actual_temporary_directory(*args, **kwargs)
            directories.append(directory.name)
            return directory
        with patch('business_api.tempfile.TemporaryDirectory', side_effect=staging):
            result = self.client.post('/api/documents', files={'files': ('notes.md', '# 私有文档\n这是小林的知识库。'.encode())},
                                      headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['added'], 1)
        self.assertTrue(directories)
        self.assertTrue(all(not Path(path).exists() for path in directories))
        self.assertNotIn(self.temp.name, result.text)
        self.assertEqual(self.client.get('/api/documents', headers=self.headers()).json()['documents'], [{'source': 'notes.md'}])
        self.assertEqual(self.client.get('/api/documents', headers=self.headers(self.bob_token)).json()['documents'], [])
        self.assertEqual(self.client.request('DELETE', '/api/documents', json={'sources': ['notes.md']},
                                            headers=self.headers(self.bob_token)).status_code, 404)
        result = self.client.request('DELETE', '/api/documents', json={'sources': ['notes.md']}, headers=self.headers())
        self.assertEqual(result.json(), {'deleted': 1})
        self.assertGreater(self.workspaces.ledger.summary(self.alice['id'])['upload_bytes'], 20)

    def test_upload_rejects_paths_types_sizes_and_excess_document_count_before_model_loading(self):
        for name in ['../secret.md', 'payload.exe']:
            result = self.client.post('/api/documents', files={'files': (name, b'hello')}, headers=self.headers())
            self.assertEqual(result.status_code, 400, result.text)
        result = self.client.post('/api/documents', json={'paths': ['/etc/passwd']}, headers=self.headers())
        self.assertEqual(result.status_code, 400)
        with patch.object(config, 'MAX_UPLOAD_BYTES', 4):
            result = self.client.post('/api/documents', files={'files': ('large.md', b'12345')}, headers=self.headers())
            self.assertEqual(result.status_code, 413)
        with patch.object(config, 'MAX_DOCUMENTS', 1):
            result = self.client.post('/api/documents', files=[('files', ('a.md', b'a')), ('files', ('b.md', b'b'))],
                                      headers=self.headers())
            self.assertEqual(result.status_code, 413, result.text)
        self.assertTrue(all(w._rag is None for w in self.workspaces._items.values()))

    def test_upload_daily_wire_budget_is_checked_before_multipart_parsing(self):
        with patch.object(config, 'DAILY_UPLOAD_BYTES', 20):
            result = self.client.post('/api/documents', files={'files': ('a.md', b'a')}, headers=self.headers())
        self.assertEqual(result.status_code, 429)
        self.assertEqual(self.workspaces.stats()['cached_workspaces'], 0)
        self.assertEqual(self.workspaces.ledger.summary(self.alice['id'])['upload_bytes'], 0)

    def test_admin_explicit_grant_runtime_redaction_and_disable_revokes_sessions(self):
        response = self.client.get('/api/admin/users', headers=self.headers())
        self.assertEqual(response.status_code, 403)
        self.accounts.grant_admin('alice')
        users = self.client.get('/api/admin/users', headers=self.headers()).json()
        self.assertEqual(users['total'], 2)
        self.assertIn('usage', users['users'][0])
        self.assertNotIn('password', str(users))
        runtime = self.client.get('/api/admin/runtime', headers=self.headers()).json()
        self.assertIs(runtime['verification_configured'], True)
        self.assertIn('capacity', runtime['runtime'])
        self.assertNotIn('secret_key', str(runtime))
        self.assertNotIn(self.temp.name, str(runtime))
        result = self.client.patch('/api/admin/users/' + self.bob['id'], json={'disabled': True}, headers=self.headers())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get('/api/usage', headers=self.headers(self.bob_token)).status_code, 401)
        self.assertEqual(self.client.patch('/api/admin/users/' + self.alice['id'], json={'disabled': True},
                                           headers=self.headers()).status_code, 409)
        self.assertEqual(self.client.patch('/api/admin/users/' + self.bob['id'], json={'disabled': False, 'role': 'admin'},
                                           headers=self.headers()).status_code, 422)

    def run_asgi_body(self, chunks, path='/account/login', extra_headers=(), parser_app=None,
                      content_type=b'application/json'):
        forwarded = []
        async def receiver_app(scope, receive, send):
            body = b''
            while True:
                message = await receive()
                body += message.get('body', b'')
                forwarded.append(len(message.get('body', b'')))
                if not message.get('more_body'):
                    break
            await JSONResponse({'size': len(body)})(scope, receive, send)
        messages = [dict(type='http.request', body=chunk, more_body=index < len(chunks)-1)
                    for index, chunk in enumerate(chunks)]
        sent = []
        async def receive():
            return messages.pop(0) if messages else {'type': 'http.disconnect'}
        async def send(message):
            sent.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': path,
                 'headers': [(b'content-type', content_type), *extra_headers]}
        asyncio.run(RequestBodyLimits(parser_app or receiver_app, self.accounts, self.workspaces)(scope, receive, send))
        return sent, forwarded

    def test_actual_stream_caps_account_and_gradio_json_without_length_header(self):
        sent, forwarded = self.run_asgi_body([b'a' * 60_000, b'b' * 10_000])
        self.assertEqual(sent[0]['status'], 413)
        self.assertEqual(forwarded, [60_000])
        sent, _ = self.run_asgi_body([b'a' * (2 * 1024 * 1024 + 1)], path='/gradio_api/queue/join')
        self.assertEqual(sent[0]['status'], 413)

    def test_malformed_and_dishonest_content_length_do_not_bypass_stream_cap(self):
        for value in [b'-1', b'abc', b'1,2', b'9' * 5000]:
            sent, forwarded = self.run_asgi_body([b'abc'], extra_headers=[(b'content-length', value)])
            self.assertEqual(sent[0]['status'], 400)
            self.assertFalse(forwarded)
        sent, _ = self.run_asgi_body([b'a' * 70_000], extra_headers=[(b'content-length', b'1')])
        self.assertEqual(sent[0]['status'], 413)

    def test_unknown_length_upload_accounting_is_atomic_and_cannot_exceed_daily_budget(self):
        with patch.object(config, 'DAILY_UPLOAD_BYTES', 10):
            sent, forwarded = self.run_asgi_body([b'123456', b'123456'], path='/gradio_api/upload',
                extra_headers=[(b'cookie', f'{COOKIE}={self.alice_token}'.encode())])
        self.assertEqual(sent[0]['status'], 429)
        self.assertEqual(forwarded, [6])
        self.assertEqual(self.workspaces.ledger.summary(self.alice['id'])['upload_bytes'], 6)

    def test_real_gradio_mount_has_api_csrf_guard_and_limits_before_boundary_json_parse(self):
        from starlette.requests import Request as StarletteRequest
        from account_server import create_app
        app = create_app(self.accounts, self.workspaces, FakeVerifier())
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/documents', headers=self.headers()).json(), {'documents': []})
            self.assertEqual(client.post('/api/chat', json={'message': 'hello'},
                headers={'Cookie': f'{COOKIE}={self.alice_token}'}).status_code, 403)
            self.assertEqual(client.request('DELETE', '/api/documents', json={'sources': ['a.md']},
                headers={**self.headers(), 'Origin': 'https://other.example'}).status_code, 403)
            self.accounts.bind_queue('alice-private-session', self.alice['id'])
            self.accounts.record_event('alice-private-event', self.alice['id'])
            for content_type in ['application/json', 'application/problem+json']:
                result = client.post('/gradio_api/cancel', content=json.dumps({
                    'session_hash': 'alice-private-session', 'event_id': 'alice-private-event', 'fn_index': 0}),
                    headers={**self.headers(self.bob_token), 'Content-Type': content_type})
                self.assertEqual(result.status_code, 403, result.text)
            result = client.post('/gradio_api/component_server', content=json.dumps({
                'session_hash': 'alice-private-session', 'component_id': 1, 'fn_name': 'unused', 'data': {}}),
                headers={**self.headers(self.bob_token), 'Content-Type': 'text/plain'})
            self.assertEqual(result.status_code, 403, result.text)
            self.assertEqual(client.post('/gradio_api/component_server', files={'data': (None, '{}')},
                headers=self.headers(self.bob_token)).status_code, 400)
            self.assertEqual(client.get('/gradio_api/heartbeat/alice-private-session',
                headers=self.headers(self.bob_token)).status_code, 403)
            consumed = []
            def oversized_stream():
                for chunk in [b'{"data":["', b'a' * (2 * 1024 * 1024), b'never-read"]}']:
                    consumed.append(len(chunk))
                    yield chunk
            parsed_sizes = []
            original = StarletteRequest.body
            async def observed_body(request):
                body = await original(request)
                parsed_sizes.append(len(body))
                return body
            with patch.object(StarletteRequest, 'body', observed_body):
                result = client.post('/gradio_api/queue/join', content=oversized_stream(),
                                     headers={**self.headers(), 'Content-Type': 'application/json'})
            self.assertEqual(result.status_code, 413, result.text)
            self.assertIn('请求内容过大', result.json()['detail'])
            self.assertFalse(any(size > 2 * 1024 * 1024 for size in parsed_sizes), parsed_sizes)

    def test_rejected_stream_closes_already_spooled_multipart_file(self):
        import starlette.formparsers
        opened = []
        original = starlette.formparsers.SpooledTemporaryFile
        def spool(*args, **kwargs):
            file = original(*args, **kwargs)
            opened.append(file)
            return file
        async def parser_app(scope, receive, send):
            request = Request(scope, receive)
            async with request.form() as form:
                await JSONResponse({'files': len(form)})(scope, receive, send)
        first = (b'--test-boundary\r\nContent-Disposition: form-data; name="files"; filename="a.md"\r\n'
                 b'Content-Type: text/markdown\r\n\r\nfirst part')
        with patch.object(config, 'DAILY_UPLOAD_BYTES', len(first) + 1), \
                patch('starlette.formparsers.SpooledTemporaryFile', side_effect=spool):
            sent, _ = self.run_asgi_body([first, b'far over daily budget\r\n--test-boundary--\r\n'],
                path='/gradio_api/upload', extra_headers=[(b'cookie', f'{COOKIE}={self.alice_token}'.encode())],
                parser_app=parser_app, content_type=b'multipart/form-data; boundary=test-boundary')
        self.assertEqual(sent[0]['status'], 429)
        self.assertTrue(opened, 'multipart parser did not create a temporary file')
        self.assertTrue(all(file.closed for file in opened))


if __name__ == '__main__':
    unittest.main()
