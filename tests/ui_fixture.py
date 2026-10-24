"""仅供离线 UI 测试注入的工作空间，不进入生产入口。"""
from types import SimpleNamespace
from contextlib import nullcontext
from core.chat_interface import ChatInterface
from core.document_manager import DocumentManager


def test_workspaces(rag_factory):
    rag = rag_factory()
    initialize = getattr(rag, "initialize", None)
    if initialize:
        initialize()
    chat = ChatInterface(rag)
    workspace = SimpleNamespace(store=chat.store, chat=chat, documents=DocumentManager(rag), policy=None)
    return SimpleNamespace(resolve=lambda request, guest=False: workspace,
                           validate_uploads=lambda files, request: None,
                           session=lambda request, guest=False: nullcontext(workspace),
                           pin=lambda workspace: nullcontext(workspace))
