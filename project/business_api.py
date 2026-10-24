"""Knowva 的独立业务接口；与 Gradio 共用权限、配额、存储和任务控制。"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import tempfile

import anyio
from fastapi import Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

import config
from core.accounts import COOKIE, AccountError
from db.parent_store_manager import ParentStoreManager


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=16_000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class DocumentDelete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sources: list[str] = Field(min_length=1, max_length=100)


class UserStatus(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    disabled: bool


def _source_name(value):
    # Filenames remain display names, never client-selected filesystem paths.
    if (not isinstance(value, str) or not value or len(value) > 160 or len(value.encode('utf-8')) > 240
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
            or value[-1] in {'.', ' '} or Path(value).stem in {'', '.', '..'} or Path(value).is_reserved()):
        raise AccountError('文档名称无效，请使用不含路径的文件名。')
    return value


def _document_names(workspace):
    # Merely opening a document list must not load embedding models or Qdrant.
    sources = ParentStoreManager(workspace.paths.parents).list_sources() if workspace.paths.parents.exists() else []
    return sources or sorted(path.name for path in workspace.paths.markdown.glob('*.md'))


def register_business_api(app, accounts, workspaces, verifier):
    """Must be called before Gradio's catch-all mount. No admin is created here."""

    def user_for(request, *, admin=False):
        user = accounts.user(request.cookies.get(COOKIE))
        if user is None:
            raise AccountError('登录已失效，请重新登录。', 401)
        if admin and user.get('role') != 'admin':
            raise AccountError('此功能仅限站点管理员。', 403)
        accounts.limit('business-api:' + user['id'], 120, 60)
        return user

    @contextmanager
    def member_workspace(request):
        user_for(request)
        with workspaces.session(request) as workspace:
            yield workspace

    def require_conversation(workspace, conversation_id):
        if not workspace.store.exists(conversation_id):
            raise AccountError('对话不存在。', 404)

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        try:
            verifier.require_configured()
            config.validate_model_api_settings()
            with accounts.connect() as db:
                db.execute('SELECT 1').fetchone()
        except Exception:
            return JSONResponse({'status': 'not_ready'}, status_code=503,
                                headers={'Cache-Control': 'no-store'})
        return {'status': 'ready'}

    @app.get('/account/usage')
    @app.get('/api/usage')
    def usage(request: Request):
        user = user_for(request)
        return workspaces.policy_for(user['id']).summary()

    @app.get('/api/conversations')
    def conversations(request: Request, limit: int = Query(50, ge=1, le=100),
                      offset: int = Query(0, ge=0, le=100_000)):
        with member_workspace(request) as workspace:
            rows = workspace.store.list_conversations()
            return {'conversations': [{'id': ident, 'title': title} for title, ident in rows[offset:offset+limit]],
                    'total': len(rows)}

    @app.get('/api/conversations/{conversation_id}')
    def conversation(conversation_id: str, request: Request):
        with member_workspace(request) as workspace:
            require_conversation(workspace, conversation_id)
            saved = workspace.store.get(conversation_id)
            # Internal model memory contains summaries/tool state and is not a public API field.
            return {'id': conversation_id, 'title': saved['title'], 'messages': saved['messages']}

    @app.delete('/api/conversations/{conversation_id}')
    def delete_conversation(conversation_id: str, request: Request):
        with member_workspace(request) as workspace:
            require_conversation(workspace, conversation_id)
            if workspace._chat is None:
                workspace.store.delete(conversation_id)
            else:
                workspace._chat.delete_conversation(conversation_id)
            return {'ok': True}

    @app.get('/api/documents')
    def documents(request: Request):
        with member_workspace(request) as workspace:
            return {'documents': [{'source': source} for source in _document_names(workspace)]}

    @app.post('/api/documents')
    async def upload_documents(request: Request):
        user_for(request)
        # Files are spooled by Starlette only after RequestBodyLimits accepts each stream chunk.
        async with request.form(max_files=config.MAX_UPLOAD_BATCH, max_fields=0,
                                max_part_size=config.MAX_UPLOAD_BYTES) as form:
            files = form.getlist('files')
            if not files or any(key != 'files' for key in form):
                raise AccountError('请通过 files 字段上传 PDF 或 Markdown 文档。')
            if len(files) > config.MAX_UPLOAD_BATCH or any(not isinstance(f, UploadFile) for f in files):
                raise AccountError('上传文档的数量或格式无效。', 413)
            names = [_source_name(file.filename) for file in files]
            if len({name.casefold() for name in names}) != len(names):
                raise AccountError('同一批文件不能重名。')
            if any(Path(name).suffix.lower() not in {'.pdf', '.md'} for name in names):
                raise AccountError('仅支持 PDF 或 Markdown 文档。')
            # Staging is generated by the server, private, disposable, and never returned to clients.
            with tempfile.TemporaryDirectory(prefix='knowva-api-upload-') as staging:
                root = Path(staging)
                root.chmod(0o700)
                paths = []
                for file, name in zip(files, names):
                    if file.size is not None and file.size > config.MAX_UPLOAD_BYTES:
                        raise AccountError('单个文档超过上传大小限制。', 413)
                    destination = root / name
                    def copy_file():
                        size = 0
                        with destination.open('xb') as output:
                            while chunk := file.file.read(1024 * 1024):
                                size += len(chunk)
                                if size > config.MAX_UPLOAD_BYTES:
                                    raise AccountError('单个文档超过上传大小限制。', 413)
                                output.write(chunk)
                        destination.chmod(0o600)
                    await run_in_threadpool(copy_file)
                    paths.append(str(destination))

                def ingest():
                    with workspaces.session(request) as workspace:
                        workspace.policy.validate_batch(paths)
                        events = []
                        added, skipped = workspace.documents.add_documents(paths, events.append)
                        return {'added': added, 'skipped_or_failed': skipped,
                                'issues': list(events[-1].issues) if events else [],
                                'documents': [{'source': name} for name in _document_names(workspace)]}
                return await run_in_threadpool(ingest)

    @app.delete('/api/documents')
    def delete_documents(data: DocumentDelete, request: Request):
        sources = [_source_name(source) for source in data.sources]
        with member_workspace(request) as workspace:
            if not set(sources).issubset(_document_names(workspace)):
                raise AccountError('所选文档不存在，请刷新后重试。', 404)
            try:
                return {'deleted': workspace.documents.delete_documents(sources)}
            except AccountError:
                raise
            except ValueError:
                raise AccountError('文档状态已改变，请刷新后重试。', 409) from None

    @app.post('/api/chat')
    async def chat(data: ChatRequest, request: Request):
        user = user_for(request)
        if not data.message.strip() or len(data.message) > config.MAX_QUESTION_CHARS:
            raise AccountError(f'问题需要 1–{config.MAX_QUESTION_CHARS} 个字符。')
        lease = workspaces.session(request)
        workspace = await run_in_threadpool(lease.__enter__)
        conversation_id = data.conversation_id or workspace.store.new_id()
        try:
            if data.conversation_id:
                require_conversation(workspace, conversation_id)
            def begin():
                interface = workspace.chat
                try:
                    generation = interface.begin_generation(data.message, [], conversation_id)
                except AccountError:
                    raise
                except ValueError:
                    raise AccountError('对话正在处理或状态已改变，请停止当前回答或刷新后重试。', 409) from None
                return interface, generation, interface.chat(data.message, [], conversation_id, generation)
            interface, generation, iterator = await run_in_threadpool(begin)
        except BaseException:
            lease.__exit__(None, None, None)
            raise

        def event(kind, **fields):
            payload = json.dumps({'conversation_id': conversation_id, **fields}, ensure_ascii=False)
            return f'event: {kind}\ndata: {payload}\n\n'

        closed = False

        async def cleanup():
            nonlocal closed
            if closed:
                return
            closed = True
            # Stop wakes graph_events' polling thread, while a remaining model worker keeps
            # its capacity ticket until the actual network operation returns.
            with anyio.CancelScope(shield=True):
                try:
                    try:
                        await run_in_threadpool(interface.stop, conversation_id)
                    finally:
                        await run_in_threadpool(iterator.close)
                finally:
                    lease.__exit__(None, None, None)

        class ChatResponse(StreamingResponse):
            async def __call__(self, scope, receive, send):
                # Observe disconnect concurrently even while next(iterator) is waiting on
                # model output. Stopping before cancellation lets that thread return.
                try:
                    async with anyio.create_task_group() as group:
                        async def send_body():
                            try:
                                await self.stream_response(send)
                            except OSError:
                                await run_in_threadpool(interface.stop, conversation_id)
                            finally:
                                group.cancel_scope.cancel()

                        async def disconnect():
                            await self.listen_for_disconnect(receive)
                            await run_in_threadpool(interface.stop, conversation_id)
                            group.cancel_scope.cancel()

                        group.start_soon(disconnect)
                        await send_body()
                finally:
                    await cleanup()

        async def stream():
            try:
                yield event('started')
                sentinel = object()
                while True:
                    # Revocation/disable applies to a running stream as well as the next HTTP request.
                    current = await run_in_threadpool(accounts.user, request.cookies.get(COOKIE))
                    if current is None or current['id'] != user['id']:
                        yield event('error', detail='登录已失效，请重新登录。')
                        return
                    update = await run_in_threadpool(next, iterator, sentinel)
                    # A model/network wait may outlive logout, password changes, or
                    # an administrator disabling the account. Check again before
                    # forwarding either the fetched update or the final done event.
                    current = await run_in_threadpool(accounts.user, request.cookies.get(COOKIE))
                    if current is None or current['id'] != user['id']:
                        yield event('error', detail='登录已失效，请重新登录。')
                        return
                    if update is sentinel:
                        break
                    yield event('update', messages=update)
                yield event('done', stopped=generation.cancelled.is_set())
            except Exception:
                yield event('error', detail='请求未完成，请稍后重试。')
            finally:
                await cleanup()
        return ChatResponse(stream(), media_type='text/event-stream', headers={
            'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @app.post('/api/chat/{conversation_id}/stop')
    def stop_chat(conversation_id: str, request: Request):
        with member_workspace(request) as workspace:
            require_conversation(workspace, conversation_id)
            return {'stopped': bool(workspace._chat and workspace._chat.stop(conversation_id))}

    @app.get('/api/admin/users')
    def users(request: Request, limit: int = Query(25, ge=1, le=100),
              offset: int = Query(0, ge=0, le=100_000)):
        user_for(request, admin=True)
        result = accounts.list_users(limit=limit, offset=offset)
        for user in result['users']:
            user['usage'] = workspaces.policy_for(user['id']).summary()
        return result

    @app.patch('/api/admin/users/{user_id}')
    def status(user_id: str, data: UserStatus, request: Request):
        actor = user_for(request, admin=True)
        accounts.set_status(user_id, data.disabled, actor['id'])
        if data.disabled:
            workspaces.cancel_user(user_id)
        return {'ok': True}

    @app.get('/api/admin/runtime')
    def runtime(request: Request):
        user_for(request, admin=True)
        try:
            verifier.require_configured()
            verification_configured = True
        except AccountError:
            verification_configured = False
        path = Path(workspaces.base or config.USER_DATA_DIR).resolve()
        while not path.exists() and path != path.parent:
            path = path.parent
        disk = shutil.disk_usage(path)
        return {'verification_configured': verification_configured,
                'chat_api_configured': bool(config.DEEPSEEK_API_KEY),
                'embedding_api_configured': bool(config.EMBEDDING_API_KEY),
                'runtime': workspaces.stats(),
                'disk': {'total_bytes': disk.total, 'used_bytes': disk.used, 'free_bytes': disk.free}}
