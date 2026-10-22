"""仅管理页面显示与侧栏交互，不接触聊天内容或检索状态。"""

app_ui_js = """(() => {
    const initialize = () => {
        const root = document.querySelector('#app-shell');
        if (!root) return false;
        root.dataset.view = 'chat';
        const mobile = () => window.matchMedia('(max-width: 767px)').matches;
        root.dataset.sidebar = mobile() ? 'closed' : 'open';
        const backdrop = () => document.querySelector('#sidebar-backdrop');
        const closeSidebar = () => {
            if (mobile()) root.dataset.sidebar = 'closed';
            backdrop()?.classList.remove('open');
        };
        document.addEventListener('click', (event) => {
            const action = event.target.closest('[data-action]')?.dataset.action;
            if (action === 'toggle-sidebar') {
                const isOpen = root.dataset.sidebar === 'open';
                root.dataset.sidebar = isOpen ? (mobile() ? 'closed' : 'collapsed') : 'open';
                backdrop()?.classList.toggle('open', mobile() && !isOpen);
            }
            if (action === 'close-sidebar') closeSidebar();
            if (event.target.closest('#knowledge-nav, #composer-attach')) {
                root.dataset.view = 'documents';
                closeSidebar();
            }
            if (event.target.closest('#new-chat, #conversation-history, #back-to-chat')) {
                root.dataset.view = 'chat';
                closeSidebar();
                requestAnimationFrame(() => document.querySelector('#composer-input textarea')?.focus());
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeSidebar();
        });
        document.addEventListener('keydown', (event) => {
            if (event.target.matches('#composer-input textarea') && event.key === 'Enter'
                && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey
                && !event.isComposing && event.keyCode !== 229 && !event.target.disabled) {
                event.preventDefault();
                event.stopImmediatePropagation();
                const send = document.querySelector('#composer-input .submit-button');
                if (send && !send.disabled) send.click();
            }
        }, true);
        const syncMessages = () => {
            const conversation = document.querySelector('#conversation');
            const hasMessages = Boolean(conversation?.querySelector('.message'));
            document.querySelector('#chat-view')?.classList.toggle('has-messages', hasMessages);
            const submit = document.querySelector('#composer-input .submit-button');
            if (submit) { submit.setAttribute('aria-label', '发送消息'); submit.title = '发送消息'; }
            const stop = document.querySelector('#composer-input .stop-button');
            if (stop) { stop.setAttribute('aria-label', '停止生成'); stop.title = '停止生成'; }
        };
        new MutationObserver(syncMessages).observe(root, {subtree:true, childList:true});
        syncMessages();
        const updateElapsed = () => {
            root.querySelectorAll('[data-upload-start]').forEach((element) => {
                const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(element.dataset.uploadStart)));
                element.textContent = seconds < 60 ? `已用时 ${seconds} 秒` : `已用时 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
            });
        };
        window.setInterval(updateElapsed, 1000);
        window.matchMedia('(max-width: 767px)').addEventListener('change', () => {
            root.dataset.sidebar = mobile() ? 'closed' : 'open';
            backdrop()?.classList.remove('open');
        });
        return true;
    };
    if (!initialize()) {
        const mounted = new MutationObserver(() => {
            if (initialize()) mounted.disconnect();
        });
        mounted.observe(document.body, {childList:true, subtree:true});
    }
})();"""
