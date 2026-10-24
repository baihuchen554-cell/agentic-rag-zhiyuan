"""在 JSON / multipart 解析前限制真实请求流；不依赖 Content-Length。"""

from http.cookies import SimpleCookie, CookieError

from starlette.responses import JSONResponse
from starlette.formparsers import MultiPartException

import config
from core.accounts import AccountError, COOKIE


class _UploadBodyLimit(MultiPartException):
    """Allow Starlette to close already-spooled multipart files on stream rejection."""
    def __init__(self, error):
        super().__init__(str(error))
        self.error = error


class RequestBodyLimits:
    """ASGI 接收层：超量片段不交给解析器，已接收的上传字节原子记账。"""

    def __init__(self, app, accounts, workspaces):
        self.app, self.accounts, self.workspaces = app, accounts, workspaces

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in {'GET', 'HEAD', 'OPTIONS'}:
            return await self.app(scope, receive, send)
        path = scope['path'].rstrip('/')
        upload = path in {'/gradio_api/upload', '/api/documents'} and scope['method'] == 'POST'
        avatar = path == '/account/avatar'
        limit = (config.MAX_UPLOAD_BYTES * config.MAX_UPLOAD_BATCH + 1024 * 1024 if upload else
                 2 * 1024 * 1024 if avatar or path.startswith('/gradio_api/') else 64 * 1024)
        # Do not impose application limits on unrelated mounted protocols.
        if not (path.startswith(('/api/', '/account/', '/gradio_api/'))):
            return await self.app(scope, receive, send)
        headers = [(key.lower(), value) for key, value in scope['headers']]
        started = False
        violation = None

        async def observed_send(message):
            nonlocal started
            # JSON/form parsers may translate a receive exception into generic 400.
            # Preserve the actual 413/429 and discard that replacement body.
            if violation is not None:
                if not started:
                    started = True
                    await JSONResponse({'detail': str(violation)}, status_code=violation.status,
                        headers={'Cache-Control': 'no-store'})(scope, receive, send)
                return
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            lengths = [value for key, value in headers if key == b'content-length']
            if lengths:
                if len(lengths) != 1 or len(lengths[0]) > 20 or not lengths[0].isdigit():
                    raise AccountError('请求长度无效。', 400)
                if int(lengths[0]) > limit:
                    raise AccountError('请求内容过大，请缩小文件或分批上传。', 413)
            user = None
            if upload:
                cookie = SimpleCookie()
                try:
                    cookie.load(b'; '.join(value for key, value in headers if key == b'cookie').decode('latin1'))
                except CookieError:
                    raise AccountError('登录已失效，请重新登录。', 401) from None
                user = self.accounts.user(cookie[COOKIE].value if COOKIE in cookie else None)
                if user is None:
                    raise AccountError('请先登录后上传文档。', 401)
                if lengths:
                    used = self.workspaces.ledger.summary(user['id'])['upload_bytes']
                    if used + int(lengths[0]) > config.DAILY_UPLOAD_BYTES:
                        raise AccountError('今日上传流量已达上限，请明日再试。', 429)
            received = 0

            async def limited_receive():
                nonlocal received, violation
                message = await receive()
                if message['type'] == 'http.request':
                    size = len(message.get('body', b''))
                    received += size
                    try:
                        if received > limit:
                            raise AccountError('请求内容过大，请缩小文件或分批上传。', 413)
                        if upload and size:
                            self.accounts.require_enabled(user['id'])
                            self.workspaces.ledger.consume(user['id'], 'upload_bytes', size, config.DAILY_UPLOAD_BYTES)
                    except AccountError as exc:
                        violation = exc
                        if upload:
                            raise _UploadBodyLimit(exc) from None
                        raise
                return message

            await self.app(scope, limited_receive, observed_send)
        except (AccountError, _UploadBodyLimit) as exc:
            if isinstance(exc, _UploadBodyLimit):
                exc = exc.error
            if started:
                raise
            response = JSONResponse({'detail': str(exc)}, status_code=exc.status,
                                    headers={'Cache-Control': 'no-store'})
            await response(scope, receive, send)
