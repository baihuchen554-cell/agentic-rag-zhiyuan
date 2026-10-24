"""账号界面离线测试使用真实存储与工作流，但不调用收费模型。"""
from types import SimpleNamespace
from core.workspaces import Workspace
from db.parent_store_manager import ParentStoreManager
from document_chunker import DocumentChunker
from rag_agent.graph import create_agent_graph
from test_conversation_memory import MemoryLlm, rag_for, search_child_chunks
from core.accounts import AccountError


class FakeVerifier:
    """只通过构造参数注入临时测试应用，正式入口始终用 TurnstileVerifier。"""
    site_key = '1x00000000000000000000AA'

    def require_configured(self):
        pass

    def verify(self, token, **kwargs):
        if token != 'test-valid-token':
            raise AccountError('人机验证未通过。')


class OfflineCollection:
    def add_documents(self, documents, **kwargs):
        return []


class OfflineWorkspace(Workspace):
    @property
    def rag(self):
        with self._lock:
            if self._rag is None:
                collection = OfflineCollection()
                self._rag = rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks]))
                self._rag.markdown_dir = self.paths.markdown
                self._rag.parent_store = ParentStoreManager(self.paths.parents)
                self._rag.chunker = DocumentChunker()
                self._rag.collection_name = 'documents'
                self._rag.vector_db = SimpleNamespace(get_collection=lambda name: collection,
                    delete_sources=lambda *args: None, delete_collection=lambda *args: None,
                    create_collection=lambda *args: None, close=lambda: None)
            return self._rag
