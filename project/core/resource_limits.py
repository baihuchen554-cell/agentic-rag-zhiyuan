"""统一的用量记账、文档预算和跨 UI/API 的任务容量控制。"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import RLock
from langchain_core.callbacks import BaseCallbackHandler

import config
import re
from core.accounts import AccountError


class ActiveAccountCallback(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, policy):
        self.policy = policy

    def check(self, *args, **kwargs):
        self.policy.ledger.accounts.require_enabled(self.policy.user_id)

    on_chat_model_start = check
    on_llm_start = check
    on_tool_start = check
    on_retriever_start = check


class TaskCapacity:
    def __init__(self, maximum=None):
        self.maximum = maximum or config.MAX_ACTIVE_TASKS
        self._active = {}
        self._lock = RLock()

    def acquire(self, user_id, kind):
        with self._lock:
            if user_id in self._active:
                raise AccountError("你已有任务在处理，请等待完成或停止中的网络请求结束。", 429)
            if len(self._active) >= self.maximum or (kind == 'ingest' and 'ingest' in self._active.values()):
                raise AccountError("服务器当前繁忙，请稍后重试。", 503)
            self._active[user_id] = kind
        released = False

        def release():
            nonlocal released
            with self._lock:
                if not released:
                    self._active.pop(user_id, None)
                    released = True
        return release

    @contextmanager
    def claim(self, user_id, kind):
        release = self.acquire(user_id, kind)
        try:
            yield
        finally:
            release()

    def snapshot(self):
        with self._lock:
            return {"active_tasks": len(self._active), "capacity": self.maximum,
                    "ingestions": sum(kind == 'ingest' for kind in self._active.values())}


def directory_bytes(root):
    root = Path(root)
    total = 0
    if root.exists():
        for path in root.rglob('*'):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                # 并发对话可能刚好清理 WAL/SHM 或删除文档。
                continue
    return total


class UsageLedger:
    METRICS = {'questions', 'embedding_chars', 'upload_bytes'}

    def __init__(self, accounts):
        self.accounts = accounts
        with accounts.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS daily_usage (
                user_id TEXT NOT NULL, day TEXT NOT NULL, metric TEXT NOT NULL, amount INTEGER NOT NULL,
                PRIMARY KEY(user_id,day,metric))''')

    def day(self):
        return datetime.fromtimestamp(self.accounts.clock(), timezone(timedelta(hours=8))).date().isoformat()

    def consume(self, user_id, metric, amount, maximum):
        if metric not in self.METRICS or amount < 0:
            raise ValueError('Invalid usage metric')
        day = self.day()
        with self.accounts.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT amount FROM daily_usage WHERE user_id=? AND day=? AND metric=?',
                                 (user_id,day,metric)).fetchone()
            if (current[0] if current else 0) + amount > maximum:
                labels = {'questions':'今日问答次数', 'embedding_chars':'今日文档向量处理量', 'upload_bytes':'今日上传流量'}
                raise AccountError(labels[metric] + '已达上限，请明日再试。', 429)
            db.execute('INSERT INTO daily_usage VALUES (?,?,?,?) ON CONFLICT(user_id,day,metric) DO UPDATE SET amount=amount+excluded.amount',
                       (user_id,day,metric,amount))

    def summary(self, user_id):
        day = self.day()
        with self.accounts.connect() as db:
            rows = db.execute('SELECT metric,amount FROM daily_usage WHERE user_id=? AND day=?', (user_id,day)).fetchall()
        return {"day":day, **{metric:0 for metric in self.METRICS}, **dict(rows)}


class UserPolicy:
    def __init__(self, user_id, paths, ledger, capacity):
        self.user_id, self.paths, self.ledger, self.capacity = user_id, paths, ledger, capacity

    def consume_question(self, message):
        self.ledger.accounts.require_enabled(self.user_id)
        if not isinstance(message, str) or not message.strip() or len(message) > config.MAX_QUESTION_CHARS:
            raise AccountError(f"问题需要 1–{config.MAX_QUESTION_CHARS} 个字符。")
        self.check_storage(len(message.encode('utf-8')) * 8)
        self.ledger.accounts.limit('question-minute:'+self.user_id, 6, 60)
        self.ledger.consume(self.user_id,'questions',1,config.DAILY_QUESTIONS)

    def check_storage(self, additional=0):
        if directory_bytes(self.paths.root) + additional > config.USER_STORAGE_BYTES:
            raise AccountError('个人工作目录的存储预算已满，请清理文档或联系站点维护者。', 413)

    def validate_batch(self, paths):
        self.ledger.accounts.require_enabled(self.user_id)
        if len(paths) > config.MAX_UPLOAD_BATCH:
            raise AccountError(f"每批最多上传 {config.MAX_UPLOAD_BATCH} 个文档。", 413)
        self.check_storage()
        existing = {p.stem for p in self.paths.markdown.glob('*.md')}
        new = {Path(p).stem for p in paths} - existing
        if len(existing) + len(new) > config.MAX_DOCUMENTS:
            raise AccountError(f"知识库最多保存 {config.MAX_DOCUMENTS} 个文档，请先删除不需要的文档。", 413)
        for filename in paths:
            path = Path(filename)
            if (len(path.name)>160 or re.search(r'[<>:"/\\|?*\x00-\x1f]',path.name)
                    or path.name.endswith(('.', ' '))):
                raise AccountError('文档名称无效，请重命名后上传。')
            if path.suffix.lower() not in {'.pdf','.md'}:
                raise AccountError('仅支持 PDF 或 Markdown 文档。')
            if path.stat().st_size > config.MAX_UPLOAD_BYTES:
                raise AccountError(f"单个文件不能超过 {config.MAX_UPLOAD_BYTES//1024//1024} MB。", 413)
            if path.suffix.lower() == '.pdf':
                import pymupdf
                try:
                    with pymupdf.open(path) as document:
                        if document.needs_pass or len(document) > config.MAX_PDF_PAGES:
                            raise AccountError(f"PDF 需未加密，且不超过 {config.MAX_PDF_PAGES} 页。", 413)
                except AccountError:
                    raise
                except Exception:
                    raise AccountError('无法读取 PDF，请检查文件。') from None

    def validate_text(self, markdown_path):
        path = Path(markdown_path)
        # 先限制字节数，避免为检查内容而一次读取超大的转换结果。
        if path.stat().st_size > config.MAX_DOCUMENT_CHARS * 4:
            raise AccountError('文档正文过长，请拆分后上传。', 413)
        text = path.read_text(encoding='utf-8')
        if len(text) > config.MAX_DOCUMENT_CHARS:
            raise AccountError('文档正文过长，请拆分后上传。', 413)

    def before_index(self, markdown_path, chunks):
        self.ledger.accounts.require_enabled(self.user_id)
        self.validate_text(markdown_path)
        if len(chunks) > config.MAX_DOCUMENT_CHUNKS:
            raise AccountError('文档正文或分块数量超过上限，请拆分后上传。', 413)
        self.check_storage(128*1024 + sum(len(chunk.page_content.encode('utf-8')) * 4
            + config.DENSE_DIMENSIONS * 16 + 8192 for chunk in chunks))
        # 重试也会产生模型成本，因此已接受的向量处理尝试不退回额度。
        self.ledger.consume(self.user_id,'embedding_chars',sum(len(c.page_content) for c in chunks), config.DAILY_EMBEDDING_CHARS)

    def summary(self):
        return {**self.ledger.summary(self.user_id), 'documents':sum(1 for _ in self.paths.markdown.glob('*.md')),
                'storage_bytes':directory_bytes(self.paths.root), 'limits':{
                    'questions':config.DAILY_QUESTIONS, 'embedding_chars':config.DAILY_EMBEDDING_CHARS,
                    'upload_bytes':config.DAILY_UPLOAD_BYTES, 'documents':config.MAX_DOCUMENTS,
                    'storage_bytes':config.USER_STORAGE_BYTES, 'question_chars':config.MAX_QUESTION_CHARS,
                    'file_bytes':config.MAX_UPLOAD_BYTES, 'pdf_pages':config.MAX_PDF_PAGES}}
