"""补齐 Gradio 默认控件的中文文案，包括英文浏览器环境。"""

import gradio as gr


# 使用完整翻译键，覆盖默认文案，并补齐内置中文语言包缺少的条目。
ZH_TEXT = {
    "common.built_with": "构建于",
    "common.built_with_gradio": "使用 Gradio 构建",
    "common.clear": "清除",
    "common.download": "下载",
    "common.upload": "上传",
    "common.download_all": "下载全部",
    "common.edit": "编辑",
    "common.empty": "空",
    "common.error": "错误",
    "common.hosted_on": "托管于",
    "common.loading": "加载中",
    "common.logo": "标志",
    "common.or": "或",
    "common.remove": "移除",
    "common.runs": "运行记录",
    "common.runs_description": "查看保存在此浏览器中的运行记录",
    "common.back_to_app": "返回应用",
    "common.back_to_app_description": "返回应用页面",
    "common.settings": "设置",
    "common.share": "分享",
    "common.submit": "提交",
    "common.undo": "撤销",
    "common.no_devices": "未找到设备",
    "common.language": "语言",
    "common.display_theme": "显示主题",
    "common.pwa": "渐进式网页应用",
    "common.record": "录制",
    "common.stop_recording": "停止录制",
    "common.screen_studio": "屏幕录制",
    "common.share_gradio_tab": "正在分享应用标签页",
    "common.run": "运行",
    "upload_text.click_to_upload": "点击上传",
    "upload_text.drop_file": "将文件拖放到此处",
    "upload_text.paste_clipboard": "从剪贴板粘贴",
    "file.uploading": "正在上传…",
    "chatbot.edit": "编辑",
    "chatbot.retry": "重新生成",
    "chatbot.undo": "撤销",
    "chatbot.submit": "发送",
    "chatbot.cancel": "取消",
    "chatbot.like": "赞",
    "chatbot.dislike": "踩",
    "chatbot.clear": "清空对话",
    "chatbot.copy_message": "复制消息",
    "chatbot.copied_message": "已复制消息",
    "chat_interface.new_chat": "新建对话",
    "chat_interface.message_placeholder": "请输入消息…",
    "chat_interface.additional_inputs": "附加输入",
    "chat_interface.chatbot": "聊天助手",
    "chat_interface.conversation": "对话",
    "blocks.connection_can_break": "在移动设备上，离开此标签页或设备休眠可能中断连接并丢失排队位置。",
    "blocks.long_requests_queue": "当前排队时间较长，请稍候。",
    "blocks.lost_connection": "连接已断开，正在重新加入队列…",
    "blocks.waiting_for_inputs": "请等待文件上传完成后重试。",
    "errors.build_error": "应用构建失败",
    "errors.config_error": "应用配置有误",
    "errors.contact_page_author": "请联系应用维护者。",
    "errors.no_app_file": "未找到应用文件",
    "errors.runtime_error": "应用运行出错",
    "errors.space_not_working": "应用无法运行，原因：{0}",
    "errors.space_paused": "应用已暂停",
    "errors.use_via_api": "通过接口调用",
    "errors.use_via_api_or_mcp": "通过 API 或 MCP 调用",
}

chinese_i18n = gr.I18n(**{"en": ZH_TEXT, "zh-CN": ZH_TEXT, "zh-TW": ZH_TEXT})

# 页面已经是中文。尽早声明语言并禁止浏览器二次翻译，避免翻译器改写动态控件的 DOM。
chinese_page_head = """<meta name="google" content="notranslate">
<script>
document.documentElement.lang = 'zh-CN';
document.documentElement.setAttribute('translate', 'no');
document.documentElement.classList.add('notranslate');
</script>"""

# Gradio 的部分按钮提示和无障碍标签尚未接入翻译字典。
# 只替换这些控件的显示属性，不触碰消息正文、文件名、代码块或事件绑定。
chinese_ui_js = """(() => {
    const initialize = () => {
    const root = document.querySelector('.gradio-container');
    if (!root) return false;
    document.documentElement.lang = 'zh-CN';
    document.documentElement.setAttribute('translate', 'no');
    root.setAttribute('translate', 'no');
    root.classList.add('notranslate');
    const labels = {
        'More tabs': '更多标签页',
        'Click to upload or drop files': '点击上传或拖放文件',
        'File upload': '文件上传',
        'Copy conversation': '复制对话',
        'Copied conversation': '已复制对话',
        'chatbot conversation': '聊天对话',
        'Gradio footer navigation': '应用页脚导航',
        'copy': '复制', 'Copy': '复制', 'Copied': '已复制',
        'copied': '已复制', 'undo': '撤销', 'Submit': '发送',
        'Stop': '停止生成', 'Download': '下载', 'Remove': '移除'
    };
    const translate = (element) => {
        for (const attribute of ['title', 'aria-label', 'data-tooltip']) {
            const value = element.getAttribute(attribute);
            if (!value) continue;
            let translated = labels[value];
            if (attribute === 'aria-label' && value.startsWith("user's message: "))
                translated = '用户消息：' + value.slice(16);
            if (attribute === 'aria-label' && value.startsWith("bot's message: "))
                translated = '助手消息：' + value.slice(15);
            if (translated && translated !== value)
                element.setAttribute(attribute, translated);
        }
    };
    const scan = (node) => {
        if (!(node instanceof Element)) return;
        translate(node);
        node.querySelectorAll('[title], [aria-label], [data-tooltip]').forEach(translate);
    };
    scan(root);
    new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.type === 'attributes') translate(mutation.target);
            else mutation.addedNodes.forEach(scan);
        }
    }).observe(root, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: ['title', 'aria-label', 'data-tooltip']
    });
    return true;
    };
    if (!initialize()) {
        const mounted = new MutationObserver(() => {
            if (initialize()) mounted.disconnect();
        });
        mounted.observe(document.body, {childList: true, subtree: true});
    }
})();"""
