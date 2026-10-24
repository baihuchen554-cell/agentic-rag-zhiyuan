"""按服务端账号分配工作空间；不接受客户端传入的目录或用户 ID。"""

from contextvars import ContextVar, copy_context
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import inspect
from pathlib import Path
import re
from threading import RLock
from threading import Thread
import time
import shutil
import uuid

import gradio as gr
import config
from core.accounts import COOKIE, AccountError
from core.conversation_store import ConversationStore
from core.resource_limits import UsageLedger, UserPolicy, TaskCapacity


@dataclass(frozen=True)
class UserPaths:
    root: Path
    markdown: Path
    parents: Path
    vectors: Path
    history: Path

    @classmethod
    def for_user(cls, user_id, base=None):
        if not re.fullmatch(r"[a-f0-9]{32}", user_id):
            raise ValueError("用户标识无效。")
        root = Path(base or config.USER_DATA_DIR).resolve() / user_id
        index = root / "knowledge_base" / f"{config.DENSE_MODEL}_{config.DENSE_DIMENSIONS}"
        return cls(root, index / "markdown_docs", index / "parent_store", index / "qdrant_db",
                   root / "chat_history" / "conversations.sqlite3")


class Workspace:
    def __init__(self, paths):
        self.paths = paths
        paths.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        paths.root.chmod(0o700)
        self.store = ConversationStore(paths.history)
        self._lock = RLock()
        self._rag = self._documents = self._chat = None
        self.policy = None

    @property
    def rag(self):
        with self._lock:
            if self._rag is None:
                from core.rag_system import RAGSystem
                from contextlib import nullcontext
                with self.policy.capacity.claim(self.policy.user_id, 'initialize') if self.policy else nullcontext():
                    rag = RAGSystem(paths=self.paths)
                    try:
                        rag.initialize()
                    except Exception:
                        rag.vector_db.close()
                        raise
                self._rag = rag
            return self._rag

    @property
    def documents(self):
        with self._lock:
            if self._documents is None:
                from core.document_manager import DocumentManager
                self._documents = DocumentManager(self.rag, policy=self.policy)
            return self._documents

    @property
    def chat(self):
        with self._lock:
            if self._chat is None:
                from core.chat_interface import ChatInterface
                self._chat = ChatInterface(self.rag, self.store, policy=self.policy)
            return self._chat

    def close(self):
        if self._rag:
            self._rag.vector_db.close()
        self._rag = self._documents = self._chat = None

    @property
    def busy(self):
        return bool(self._chat and self._chat.busy)


class GuestWorkspace:
    """游客只返回空视图，不创建数据库、模型或知识库。"""
    class Store:
        @staticmethod
        def list_conversations():
            return []

        @staticmethod
        def new_id():
            return str(uuid.uuid4())

        @staticmethod
        def get(_):
            return {"messages": [], "title": "新的对话", "memory": {}}

        @staticmethod
        def exists(_):
            return False

    store = Store()


class WorkspaceRegistry:
    def __init__(self, accounts, base=None, factory=Workspace, clock=time.monotonic,
                 max_cached=None, idle_seconds=None):
        self.accounts, self.base, self.factory = accounts, base, factory
        self._items, self._lock = {}, RLock()
        self._pins, self._last_used = {}, {}
        self._created = {}
        self._uploading = 0
        self._cached_uploading = 0
        self.upload_root = None
        self.clock, self.max_cached = clock, max_cached or config.MAX_CACHED_WORKSPACES
        self.idle_seconds = idle_seconds or config.WORKSPACE_IDLE_SECONDS
        self.ledger, self.capacity = UsageLedger(accounts), TaskCapacity()

    def policy_for(self, user_id):
        return UserPolicy(user_id, UserPaths.for_user(user_id, self.base), self.ledger, self.capacity)

    def _remove(self, key):
        self._items[key].close()
        del self._items[key]
        self._last_used.pop(key, None)
        self._created.pop(key, None)
        self._pins.pop(key, None)

    def prune(self, force_space=False):
        with self._lock:
            for key in sorted(self._items, key=lambda k:self._last_used[k]):
                if self._pins.get(key,0) or getattr(self._items[key],'busy',False):
                    continue
                if (self.clock()-self._last_used[key] >= self.idle_seconds
                        or self.clock()-self._created[key] >= config.WORKSPACE_MAX_AGE_SECONDS
                        or (force_space and len(self._items) >= self.max_cached)):
                    self._remove(key)

    def resolve(self, request, guest=False):
        cookies = request.cookies if request else {}
        user = self.accounts.user(cookies.get(COOKIE))
        if user is None:
            if guest:
                return GuestWorkspace()
            raise gr.Error("请先登录或注册，再使用此功能。")
        session_hash = getattr(request, "session_hash", None)
        if session_hash:
            self.accounts.bind_queue(session_hash, user["id"])
        with self._lock:
            self.prune()
            if user["id"] not in self._items:
                self.prune(force_space=True)
                if len(self._items) >= self.max_cached:
                    raise AccountError('当前工作空间繁忙，请稍后重试。', 503)
                workspace = self.factory(UserPaths.for_user(user["id"], self.base))
                workspace.policy = self.policy_for(user['id'])
                self._items[user["id"]] = workspace
                self._created[user['id']] = self.clock()
            self._last_used[user['id']] = self.clock()
            return self._items[user["id"]]

    @contextmanager
    def pin(self, workspace):
        if isinstance(workspace, GuestWorkspace):
            yield workspace
            return
        key = workspace.paths.root.name
        with self._lock:
            if self._items.get(key) is not workspace:
                raise AccountError('工作空间已释放，请刷新后重试。', 409)
            self._pins[key] = self._pins.get(key,0)+1
        try:
            yield workspace
        finally:
            with self._lock:
                self._pins[key] -= 1
                self._last_used[key] = self.clock()

    @contextmanager
    def session(self, request, guest=False):
        with self._lock:
            workspace = self.resolve(request, guest=guest)
            lease = self.pin(workspace)
            lease.__enter__()
        try:
            yield workspace
        finally:
            lease.__exit__(None,None,None)

    def validate_uploads(self, files, request):
        user = self.accounts.user(request.cookies.get(COOKIE)) if request else None
        if user is None:
            raise gr.Error("请先登录。")
        values = [files] if isinstance(files, str) else files or []
        if any(not self.accounts.owns_upload(p, user["id"]) for p in values):
            raise gr.Error("文件不属于当前账号，请重新上传。")

    def close(self):
        with self._lock:
            for key in list(self._items):
                if not self._pins.get(key,0) and not getattr(self._items[key],'busy',False):
                    self._remove(key)

    def stats(self):
        with self._lock:
            return {"cached_workspaces":len(self._items), "max_cached":self.max_cached,
                    "pinned_workspaces":sum(value>0 for value in self._pins.values()),
                    "active_uploads":self._uploading, **self.capacity.snapshot()}

    @contextmanager
    def upload_session(self, cached=True):
        with self._lock:
            if self._uploading >= config.MAX_ACTIVE_TASKS:
                raise AccountError('上传通道繁忙，请稍后重试。',503)
            if self.upload_root is not None:
                from core.resource_limits import directory_bytes
                root = Path(self.upload_root).resolve()
                if cached and directory_bytes(root) + (self._cached_uploading+1)*config.MAX_UPLOAD_BYTES*config.MAX_UPLOAD_BATCH > config.MAX_UPLOAD_CACHE_BYTES:
                    raise AccountError('上传暂存空间繁忙，请稍后重试或联系站点维护者。',503)
                disk_path = root
                while not disk_path.exists():
                    disk_path = disk_path.parent
                if shutil.disk_usage(disk_path).free < config.MIN_DISK_FREE_BYTES + config.MAX_UPLOAD_BYTES*config.MAX_UPLOAD_BATCH:
                    raise AccountError('服务器可用磁盘空间不足，请联系站点维护者。',503)
            self._uploading += 1
            self._cached_uploading += int(cached)
        try:
            yield
        finally:
            with self._lock:
                self._uploading -= 1
                self._cached_uploading -= int(cached)

    def maintenance(self):
        self.prune()
        # 与上传请求和所有工作空间使用者互斥，避免清理正在解析的暂存文件。
        with self._lock:
            if self._uploading or any(self._pins.values()) or self.capacity.snapshot()['active_tasks']:
                return
            if self.upload_root is None:
                return
            root = Path(self.upload_root).resolve()
            for filename in self.accounts.expired_uploads(config.UPLOAD_TTL_SECONDS):
                path = Path(filename).resolve()
                if path.is_relative_to(root) and path != root and path.is_file():
                    path.unlink(missing_ok=True)
                self.accounts.forget_upload(filename)

    def cancel_user(self, user_id):
        with self._lock:
            workspace = self._items.get(user_id)
            chat = getattr(workspace, '_chat', None)
            if not chat:
                return 0
            with chat._lock:
                ids = list(chat._active)
            return sum(bool(chat.stop(conversation_id)) for conversation_id in ids)


class WorkspaceScope:
    """Gradio 回调每次执行都重新验证 cookie；上下文仅覆盖本次回调。"""
    def __init__(self, registry):
        self.registry = registry
        self.current = ContextVar("knowva_workspace")

    def proxy(self, attribute):
        current = self.current
        class Proxy:
            def __getattr__(self, name):
                return getattr(getattr(current.get(), attribute), name)
        return Proxy()

    def background(self, fn):
        workspace = self.current.get()
        lease = self.registry.pin(workspace)
        lease.__enter__()
        context = copy_context()
        def run():
            try:
                context.run(fn)
            finally:
                lease.__exit__(None,None,None)
        thread = Thread(target=run, daemon=True, name='document-ingestion')
        try:
            thread.start()
        except Exception:
            lease.__exit__(None,None,None)
            raise
        return thread

    def guard(self, fn=None, *, guest=False, uploads=False):
        if fn is None:
            return lambda function: self.guard(function, guest=guest, uploads=uploads)
        signature = inspect.signature(fn)
        count = len(signature.parameters)
        def arguments(args, kwargs):
            args = list(args)
            request = kwargs.pop("request", None)
            if len(args) > count:
                request = args.pop()
            return args, kwargs, request
        if inspect.isgeneratorfunction(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                args, kwargs, request = arguments(args, kwargs)
                lease = self.registry.session(request, guest=guest)
                try:
                    workspace = lease.__enter__()
                except AccountError as exc:
                    raise gr.Error(str(exc)) from None
                iterator = None
                try:
                    if uploads:
                        self.registry.validate_uploads(args[0], request)
                        paths = [args[0]] if isinstance(args[0],str) else args[0] or []
                        if workspace.policy:
                            workspace.policy.validate_batch(paths)
                    while True:
                        self.registry.resolve(request, guest=guest)
                        token = self.current.set(workspace)
                        try:
                            if iterator is None:
                                iterator = fn(*args, **kwargs)
                            result = next(iterator)
                            # 等待模型或后台任务时，用户可能已退出或被停用。
                            self.registry.resolve(request, guest=guest)
                        except StopIteration:
                            return
                        except AccountError as exc:
                            raise gr.Error(str(exc)) from None
                        finally:
                            self.current.reset(token)
                        yield result
                except AccountError as exc:
                    raise gr.Error(str(exc)) from None
                finally:
                    try:
                        if iterator is not None:
                            token = self.current.set(workspace)
                            try:
                                iterator.close()
                            finally:
                                self.current.reset(token)
                    finally:
                        lease.__exit__(None,None,None)
        else:
            @wraps(fn)
            def wrapped(*args, **kwargs):
                try:
                    args, kwargs, request = arguments(args, kwargs)
                    with self.registry.session(request, guest=guest) as workspace:
                        token = self.current.set(workspace)
                        try:
                            return fn(*args, **kwargs)
                        finally:
                            self.current.reset(token)
                except AccountError as exc:
                    raise gr.Error(str(exc)) from None
        wrapped.__signature__ = signature.replace(parameters=[*signature.parameters.values(),
            inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=gr.Request)])
        wrapped.__annotations__ = {**fn.__annotations__, "request": gr.Request}
        return wrapped
