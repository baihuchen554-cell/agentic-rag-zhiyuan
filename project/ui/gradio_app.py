"""knowva：极简文档问答界面，复用现有检索和文档管理服务。"""

from html import escape
from core.accounts import AccountStore
from core.workspaces import WorkspaceRegistry, WorkspaceScope
from ui.account_ui import ACCOUNT_DIALOG
from ui.settings_ui import SETTINGS_DIALOG
from pathlib import Path
from queue import Queue
from time import time
from dataclasses import replace
from urllib.parse import quote

import gradio as gr
import config

from core.document_manager import DocumentProgress
from core.conversation_store import normalize_history
from core.accounts import AccountError
from ui.upload_progress import render_upload_progress

ASSET_DIR = Path(config.ASSETS_DIR)
ICON_DIR = ASSET_DIR / "icons"
gr.set_static_paths(paths=[str(ASSET_DIR.resolve())])
BRAND_ICON_URL = "./gradio_api/file=" + quote(Path(config.APP_LOGO_PATH).resolve().as_posix(), safe="/:")


def _icon(name):
    return str(ICON_DIR / f"{name}.svg")


BRAND = f"""<div class="sidebar-brand"><img class="brand-mark" src="{BRAND_ICON_URL}" alt="{config.APP_NAME}标志" width="31" height="31">
<span>{config.APP_NAME}</span><button class="icon-button" data-action="toggle-sidebar" aria-label="收起侧栏" title="收起侧栏">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 4v16m13-14-6 6 6 6"/></svg></button></div>"""
HEADER = """<div id="sidebar-backdrop"><button id="sidebar-scrim" aria-label="关闭侧栏" data-action="close-sidebar"></button></div>
<header class="workspace-header"><div class="header-left">
<button class="icon-button" data-action="toggle-sidebar" aria-label="展开侧栏" title="展开侧栏">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></svg></button>
<span id="conversation-title">新的对话</span></div><span class="header-caption">文档问答</span></header>"""
WELCOME = """<div class="welcome-copy"><h1>有什么可以帮你？</h1>
<p>从你的文档开始，让复杂问题变得清晰。</p></div>"""
PROFILE = """<div class="workspace-profile" id="account-profile">
<button type="button" class="profile-trigger" data-account-action="login" id="account-entry" aria-label="登录或注册账号">
<span class="profile-avatar" id="account-avatar">K</span><span class="profile-copy"><strong id="account-name">登录 / 注册</strong><small id="account-caption">开启你的个人知识空间</small></span>
<svg class="profile-settings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m9.5 3-.6 2a8 8 0 0 0-1.7 1L5.1 5.5 3 9.1l1.5 1.5a8 8 0 0 0 0 2L3 14.9l2.1 3.6 2.1-.5a8 8 0 0 0 1.7 1l.6 2h5l.6-2a8 8 0 0 0 1.7-1l2.1.5 2.1-3.6-1.5-1.5a8 8 0 0 0 0-2L21 9.1l-2.1-3.6-2.1.5a8 8 0 0 0-1.7-1l-.6-2z"/><circle cx="12" cy="12" r="3"/></svg></button></div>"""


def create_gradio_ui(workspaces=None):
    workspaces = workspaces or WorkspaceRegistry(AccountStore(config.ACCOUNT_DB_PATH))
    scope = WorkspaceScope(workspaces)
    doc_manager = scope.proxy("documents")
    chat_service = scope.proxy("chat")
    store = scope.proxy("store")

    def header_for(title):
        return HEADER.replace('>新的对话</span>', f'>{escape(title)}</span>')

    def format_file_list():
        files = doc_manager.get_markdown_files()
        if not files:
            return '<div class="empty-documents"><div class="empty-doc-icon" aria-hidden="true">▱</div><h3>还没有文档</h3><p>上传 PDF 或 Markdown，开始你的第一次提问。</p></div>'
        return ""

    def file_updates():
        files = doc_manager.get_markdown_files()
        return (
            gr.update(value=format_file_list(), visible=not files),
            gr.update(choices=files, value=[], visible=bool(files)),
            gr.update(value="删除所选", interactive=False),
            gr.update(visible=False), [],
        )

    def upload_ready(files):
        count = len(files) if isinstance(files, list) else int(bool(files))
        return (gr.update(value=render_upload_progress(DocumentProgress("ready", total_files=count)), visible=bool(count)),
                gr.update(value="开始入库", interactive=True))

    def upload_handler(files):
        if not files:
            gr.Info("请先选择文档")
            return
        files = files if isinstance(files, list) else [files]
        started_at = time()
        events = Queue()
        latest = DocumentProgress("preparing", total_files=len(files))

        def busy_packet(update):
            return (gr.update(interactive=False), gr.skip(), gr.update(interactive=False),
                    gr.update(interactive=False), gr.update(visible=False), [],
                    gr.update(value=render_upload_progress(update, started_at), visible=True),
                    gr.update(value="正在入库…", interactive=False),
                    gr.update(interactive=False), gr.update(interactive=False))

        def report(update):
            nonlocal latest
            latest = update
            events.put(update)

        def process():
            try:
                doc_manager.add_documents(files, progress_callback=report)
            except Exception as exc:
                report(replace(latest, stage="complete", failed=max(1, latest.failed),
                               issues=(*latest.issues, str(exc) if isinstance(exc, AccountError) else "处理未完成，请刷新文档列表后重试。")))
            finally:
                events.put(None)

        yield busy_packet(latest)
        # 后台执行文档处理，阶段事件通过生成器推送，等待 API 时页面仍可更新。
        scope.background(process)
        while (update := events.get()) is not None:
            if update.stage != "complete":
                yield busy_packet(update)
        updates = list(file_updates())
        updates[1] = {**updates[1], "interactive": True}
        yield (gr.update(value=files if latest.failed else None, interactive=True), *updates,
               gr.update(value=render_upload_progress(latest), visible=True),
               gr.update(value="重试入库" if latest.failed else "开始入库", interactive=True),
               gr.update(interactive=True), gr.update(interactive=True))

    def prepare_delete(selected):
        selected = list(selected or [])
        if not selected:
            gr.Info("请先勾选要删除的文档")
            return gr.update(visible=False), "", [], gr.update(visible=False)
        names = "".join(f"<li>{escape(name)}</li>" for name in selected)
        message = f"<p>确认删除以下 {len(selected)} 个文档及其索引？</p><ul>{names}</ul>"
        return gr.update(visible=True), message, selected, gr.update(visible=False)

    def delete_selected_handler(selected):
        if not selected:
            gr.Info("请先勾选要删除的文档")
            return file_updates()
        try:
            count = doc_manager.delete_documents(selected)
            gr.Info(f"已删除 {count} 个文档")
        except Exception as exc:
            gr.Warning(f"删除失败：{exc}")
        return file_updates()

    def clear_handler():
        try:
            doc_manager.clear_all()
            gr.Info("知识库已清空")
        except Exception as exc:
            gr.Warning(f"无法清空文档：{exc}")
        return *file_updates(), gr.update(visible=False)

    def conversation_packet(conversation_id, messages, title, busy=False, choices=None):
        choices = store.list_conversations() if choices is None else choices
        selected = conversation_id if any(cid == conversation_id for _, cid in choices) else None
        return (messages, gr.update(value="", interactive=not busy, submit_btn=not busy, stop_btn=busy), conversation_id,
                gr.update(choices=choices, value=selected, interactive=not busy), header_for(title),
                gr.update(value="新建对话", interactive=not busy),
                gr.update(value="删除当前对话", interactive=not busy and store.exists(conversation_id)),
                gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), None)

    def new_conversation():
        return conversation_packet(store.new_id(), [], "新的对话")

    def select_conversation(conversation_id):
        saved = store.get(conversation_id)
        return conversation_packet(conversation_id, saved["messages"], saved["title"])

    def load_conversations():
        choices = store.list_conversations()
        conversation_id = choices[0][1] if choices else store.new_id()
        saved = store.get(conversation_id)
        return conversation_packet(conversation_id, saved["messages"], saved["title"], choices=choices)

    def prepare_conversation_delete(conversation_id):
        if not store.exists(conversation_id):
            gr.Info("请先选择一条历史对话")
            return gr.update(visible=False), "", None
        title = escape(store.get(conversation_id)["title"])
        return (gr.update(visible=True), f"<p>确认删除「{title}」？</p><p>聊天记录和该对话的记忆将一并删除。</p>", conversation_id)

    def delete_conversation_handler(pending_id, current_id):
        if not pending_id or pending_id != current_id:
            gr.Info("请重新选择要删除的对话")
            return select_conversation(current_id)
        try:
            if chat_service.delete_conversation(pending_id):
                gr.Info("对话及记忆已删除")
        except Exception:
            gr.Warning("删除失败，请稍后重试")
            return select_conversation(current_id)
        return load_conversations()

    def send_message(message, history, conversation_id):
        if not message or not message.strip():
            return
        conversation_id = conversation_id or store.new_id()
        if store.is_deleted(conversation_id):
            gr.Info("此对话已删除，请重新选择或新建对话")
            yield load_conversations()
            return
        previous = store.get(conversation_id)["messages"] or normalize_history(history)
        turn = [*previous, {"role": "user", "content": message.strip()}]
        title = next(item["content"][:24].replace("\n", " ") for item in turn if item["role"] == "user")
        answer = [{"role": "assistant", "content": "正在处理…"}]
        choices = [(title, conversation_id), *[(label, cid) for label, cid in store.list_conversations() if cid != conversation_id]]

        def packet(busy):
            return conversation_packet(conversation_id, turn + answer, title, busy, choices)

        generation = chat_service.begin_generation(message, previous, conversation_id)
        try:
            yield packet(True)
            try:
                for answer in chat_service.chat(message, previous, conversation_id, generation=generation):
                    if generation.cancelled.is_set():
                        break
                    yield packet(True)
            except Exception:
                answer = [{"role": "assistant", "content": "处理消息失败，请刷新页面后重试。"}]
            if generation.cancelled.is_set():
                answer = generation.response
            yield packet(False)
        finally:
            if not generation.completed and not generation.cancelled.is_set():
                chat_service.stop(conversation_id)

    def stop_generation(conversation_id):
        chat_service.stop(conversation_id)
        saved = store.get(conversation_id)
        return conversation_packet(conversation_id, saved["messages"], saved["title"])

    with gr.Blocks(title=config.APP_TITLE, fill_height=True, fill_width=True) as demo:
        gr.HTML(ACCOUNT_DIALOG + SETTINGS_DIALOG, elem_id="account-surface")
        pending_delete = gr.State([])
        conversation_id = gr.State(None)
        pending_conversation_delete = gr.State(None)
        with gr.Row(elem_id="app-shell"):
            with gr.Column(scale=0, min_width=248, elem_id="app-sidebar"):
                gr.HTML(BRAND, elem_id="sidebar-brand")
                new_chat_btn = gr.Button("新建对话", icon=_icon("new-chat"), elem_id="new-chat", elem_classes="nav-button", interactive=False)
                documents_btn = gr.Button("知识库", icon=_icon("documents"), elem_id="knowledge-nav", elem_classes="nav-button", interactive=False)
                gr.HTML('<div class="sidebar-divider"></div><div class="sidebar-label">历史对话</div>', elem_id="session-label")
                conversation_list = gr.Radio(choices=[], value=None, label="历史对话",
                                             show_label=False, container=False, elem_id="conversation-history")
                delete_conversation_btn = gr.Button("删除当前对话", icon=_icon("trash"), size="sm", interactive=False,
                                                     elem_id="delete-conversation")
                with gr.Column(visible=False, elem_id="conversation-delete-confirmation") as conversation_delete_confirmation:
                    conversation_delete_message = gr.HTML()
                    with gr.Row():
                        cancel_conversation_delete = gr.Button("取消", size="sm")
                        confirm_conversation_delete = gr.Button("确认删除", size="sm", variant="stop")
                gr.HTML(PROFILE, elem_id="workspace-profile")
            with gr.Column(scale=1, min_width=0, elem_id="workspace"):
                header = gr.HTML(HEADER, elem_id="workspace-header")
                with gr.Column(elem_id="chat-view") as chat_view:
                    gr.HTML(WELCOME, elem_id="welcome")
                    chatbot = gr.Chatbot(
                            label="聊天助手", show_label=False, container=False,
                            height="100%", min_height=0, layout="bubble", buttons=["copy"],
                            elem_id="conversation", placeholder="", group_consecutive_messages=True,
                            scale=1,
                        )
                    with gr.Column(elem_id="chat-surface", scale=0):
                        textbox = gr.Textbox(
                            placeholder="继续提问…", label="消息", show_label=False,
                            lines=1, max_lines=8, container=False, autofocus=True,
                            submit_btn=True, stop_btn=False, elem_id="composer-input", interactive=False,
                        )
                        attach_btn = gr.Button("添加文档", icon=_icon("plus"), size="sm", elem_id="composer-attach", interactive=False)
                    gr.HTML('<p class="composer-note">优先参考文档，资料不足时联网补充。请核对来源信息。</p>', elem_id="composer-note")
                with gr.Column(visible=False, elem_id="documents-view") as documents_view:
                    gr.HTML('<div class="documents-heading"><h1>你的知识库</h1><p>上传资料，让每一次回答都有据可依。</p></div>')
                    gr.HTML('<p class="upload-hint">选择或拖入 PDF、Markdown 文件，上传后点击开始入库。</p>')
                    files_input = gr.File(
                        label="上传文档", file_count="multiple", file_types=[".pdf", ".md"],
                        type="filepath", height=150, show_label=False, elem_id="document-upload",
                    )
                    with gr.Row(elem_id="document-actions"):
                        add_btn = gr.Button("开始入库", variant="primary", elem_id="add-documents")
                        refresh_btn = gr.Button("刷新列表", icon=_icon("refresh"), elem_id="refresh-documents")
                    upload_progress = gr.HTML(visible=False, elem_id="upload-progress")
                    gr.HTML('<h2 class="section-title">已入库的文档 · 可勾选删除</h2>')
                    initial_files = []
                    file_list = gr.HTML('<div class="empty-documents"><div class="empty-doc-icon" aria-hidden="true">▱</div><h3>还没有文档</h3><p>上传 PDF 或 Markdown，开始你的第一次提问。</p></div>', visible=True, elem_id="document-list")
                    document_selection = gr.CheckboxGroup(
                        choices=initial_files, value=[], label="选择文档", show_label=False,
                        visible=bool(initial_files), elem_id="document-selection",
                    )
                    delete_selected_btn = gr.Button(
                        "删除所选", interactive=False, size="sm", elem_id="delete-selected-documents",
                    )
                    with gr.Column(visible=False, elem_id="delete-confirmation") as delete_confirmation:
                        delete_message = gr.HTML()
                        with gr.Row():
                            cancel_delete = gr.Button("取消", size="sm")
                            confirm_delete = gr.Button("确认删除", variant="stop", size="sm")
                    with gr.Row(elem_id="knowledge-footer"):
                        back_btn = gr.Button("返回对话", size="sm", elem_id="back-to-chat")
                        clear_btn = gr.Button("清空知识库", size="sm", elem_id="clear-documents")
                    with gr.Column(visible=False, elem_id="clear-confirmation") as clear_confirmation:
                        gr.Markdown("确定清空知识库？这会移除全部文档及索引。")
                        with gr.Row():
                            cancel_clear = gr.Button("取消", size="sm")
                            confirm_clear = gr.Button("确认清空", variant="stop", size="sm")

        document_outputs = [file_list, document_selection, delete_selected_btn, delete_confirmation, pending_delete]
        for button in (documents_btn, attach_btn):
            button.click(scope.guard(lambda: (gr.update(visible=False), gr.update(visible=True))),
                         outputs=[chat_view, documents_view], queue=False, show_progress="hidden").then(
                             scope.guard(file_updates), outputs=document_outputs, show_progress="minimal")
        for button in (back_btn,):
            button.click(lambda: (gr.update(visible=True), gr.update(visible=False)),
                         outputs=[chat_view, documents_view], queue=False, show_progress="hidden")
        conversation_outputs = [chatbot, textbox, conversation_id, conversation_list, header, new_chat_btn,
                                delete_conversation_btn, chat_view, documents_view,
                                conversation_delete_confirmation, pending_conversation_delete]
        new_chat_btn.click(scope.guard(new_conversation), outputs=conversation_outputs, show_progress="hidden", queue=False)
        conversation_list.input(scope.guard(select_conversation), inputs=conversation_list,
                                outputs=conversation_outputs,
                                show_progress="hidden", queue=False)
        textbox.submit(scope.guard(send_message), inputs=[textbox, chatbot, conversation_id],
                       outputs=conversation_outputs,
                       concurrency_id="chat", concurrency_limit=config.MAX_ACTIVE_TASKS, show_progress="hidden")
        textbox.stop(scope.guard(stop_generation), inputs=conversation_id, outputs=conversation_outputs,
                     queue=False, show_progress="hidden")
        demo.load(scope.guard(load_conversations, guest=True), outputs=conversation_outputs, show_progress="hidden").then(
            lambda: (gr.update(interactive=True), gr.update(interactive=True)),
            outputs=[documents_btn, attach_btn], show_progress="hidden", queue=False)
        delete_conversation_btn.click(scope.guard(prepare_conversation_delete), inputs=conversation_id,
                                      outputs=[conversation_delete_confirmation, conversation_delete_message, pending_conversation_delete],
                                      queue=False, show_progress="hidden")
        cancel_conversation_delete.click(lambda: (gr.update(visible=False), None),
                                          outputs=[conversation_delete_confirmation, pending_conversation_delete], queue=False)
        confirm_conversation_delete.click(scope.guard(delete_conversation_handler), inputs=[pending_conversation_delete, conversation_id],
                                           outputs=conversation_outputs, concurrency_id="chat", concurrency_limit=config.MAX_ACTIVE_TASKS,
                                           show_progress="hidden")
        document_outputs = [file_list, document_selection, delete_selected_btn, delete_confirmation, pending_delete]
        document_selection.change(
            lambda selected: (gr.update(value=f"删除所选（{len(selected)}）" if selected else "删除所选",
                                       interactive=bool(selected)), gr.update(visible=False), [], gr.update(visible=False)),
            inputs=document_selection,
            outputs=[delete_selected_btn, delete_confirmation, pending_delete, clear_confirmation],
            queue=False, show_progress="hidden",
        )
        delete_selected_btn.click(
            prepare_delete, inputs=document_selection,
            outputs=[delete_confirmation, delete_message, pending_delete, clear_confirmation],
            queue=False, show_progress="hidden",
        )
        cancel_delete.click(lambda: (gr.update(visible=False), []),
                            outputs=[delete_confirmation, pending_delete], queue=False)
        confirm_delete.click(scope.guard(delete_selected_handler), inputs=pending_delete, outputs=document_outputs,
                             concurrency_id="knowledge_base", concurrency_limit=1, show_progress="minimal")
        files_input.upload(scope.guard(upload_ready), inputs=files_input, outputs=[upload_progress, add_btn],
                           queue=False, show_progress="hidden")
        add_btn.click(scope.guard(upload_handler, uploads=True), inputs=files_input,
                      outputs=[files_input, *document_outputs, upload_progress, add_btn, refresh_btn, clear_btn],
                      concurrency_id="knowledge_base", concurrency_limit=1, show_progress="hidden")
        refresh_btn.click(scope.guard(file_updates), outputs=document_outputs, show_progress="hidden")
        clear_btn.click(lambda: (gr.update(visible=True), gr.update(visible=False), []),
                        outputs=[clear_confirmation, delete_confirmation, pending_delete], queue=False)
        cancel_clear.click(lambda: gr.update(visible=False), outputs=clear_confirmation, queue=False)
        confirm_clear.click(scope.guard(clear_handler), outputs=[*document_outputs, clear_confirmation],
                            concurrency_id="knowledge_base", concurrency_limit=1, show_progress="minimal")
    demo.queue(max_size=config.QUEUE_MAX_SIZE)
    return demo
