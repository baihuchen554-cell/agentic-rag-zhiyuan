"""用临时 SQLite/Qdrant、可控时钟和离线模型验证资源预算与工作空间生命周期。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier, Event
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import gradio as gr
import config
from core.accounts import AccountError, AccountStore, COOKIE
from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore
from core.document_manager import DocumentManager
from core.resource_limits import TaskCapacity, UsageLedger, UserPolicy
from core.workspaces import UserPaths, WorkspaceRegistry, WorkspaceScope
from db.parent_store_manager import ParentStoreManager
from langchain_core.documents import Document
from test_generation_stop import ControlledGraph
from test_conversation_memory import rag_for


class TemporaryAccounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2030, 1, 1, 10, tzinfo=timezone.utc).timestamp()
        self.accounts = AccountStore(self.root / "accounts.sqlite3", clock=lambda: self.now)
        self.ledger = UsageLedger(self.accounts)


class UsageLedgerTests(TemporaryAccounts):
    def test_atomic_quota_allows_only_budgeted_concurrent_requests_for_each_metric(self):
        for metric in sorted(UsageLedger.METRICS):
            with self.subTest(metric=metric):
                ready = Barrier(12)

                def consume(_):
                    ready.wait(5)
                    try:
                        self.ledger.consume("alice", metric, 1, 5)
                        return 200
                    except AccountError as exc:
                        return exc.status

                with ThreadPoolExecutor(max_workers=12) as pool:
                    statuses = list(pool.map(consume, range(12)))
                self.assertEqual(statuses.count(200), 5)
                self.assertEqual(statuses.count(429), 7)
                self.assertEqual(self.ledger.summary("alice")[metric], 5)
                # Another account has an independent budget for the same day.
                self.ledger.consume("bob", metric, 5, 5)
                self.assertEqual(self.ledger.summary("bob")[metric], 5)

    def test_day_rolls_over_at_beijing_midnight_and_usage_survives_reopen(self):
        self.now = datetime(2030, 1, 1, 15, 59, 59, tzinfo=timezone.utc).timestamp()
        self.ledger.consume("alice", "questions", 2, 2)
        self.assertEqual(self.ledger.summary("alice")["day"], "2030-01-01")
        with self.assertRaises(AccountError):
            self.ledger.consume("alice", "questions", 1, 2)
        self.now += 1
        reopened = UsageLedger(AccountStore(self.accounts.path, clock=lambda: self.now))
        self.assertEqual(reopened.summary("alice")["day"], "2030-01-02")
        self.assertEqual(reopened.summary("alice")["questions"], 0)
        reopened.consume("alice", "questions", 1, 2)
        self.now -= 1
        self.assertEqual(self.ledger.summary("alice")["questions"], 2)

    def test_midnight_during_transaction_cannot_add_to_an_unchecked_day(self):
        with self.accounts.connect() as db:
            db.execute("INSERT INTO daily_usage VALUES (?,?,?,?)", ("alice", "2030-01-02", "questions", 2))
        # The first read is before midnight, a later read would be after midnight.
        # One operation must use the same captured day for both SELECT and INSERT.
        with patch.object(self.ledger, "day", side_effect=["2030-01-01", "2030-01-02"]):
            self.ledger.consume("alice", "questions", 1, 2)
        with self.accounts.connect() as db:
            amounts = dict(db.execute("SELECT day,amount FROM daily_usage WHERE user_id='alice'"))
        self.assertEqual(amounts, {"2030-01-01": 1, "2030-01-02": 2})

    def test_rejected_reservation_does_not_change_usage(self):
        self.ledger.consume("alice", "embedding_chars", 8, 10)
        with self.assertRaises(AccountError):
            self.ledger.consume("alice", "embedding_chars", 3, 10)
        self.assertEqual(self.ledger.summary("alice")["embedding_chars"], 8)
        self.ledger.consume("alice", "embedding_chars", 2, 10)
        self.assertEqual(self.ledger.summary("alice")["embedding_chars"], 10)


class TaskCapacityTests(unittest.TestCase):
    def test_user_exclusivity_global_ingestion_limit_and_idempotent_release(self):
        capacity = TaskCapacity(maximum=2)
        release_chat = capacity.acquire("alice", "chat")
        with self.assertRaises(AccountError) as conflict:
            capacity.acquire("alice", "ingest")
        self.assertEqual(conflict.exception.status, 429)
        release_ingest = capacity.acquire("bob", "ingest")
        with self.assertRaises(AccountError) as busy:
            capacity.acquire("carol", "chat")
        self.assertEqual(busy.exception.status, 503)
        release_chat()
        release_chat()
        with self.assertRaises(AccountError):
            capacity.acquire("carol", "ingest")
        with capacity.claim("carol", "chat"):
            self.assertEqual(capacity.snapshot()["active_tasks"], 2)
        self.assertEqual(capacity.snapshot()["active_tasks"], 1)
        release_ingest()
        self.assertEqual(capacity.snapshot()["active_tasks"], 0)
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with capacity.claim("carol", "ingest"):
                raise RuntimeError("test failure")
        self.assertEqual(capacity.snapshot()["active_tasks"], 0)


class GraphConcurrencyConfigTests(unittest.TestCase):
    def test_fresh_config_defaults_to_two_and_rejects_single_stream_worker(self):
        def fresh_config():
            specification = importlib.util.spec_from_file_location("_knowva_resource_test_config", config.__file__)
            module = importlib.util.module_from_spec(specification)
            # A regression check must not reload a real site's secrets or mutate the
            # already imported config used by other tests and live SDK objects.
            with patch("dotenv.load_dotenv", return_value=False):
                specification.loader.exec_module(module)
            return module

        with patch.dict(os.environ):
            os.environ.pop("GRAPH_MAX_CONCURRENCY", None)
            self.assertEqual(fresh_config().GRAPH_MAX_CONCURRENCY, 2)
            os.environ["GRAPH_MAX_CONCURRENCY"] = "1"
            with self.assertRaisesRegex(ValueError, "GRAPH_MAX_CONCURRENCY"):
                fresh_config()
            os.environ["GRAPH_MAX_CONCURRENCY"] = "2"
            self.assertEqual(fresh_config().GRAPH_MAX_CONCURRENCY, 2)


class UserPolicyTests(TemporaryAccounts):
    def setUp(self):
        super().setUp()
        self.user, _ = self.accounts.register("alice", "Alice", "strong-password-123")
        self.paths = UserPaths.for_user(self.user["id"], self.root / "users")
        self.paths.markdown.mkdir(parents=True)
        self.capacity = TaskCapacity(maximum=2)
        self.policy = UserPolicy(self.user["id"], self.paths, self.ledger, self.capacity)
        self.collection = SimpleNamespace(add_documents=Mock())
        self.parents = ParentStoreManager(self.paths.parents)
        self.chunker = SimpleNamespace(create_chunks_single=Mock(return_value=(
            [("p1", Document(page_content="parent", metadata={"source": "document.md"}))],
            [Document(page_content="正文", metadata={"parent_id": "p1"})],
        )))
        self.rag = SimpleNamespace(markdown_dir=self.paths.markdown, parent_store=self.parents,
            chunker=self.chunker, collection_name="documents", vector_db=SimpleNamespace(
                get_collection=Mock(return_value=self.collection), delete_sources=Mock()))
        self.manager = DocumentManager(self.rag, policy=self.policy)
        self.source = self.root / "document.md"
        self.source.write_text("正文", encoding="utf-8")

    def test_oversized_pdf_rejected_before_conversion_chunking_or_embedding(self):
        import pymupdf
        pdf = self.root / "pages.pdf"
        with pymupdf.open() as document:
            document.new_page()
            document.new_page()
            document.save(pdf)
        with patch.object(config, "MAX_PDF_PAGES", 1), patch("core.document_manager.pdf_to_markdown") as convert:
            with self.assertRaises(AccountError) as error:
                self.manager.add_documents([str(pdf)])
        self.assertEqual(error.exception.status, 413)
        convert.assert_not_called()
        self.chunker.create_chunks_single.assert_not_called()
        self.collection.add_documents.assert_not_called()
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)

    def test_oversized_upload_and_excess_document_count_rejected_before_parsing(self):
        self.source.write_text("123456", encoding="utf-8")
        with patch.object(config, "MAX_UPLOAD_BYTES", 5):
            with self.assertRaises(AccountError):
                self.manager.add_documents([str(self.source)])
        (self.paths.markdown / "existing.md").write_text("old", encoding="utf-8")
        with patch.object(config, "MAX_DOCUMENTS", 1):
            with self.assertRaises(AccountError):
                self.manager.add_documents([str(self.source)])
        self.chunker.create_chunks_single.assert_not_called()
        self.collection.add_documents.assert_not_called()
        self.assertFalse((self.paths.markdown / self.source.name).exists())

    def test_long_converted_text_rejected_before_chunking_and_rolled_back(self):
        self.source.write_text("过长的正文", encoding="utf-8")
        with patch.object(config, "MAX_DOCUMENT_CHARS", 2):
            self.assertEqual(self.manager.add_documents([str(self.source)]), (0, 1))
        self.chunker.create_chunks_single.assert_not_called()
        self.collection.add_documents.assert_not_called()
        self.assertFalse((self.paths.markdown / self.source.name).exists())
        self.assertEqual(self.ledger.summary(self.policy.user_id)["embedding_chars"], 0)

    def test_chunk_and_embedding_budgets_checked_before_model_or_parent_writes(self):
        children = [Document(page_content="one"), Document(page_content="two")]
        self.chunker.create_chunks_single.return_value = (
            [("p1", Document(page_content="parent"))], children)
        with patch.object(config, "MAX_DOCUMENT_CHUNKS", 1):
            self.assertEqual(self.manager.add_documents([str(self.source)]), (0, 1))
        self.assertEqual(self.parents.list_sources(), [])
        self.assertEqual(self.ledger.summary(self.policy.user_id)["embedding_chars"], 0)
        with patch.object(config, "DAILY_EMBEDDING_CHARS", 5):
            self.assertEqual(self.manager.add_documents([str(self.source)]), (0, 1))
        self.collection.add_documents.assert_not_called()
        self.assertEqual(list(self.paths.parents.glob("*.json")), [])
        self.assertFalse((self.paths.markdown / self.source.name).exists())
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)

    def test_question_quota_and_storage_failure_do_not_invoke_model_or_save_turn(self):
        graph = ControlledGraph()
        chat = ChatInterface(rag_for(graph), ConversationStore(self.paths.history), policy=self.policy)
        with patch.object(config, "DAILY_QUESTIONS", 1):
            run = chat.begin_generation("第一个问题", [], "first")
            chat.stop("first")
            with self.assertRaises(AccountError):
                chat.begin_generation("第二个问题", [], "second")
        self.assertEqual(graph.calls, [])
        self.assertFalse(chat.store.exists("second"))
        with patch.object(config, "USER_STORAGE_BYTES", 1):
            with self.assertRaises(AccountError):
                chat.begin_generation("存储已满", [], "storage")
        self.assertFalse(chat.store.exists("storage"))
        self.assertEqual(self.ledger.summary(self.policy.user_id)["questions"], 1)
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)

    def test_disabled_during_embedding_batch_stops_later_paid_calls_and_rolls_back(self):
        self.chunker.create_chunks_single.return_value = (
            [("p1", Document(page_content="parent", metadata={"source": self.source.name}))],
            [Document(page_content=f"chunk {i}") for i in range(4)])

        def disable_after_first_batch(*args, **kwargs):
            self.accounts.set_status(self.user["id"], True, "server-console")

        self.collection.add_documents.side_effect = disable_after_first_batch
        events = []
        with patch.object(config, "EMBEDDING_BATCH_SIZE", 1):
            self.assertEqual(self.manager.add_documents([str(self.source)], events.append), (0, 1))
        self.assertEqual(self.collection.add_documents.call_count, 1)
        self.rag.vector_db.delete_sources.assert_called_once_with("documents", [self.source.name])
        self.assertEqual(list(self.paths.parents.glob("*.json")), [])
        self.assertFalse((self.paths.markdown / self.source.name).exists())
        self.assertEqual(events[-1].failed, 1)
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)

    def test_disabled_before_ingestion_or_chat_rejects_before_paid_work(self):
        self.accounts.set_status(self.user["id"], True, "server-console")
        with self.assertRaises(AccountError):
            self.manager.add_documents([str(self.source)])
        graph = ControlledGraph()
        chat = ChatInterface(rag_for(graph), ConversationStore(self.paths.history), policy=self.policy)
        with self.assertRaises(AccountError):
            chat.begin_generation("已停用", [], "never")
        self.collection.add_documents.assert_not_called()
        self.chunker.create_chunks_single.assert_not_called()
        self.assertEqual(graph.calls, [])
        self.assertFalse(chat.store.exists("never"))
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)

    def test_unexpected_vector_growth_is_detected_after_batch_and_rolled_back(self):
        # A backend can allocate more than a preflight estimate (e.g. SQLite pages).
        # The policy must recheck real disk usage and stop before another paid batch.
        vector_blob = self.paths.root / "unexpected-index-growth.bin"

        def grow_index(*args, **kwargs):
            vector_blob.write_bytes(b"x" * (2 * 1024 * 1024))

        self.collection.add_documents.side_effect = grow_index
        self.rag.vector_db.delete_sources.side_effect = lambda *args: vector_blob.unlink(missing_ok=True)
        events = []
        with patch.object(config, "USER_STORAGE_BYTES", 1024 * 1024):
            self.assertEqual(self.manager.add_documents([str(self.source)], events.append), (0, 1))
        self.assertEqual(self.collection.add_documents.call_count, 1)
        self.rag.vector_db.delete_sources.assert_called_once_with("documents", [self.source.name])
        self.assertEqual(events[-1].failed, 1)
        self.assertFalse(vector_blob.exists())
        self.assertFalse((self.paths.markdown / self.source.name).exists())
        self.assertEqual(list(self.paths.parents.glob("*.json")), [])
        self.assertEqual(self.ledger.summary(self.policy.user_id)["embedding_chars"], 2)
        self.assertEqual(self.capacity.snapshot()["active_tasks"], 0)


class CachedWorkspace:
    """真实聊天 SQLite + 可观察的 close，不初始化远程模型。"""
    def __init__(self, paths):
        self.paths = paths
        paths.root.mkdir(parents=True, exist_ok=True)
        self.store = ConversationStore(paths.history)
        self.closed = 0
        self.policy = None
        self._chat = None

    @property
    def busy(self):
        return bool(self._chat and self._chat.busy)

    def close(self):
        self.closed += 1


class PersistentVectorWorkspace(CachedWorkspace):
    def __init__(self, paths):
        super().__init__(paths)
        from qdrant_client import QdrantClient, models
        self.client = QdrantClient(path=str(paths.vectors))
        if not self.client.collection_exists("documents"):
            self.client.create_collection("documents", vectors_config=models.VectorParams(
                size=2, distance=models.Distance.COSINE))
        self.parents = ParentStoreManager(paths.parents)

    def close(self):
        self.client.close()
        super().close()


class WorkspaceLifecycleTests(TemporaryAccounts):
    def setUp(self):
        super().setUp()
        self.monotonic = 100.0
        self.users, self.requests = [], []
        for name in ("alice", "bob", "carol"):
            user, _ = self.accounts.register(name, name.title(), "strong-password-123")
            token, _ = self.accounts.new_session(user["id"])
            self.users.append(user)
            self.requests.append(SimpleNamespace(cookies={COOKIE: token}, session_hash=None))
        self.registry = WorkspaceRegistry(self.accounts, base=self.root / "users", factory=CachedWorkspace,
            clock=lambda: self.monotonic, max_cached=2, idle_seconds=10)
        self.addCleanup(self.registry.close)

    def test_lru_evicts_only_unpinned_workspace_then_idle_cleanup_releases_all(self):
        alice = self.registry.resolve(self.requests[0])
        with self.registry.pin(alice):
            self.monotonic += 1
            bob = self.registry.resolve(self.requests[1])
            self.monotonic += 1
            carol = self.registry.resolve(self.requests[2])
            self.assertEqual(bob.closed, 1)
            self.assertEqual(alice.closed, 0)
            self.assertEqual(carol.closed, 0)
            self.assertEqual(self.registry.stats()["cached_workspaces"], 2)
            self.monotonic += 20
            self.registry.prune()
            self.assertEqual(alice.closed, 0)
            self.assertEqual(carol.closed, 1)
        self.monotonic += 11
        self.registry.prune()
        self.assertEqual(alice.closed, 1)
        self.assertEqual(self.registry.stats()["cached_workspaces"], 0)

    def test_absolute_age_recycles_active_cache_but_waits_for_pins_and_workers(self):
        with patch.object(config, "WORKSPACE_MAX_AGE_SECONDS", 30):
            alice = self.registry.resolve(self.requests[0])
            alice.store.save("chat", [{"role": "user", "content": "记忆保留"}], {})
            for moment in (108, 116, 124):
                self.monotonic = moment
                self.assertIs(self.registry.resolve(self.requests[0]), alice)
            self.monotonic = 131  # Last access was only 7 s ago, so idle TTL has not expired.
            self.registry.prune()
            self.assertEqual(alice.closed, 1)
            reopened = self.registry.resolve(self.requests[0])
            self.assertIsNot(reopened, alice)
            self.assertEqual(reopened.store.get("chat")["messages"][-1]["content"], "记忆保留")
            with self.registry.pin(reopened):
                self.monotonic += 31
                self.registry.prune()
                self.assertEqual(reopened.closed, 0)
            reopened._chat = SimpleNamespace(busy=True)
            self.registry.prune()
            self.assertEqual(reopened.closed, 0)
            reopened._chat.busy = False
            self.registry.prune()
            self.assertEqual(reopened.closed, 1)
            self.assertEqual(self.registry.stats()["cached_workspaces"], 0)

    def test_eviction_reopens_real_qdrant_parent_and_chat_data_without_loss(self):
        from qdrant_client import models
        self.registry.factory = PersistentVectorWorkspace
        self.registry.max_cached = 1
        alice = self.registry.resolve(self.requests[0])
        alice.client.upsert("documents", [models.PointStruct(id=1, vector=[1.0, 0.0])])
        alice.parents.save("p1", "私有正文", {"source": "alice.md"})
        alice.store.save("chat", [{"role": "user", "content": "保留这句话"}], {"summary": "重要记忆"})
        bob = self.registry.resolve(self.requests[1])
        self.assertEqual(alice.closed, 1)
        self.assertEqual(bob.client.count("documents").count, 0)
        self.assertEqual(bob.parents.list_sources(), [])
        self.assertFalse(bob.store.exists("chat"))
        reopened = self.registry.resolve(self.requests[0])
        self.assertIsNot(reopened, alice)
        self.assertEqual(reopened.client.count("documents").count, 1)
        self.assertEqual(reopened.parents.load_content("p1")["content"], "私有正文")
        self.assertEqual(reopened.store.get("chat")["messages"][-1]["content"], "保留这句话")
        self.assertEqual(reopened.store.get("chat")["memory"]["summary"], "重要记忆")

    def test_full_cache_rejects_new_user_while_every_workspace_is_pinned(self):
        with self.registry.session(self.requests[0]), self.registry.session(self.requests[1]):
            with self.assertRaises(AccountError) as error:
                self.registry.resolve(self.requests[2])
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(self.registry.stats()["cached_workspaces"], 2)
            self.assertEqual(self.registry.stats()["pinned_workspaces"], 2)
        self.assertEqual(self.registry.stats()["pinned_workspaces"], 0)
        self.registry.resolve(self.requests[2])
        self.assertEqual(self.registry.stats()["cached_workspaces"], 2)

    def test_rejected_generator_upload_releases_lease_and_does_not_run_callback(self):
        scope = WorkspaceScope(self.registry)
        ran = []

        def upload(files):
            ran.append(files)
            yield "never"

        guarded = scope.guard(upload, uploads=True)
        with self.assertRaises(gr.Error):
            list(guarded([str(self.root / "foreign.md")], request=self.requests[0]))
        self.assertEqual(ran, [])
        self.assertEqual(self.registry.stats()["pinned_workspaces"], 0)
        self.monotonic += 11
        self.registry.prune()
        self.assertEqual(self.registry.stats()["cached_workspaces"], 0)

    def test_logout_while_generator_waits_discards_private_result_and_releases_lease(self):
        scope = WorkspaceScope(self.registry)
        waiting, release = Event(), Event()
        closed_under = []

        def delayed_private_result():
            try:
                waiting.set()
                release.wait(5)
                yield "private output must never reach the revoked session"
            finally:
                closed_under.append(scope.current.get().paths.root.name)

        iterator = scope.guard(delayed_private_result)(request=self.requests[0])
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(next, iterator)
            try:
                self.assertTrue(waiting.wait(2))
                self.assertEqual(self.registry.stats()["pinned_workspaces"], 1)
                self.accounts.logout(self.requests[0].cookies[COOKIE])
                release.set()
                with self.assertRaises(gr.Error):
                    pending.result(timeout=5)
            finally:
                release.set()
        iterator.close()
        self.assertEqual(closed_under, [self.users[0]["id"]])
        self.assertEqual(self.registry.stats()["pinned_workspaces"], 0)
        self.monotonic += 11
        self.registry.prune()
        self.assertEqual(self.registry.stats()["cached_workspaces"], 0)

    def test_background_work_holds_pin_after_frontend_generator_closes(self):
        scope = WorkspaceScope(self.registry)
        waiting, release = Event(), Event()
        observed = []

        def work():
            observed.append(scope.current.get().paths.root.name)
            waiting.set()
            release.wait(5)

        def upload():
            yield scope.background(work)

        iterator = scope.guard(upload)(request=self.requests[0])
        thread = next(iterator)
        try:
            self.assertTrue(waiting.wait(2))
            iterator.close()
            self.monotonic += 20
            self.registry.prune()
            self.assertEqual(self.registry.stats()["pinned_workspaces"], 1)
            self.assertEqual(self.registry.stats()["cached_workspaces"], 1)
            self.assertEqual(observed, [self.users[0]["id"]])
        finally:
            iterator.close()
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.registry.stats()["pinned_workspaces"], 0)
        self.monotonic += 11
        self.registry.prune()
        self.assertEqual(self.registry.stats()["cached_workspaces"], 0)

    def test_cancelled_chat_keeps_task_capacity_and_workspace_until_network_worker_exits(self):
        self.registry.max_cached = 1
        with self.registry.session(self.requests[0]) as workspace:
            graph = ControlledGraph()
            workspace._chat = ChatInterface(rag_for(graph), workspace.store, policy=workspace.policy)
            iterator = workspace._chat.chat("慢问题", [], "chat")
            next(iterator)
            next(iterator)
            self.assertTrue(graph.waiting.wait(2))
            run = workspace._chat._active["chat"]
            self.assertEqual(self.registry.cancel_user(self.users[0]["id"]), 1)
            list(iterator)
        try:
            self.assertTrue(workspace.busy)
            self.assertEqual(self.registry.capacity.snapshot()["active_tasks"], 1)
            with self.assertRaises(AccountError):
                workspace._chat.begin_generation("另一个请求", [], "another-chat")
            self.monotonic += 20
            self.registry.prune()
            self.assertEqual(workspace.closed, 0)
            with self.assertRaises(AccountError):
                self.registry.resolve(self.requests[1])
        finally:
            graph.release_old.set()
            run.worker.join(2)
            iterator.close()
        self.assertFalse(run.worker.is_alive())
        self.assertFalse(workspace.busy)
        self.assertEqual(self.registry.capacity.snapshot()["active_tasks"], 0)
        self.registry.prune()
        self.assertEqual(workspace.closed, 1)
        self.registry.resolve(self.requests[1])

    def test_expired_upload_cleanup_waits_for_requests_tasks_and_pins_and_stays_in_root(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        self.registry.upload_root = uploads
        pending = uploads / "pending.md"
        outside = self.root / "outside.md"
        for path in (pending, outside):
            path.write_text("preserve until safe", encoding="utf-8")
            self.accounts.record_upload(str(path), self.users[0]["id"])
        self.now += config.UPLOAD_TTL_SECONDS + 1
        with self.registry.upload_session():
            self.registry.maintenance()
            self.assertTrue(pending.exists())
        with self.registry.session(self.requests[0]):
            self.registry.maintenance()
            self.assertTrue(pending.exists())
        with self.registry.capacity.claim(self.users[0]["id"], "chat"):
            self.registry.maintenance()
            self.assertTrue(pending.exists())
        self.registry.maintenance()
        self.assertFalse(pending.exists())
        self.assertTrue(outside.exists())

    def test_simultaneous_uploads_share_global_capacity_and_release_every_counter(self):
        ready, attempted, release = Barrier(6), Barrier(7), Event()

        def upload(index):
            ready.wait(5)
            lease = self.registry.upload_session(cached=index % 2 == 0)
            entered = False
            try:
                try:
                    lease.__enter__()
                    entered, status = True, 200
                except AccountError as exc:
                    status = exc.status
                attempted.wait(5)
                if entered:
                    release.wait(5)
                return status
            finally:
                if entered:
                    lease.__exit__(None, None, None)
                    # A caller's duplicate cleanup must not decrement twice.
                    lease.__exit__(None, None, None)

        with patch.object(config, "MAX_ACTIVE_TASKS", 2), ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(upload, index) for index in range(6)]
            try:
                attempted.wait(5)
                self.assertEqual(self.registry.stats()["active_uploads"], 2)
            finally:
                release.set()
            statuses = [future.result(timeout=5) for future in futures]
        self.assertEqual(statuses.count(200), 2)
        self.assertEqual(statuses.count(503), 4)
        self.assertEqual(self.registry.stats()["active_uploads"], 0)
        with self.assertRaisesRegex(RuntimeError, "upload interrupted"):
            with self.registry.upload_session():
                raise RuntimeError("upload interrupted")
        self.assertEqual(self.registry.stats()["active_uploads"], 0)

    def test_staging_budget_rejects_cached_upload_without_deleting_existing_files(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        cached_file = uploads / "previous.md"
        cached_file.write_bytes(b"existing")
        self.registry.upload_root = uploads
        with patch.multiple(config, MAX_UPLOAD_BYTES=8, MAX_UPLOAD_BATCH=2,
                            MAX_UPLOAD_CACHE_BYTES=20, MIN_DISK_FREE_BYTES=100), \
                patch("core.workspaces.shutil.disk_usage", return_value=SimpleNamespace(free=1000)):
            with self.assertRaises(AccountError) as rejected:
                with self.registry.upload_session(cached=True):
                    self.fail("Full cache must reject before entering an upload session")
            self.assertEqual(rejected.exception.status, 503)
            self.assertEqual(self.registry.stats()["active_uploads"], 0)
            # Private API staging bypasses only the shared Gradio cache budget.
            with self.registry.upload_session(cached=False):
                self.assertEqual(self.registry.stats()["active_uploads"], 1)
        self.assertEqual(cached_file.read_bytes(), b"existing")
        self.assertEqual(self.registry.stats()["active_uploads"], 0)

    def test_low_disk_rejects_cached_and_private_upload_without_changing_data(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        cached_file = uploads / "previous.md"
        cached_file.write_bytes(b"existing")
        self.registry.upload_root = uploads
        with patch.multiple(config, MAX_UPLOAD_BYTES=8, MAX_UPLOAD_BATCH=2,
                            MAX_UPLOAD_CACHE_BYTES=1000, MIN_DISK_FREE_BYTES=100):
            for cached in (False, True):
                with self.subTest(cached=cached):
                    with patch("core.workspaces.shutil.disk_usage", return_value=SimpleNamespace(free=115)):
                        with self.assertRaises(AccountError) as rejected:
                            with self.registry.upload_session(cached=cached):
                                self.fail("Disk reserve must be checked before entering")
                    self.assertEqual(rejected.exception.status, 503)
                    self.assertEqual(self.registry.stats()["active_uploads"], 0)
                    self.assertEqual(cached_file.read_bytes(), b"existing")
            # Exact reserve + one full batch remains available and counter is reusable.
            with patch("core.workspaces.shutil.disk_usage", return_value=SimpleNamespace(free=116)):
                with self.registry.upload_session(cached=False):
                    self.assertEqual(self.registry.stats()["active_uploads"], 1)
        self.assertEqual(self.registry.stats()["active_uploads"], 0)


class SharedSparseTests(unittest.TestCase):
    def test_concurrent_workspaces_create_only_one_sparse_encoder(self):
        from db.vector_db_manager import SharedSparseEmbeddings
        ready = Barrier(10)
        factory = Mock(return_value=SimpleNamespace(embed_query=lambda text: text,
            embed_documents=lambda texts: texts))

        def obtain(_):
            ready.wait(5)
            return SharedSparseEmbeddings.get()

        with patch("db.vector_db_manager.FastEmbedSparse", factory), \
                patch.dict(SharedSparseEmbeddings._instances, clear=True):
            with ThreadPoolExecutor(max_workers=10) as pool:
                models = list(pool.map(obtain, range(10)))
            self.assertTrue(all(model is models[0] for model in models))
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(models[0].embed_query("test"), "test")
            self.assertEqual(models[0].embed_documents(["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
