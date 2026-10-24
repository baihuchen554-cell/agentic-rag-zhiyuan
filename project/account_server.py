"""公开首页、账号接口与 Gradio 的访问边界。"""

from contextlib import asynccontextmanager
import asyncio
import json
import logging
from pathlib import Path
import secrets
from urllib.parse import unquote, urlsplit
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
import gradio as gr
from pydantic import BaseModel, ConfigDict, Field

import config
from core.accounts import AccountError, AccountStore, COOKIE, VISITOR_COOKIE, digest
from core.workspaces import WorkspaceRegistry
from core.human_verification import TurnstileVerifier

logger = logging.getLogger('knowva.http')


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=256)
    username: str = Field(min_length=1, max_length=24)
    password: str = Field(min_length=1, max_length=128)
    challenge_id: str = Field(min_length=1, max_length=64)
    verification_token: str = Field(min_length=1, max_length=2048)
    display_name: str = Field(default="", max_length=24)
    confirm_password: str = Field(default="", max_length=128)
    recovery_code: str = Field(default="", max_length=128)
    accepted: bool = False
    remember: bool = False


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=24)


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)


def create_app(accounts=None, workspaces=None, verifier=None):
    accounts = accounts or AccountStore(config.ACCOUNT_DB_PATH)
    workspaces = workspaces or WorkspaceRegistry(accounts)
    verifier = verifier or TurnstileVerifier(config.TURNSTILE_SITE_KEY,
        config.TURNSTILE_SECRET_KEY, config.TURNSTILE_HOSTNAMES)

    @asynccontextmanager
    async def lifespan(_):
        stopped = asyncio.Event()
        async def maintain():
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=30)
                except asyncio.TimeoutError:
                    try:
                        await asyncio.to_thread(workspaces.maintenance)
                    except Exception as exc:
                        logger.error('maintenance_failed type=%s', type(exc).__name__)
        worker = asyncio.create_task(maintain())
        try:
            verifier.require_configured()
        except AccountError:
            logger.warning('human_verification_not_configured')
        try:
            yield
        finally:
            stopped.set()
            await worker
            workspaces.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.accounts = accounts
    app.state.workspaces = workspaces
    from core.http_limits import RequestBodyLimits

    @app.exception_handler(AccountError)
    async def account_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # 不回显包含密码、验证码或恢复码的输入值。
        return JSONResponse({"detail": "输入格式或长度有误，请检查后重试。"}, status_code=422)

    def user_for(request):
        return accounts.user(request.cookies.get(COOKIE))

    def require_user(request, action="profile", maximum=30):
        user = user_for(request)
        if not user:
            raise AccountError("登录已失效，请重新登录。", 401)
        accounts.limit(action + ":" + user["id"], maximum, 900)
        return user

    def origin_allowed(request):
        origin = request.headers.get("origin")
        return (request.headers.get("sec-fetch-site") != "cross-site"
                and (not origin or urlsplit(origin).netloc == request.headers.get("host")))

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request_id = secrets.token_hex(8)
        started = perf_counter()
        upload_session = None
        try:
            path = request.url.path.rstrip('/')
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not origin_allowed(request):
                raise AccountError("请求来源无效，请从本站重试。", 403)
            if path.startswith(("/account/", "/api/")) and request.method not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("x-knowva-request") != "1":
                    raise AccountError("请求校验失败，请刷新页面。", 403)
            if request.method == 'POST' and path in {'/gradio_api/upload','/api/documents'}:
                upload_session = workspaces.upload_session(cached=path=='/gradio_api/upload')
                upload_session.__enter__()
            if path.startswith("/gradio_api/"):
                user = user_for(request)
                owner = user["id"] if user else "guest"
                if path.startswith('/gradio_api/heartbeat/'):
                    accounts.bind_queue(path.rsplit('/',1)[-1], owner)
                if request.headers.get('session_hash'):
                    accounts.bind_queue(request.headers['session_hash'], owner)
                if "/file=" in path:
                    filename = Path(unquote(path.split("/file=", 1)[1])).resolve()
                    public = filename.is_relative_to(Path(config.ASSETS_DIR).resolve())
                    if not public and (not user or not accounts.owns_upload(filename, user["id"])):
                        raise AccountError("文件无权访问。", 403)
                if path.rstrip("/") == "/gradio_api/upload" and not user:
                    raise AccountError("请先登录后上传文档。", 401)
                if "/call/" in path and request.method == "GET":
                    accounts.check_event(path.rstrip('/').rsplit('/', 1)[-1], owner)
                # component_server 会自行解析非 multipart JSON；不能依赖 MIME 跳过归属校验。
                if request.method == "POST" and path != '/gradio_api/upload':
                    try:
                        body = await request.json()
                    except ValueError:
                        raise AccountError("请求格式有误。") from None
                    if not isinstance(body, dict):
                        raise AccountError("请求格式有误。")
                    if body.get("session_hash"):
                        accounts.bind_queue(body["session_hash"], owner)
                    if path.endswith('/cancel') or path.endswith('/reset'):
                        accounts.check_event(body.get('event_id'), owner)
                if path.endswith("/queue/data"):
                    accounts.bind_queue(request.query_params.get("session_hash"), user["id"] if user else "guest")
            response = await call_next(request)
            response.headers['X-Request-ID'] = request_id
            safe_path = '/gradio_api/file' if '/file=' in path else path.split('/account/avatar/')[0]
            logger.info('request id=%s method=%s path=%s status=%s duration_ms=%.1f',
                        request_id,request.method,safe_path,response.status_code,(perf_counter()-started)*1000)
            if path.startswith('/gradio_api/') and (path.endswith('/queue/join') or '/call/' in path) and request.method == 'POST' and response.status_code == 200:
                body = b"".join([chunk async for chunk in response.body_iterator])
                result = json.loads(body)
                if result.get('event_id'):
                    accounts.record_event(result['event_id'], owner)
                    if '/call/' in path:
                        # Gradio 的简化 API 用 event_id 作为内部 session_hash。
                        accounts.bind_queue(result['event_id'], owner)
                return JSONResponse(result, headers={"Cache-Control": "no-store", 'X-Request-ID':request_id})
            # Capture Gradio-issued paths so callers cannot submit another user's cache files.
            if path.rstrip("/") == "/gradio_api/upload" and response.status_code == 200:
                body = b"".join([chunk async for chunk in response.body_iterator])
                for filename in json.loads(body):
                    accounts.record_upload(filename, user["id"])
                return JSONResponse(json.loads(body), headers={"Cache-Control": "no-store", 'X-Request-ID':request_id})
            if path.startswith(("/account/", "/api/")):
                response.headers["Cache-Control"] = "no-store"
            return response
        except AccountError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=exc.status,
                                headers={'Cache-Control':'no-store','X-Request-ID':request_id})
        finally:
            if upload_session is not None:
                upload_session.__exit__(None,None,None)

    @app.get("/account/me")
    def me(request: Request):
        return {"user": user_for(request)}

    @app.get("/account/challenge")
    def challenge(request: Request, action: str = "login"):
        verifier.require_configured()
        if action not in {"login", "register", "recover"}:
            raise AccountError("账号操作无效。")
        ip = request.client.host if request.client else "unknown"
        accounts.limit("challenge:" + digest(ip), 40, 600)
        visitor = request.cookies.get(VISITOR_COOKIE) or secrets.token_urlsafe(24)
        token = accounts.challenge(visitor, action)
        response = JSONResponse({"id": token, "site_key": verifier.site_key,
                                 "provider": "turnstile", "expires_in": 300})
        response.set_cookie(VISITOR_COOKIE, visitor, max_age=86400, httponly=True,
                            secure=request.url.scheme == "https", samesite="lax")
        return response

    def verify(request, data, action):
        ip = request.client.host if request.client else "unknown"
        accounts.limit("account-ip:" + digest(ip), 30, 900)
        accounts.consume_challenge(data.challenge_id, request.cookies.get(VISITOR_COOKIE, ""), action)
        verifier.verify(data.verification_token, ip=ip, hostname=request.url.hostname,
                        action=action, challenge_id=data.challenge_id)
        accounts.limit(action + ":" + digest(data.username.strip().lower()), 10, 900)

    def signed_in(request, user, remember, **extra):
        old = request.cookies.get(COOKIE)
        if old:
            accounts.logout(old)
        token, seconds = accounts.new_session(user["id"], remember)
        response = JSONResponse({"user": user, **extra})
        response.set_cookie(COOKIE, token, max_age=seconds, httponly=True,
                            secure=request.url.scheme == "https", samesite="lax")
        return response

    @app.post("/account/register")
    def register(data: Credentials, request: Request):
        verify(request, data, "register")
        if not data.accepted:
            raise AccountError("请先阅读并同意账号与数据说明。")
        if data.password != data.confirm_password:
            raise AccountError("两次输入的密码不一致。")
        user, recovery = accounts.register(data.username, data.display_name, data.password)
        return signed_in(request, user, data.remember, recovery_code=recovery)

    @app.post("/account/login")
    def login(data: Credentials, request: Request):
        verify(request, data, "login")
        return signed_in(request, accounts.login(data.username, data.password), data.remember)

    @app.post("/account/recover")
    def recover(data: Credentials, request: Request):
        verify(request, data, "recover")
        if data.password != data.confirm_password:
            raise AccountError("两次输入的密码不一致。")
        recovery = accounts.recover(data.username, data.recovery_code, data.password)
        response = JSONResponse({"recovery_code": recovery})
        response.delete_cookie(COOKIE)
        return response

    @app.post("/account/logout")
    def logout(request: Request):
        accounts.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    @app.post("/account/profile")
    def profile(data: ProfileUpdate, request: Request):
        user = require_user(request)
        accounts.update_profile(user["id"], data.display_name)
        return {"user": user_for(request)}

    @app.post("/account/password")
    def password(data: PasswordUpdate, request: Request):
        user = require_user(request, "password", 5)
        if data.new_password != data.confirm_password:
            raise AccountError("两次输入的新密码不一致。")
        accounts.change_password(user["id"], data.current_password, data.new_password)
        return signed_in(request, user, False)

    @app.get("/account/avatar/{user_id}")
    def avatar(user_id: str, request: Request):
        user = user_for(request)
        if not user or user["id"] != user_id:
            raise AccountError("头像无权访问。", 403)
        content = accounts.avatar(user_id)
        if not content:
            raise AccountError("头像不存在。", 404)
        return Response(content, media_type="image/webp", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/account/avatar")
    async def upload_avatar(request: Request):
        user = require_user(request, "avatar", 15)
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise AccountError("请选择不超过 2 MB 的图片。", 413)
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(accounts.set_avatar, user["id"], bytes(content))
        return {"user": user_for(request)}

    @app.post("/account/avatar/remove")
    def remove_avatar(request: Request):
        user = require_user(request, "avatar", 15)
        accounts.set_avatar(user["id"], None)
        return {"user": user_for(request)}

    from ui.gradio_app import create_gradio_ui
    from ui.css import custom_css, app_theme
    from ui.translations import chinese_i18n, chinese_page_head, chinese_ui_js
    from ui.interactions import app_ui_js
    from ui.account_ui import ACCOUNT_CSS, ACCOUNT_JS
    from ui.settings_ui import SETTINGS_CSS, SETTINGS_JS
    from business_api import register_business_api
    register_business_api(app, accounts, workspaces, verifier)
    demo = create_gradio_ui(workspaces=workspaces)
    workspaces.upload_root = demo.GRADIO_CACHE
    # 最后注册，确保在 boundary 读取 Gradio JSON 前限制实际请求流。
    app.add_middleware(RequestBodyLimits, accounts=accounts, workspaces=workspaces)
    return gr.mount_gradio_app(app, demo, path="/", favicon_path=config.APP_LOGO_PATH,
        css=custom_css + ACCOUNT_CSS + SETTINGS_CSS, theme=app_theme, i18n=chinese_i18n,
        js=chinese_ui_js + app_ui_js + SETTINGS_JS + ACCOUNT_JS, head=chinese_page_head,
        max_file_size=config.MAX_UPLOAD_BYTES,
        blocked_paths=[config.USER_DATA_DIR, str(Path(config.ACCOUNT_DB_PATH).parent),
                       config.QDRANT_DB_PATH, config.PARENT_STORE_PATH, config.MARKDOWN_DIR,
                       str(Path(config.CHAT_HISTORY_PATH).parent), str(Path(config.__file__).with_name('.env'))])
