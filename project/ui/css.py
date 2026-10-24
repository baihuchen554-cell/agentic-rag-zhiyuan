"""knowva 界面的灰阶主题和响应式布局。"""

import gradio as gr
from gradio.themes.utils.fonts import Font

app_theme = gr.themes.Base(
    primary_hue="neutral", secondary_hue="neutral", neutral_hue="gray",
    font=[Font("Inter"), Font("Microsoft YaHei"), Font("sans-serif")],
).set(
    body_background_fill="#ffffff", body_background_fill_dark="#ffffff",
    body_text_color="#171717", body_text_color_dark="#171717",
    background_fill_primary="#ffffff", background_fill_primary_dark="#ffffff",
    block_background_fill="#ffffff", block_background_fill_dark="#ffffff",
    block_border_color="#e8e8e8", block_border_color_dark="#e8e8e8",
    input_background_fill="#f4f4f4", input_background_fill_dark="#f4f4f4",
    button_primary_background_fill="#171717", button_primary_background_fill_dark="#171717",
    button_primary_text_color="#ffffff", button_primary_text_color_dark="#ffffff",
)

custom_css = """
:root { --app-ink:#202124; --app-muted:#797b82; --app-rail:#f5f5f6; --app-input:#f1f2f4; --rail-width:264px; }
html,body { margin:0!important; background:#fff!important; color:#171717!important; }
body,button,textarea { font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif!important; }
.gradio-container { width:100%!important; max-width:none!important; padding:0!important; margin:0!important; background:#fff!important; }
.gradio-container>.main,.gradio-container>.main>.wrap { padding:0!important; gap:0!important; }
footer:not(.settings-footer),.built-with { display:none!important; }
#app-shell { height:100dvh; gap:0!important; flex-wrap:nowrap!important; overflow:hidden; }
#app-shell .html-container { padding:0!important; }
#app-sidebar { box-sizing:border-box; width:var(--rail-width)!important; min-width:var(--rail-width)!important; max-width:var(--rail-width)!important; height:100%; flex:none!important; gap:6px!important; padding:20px 12px 14px!important; background:var(--app-rail)!important; border-right:1px solid #ebebee; transition:margin-left 180ms ease,transform 180ms ease; }
#app-sidebar>.block,#app-sidebar>.form,#app-sidebar .html-container { background:transparent!important; }
#sidebar-brand,#session-label,#workspace-profile,#workspace-header,#welcome,#composer-note { padding:0!important; border:0!important; background:transparent!important; }
.sidebar-brand { display:flex; align-items:center; gap:10px; height:44px; padding:0 12px; font-size:23px; font-weight:650; }
.brand-mark { display:block; flex:none; width:31px; height:31px; object-fit:contain; }
.icon-button { display:inline-flex; justify-content:center; align-items:center; width:32px; height:32px; padding:6px; border:0; border-radius:7px; background:transparent; color:#777; cursor:pointer; }
.icon-button svg { width:20px; height:20px; }.icon-button:hover { background:#e8e8ea; }
.sidebar-brand .icon-button { margin-left:auto; }
#new-chat { margin-top:28px!important; }
#app-sidebar .nav-button { flex:none!important; justify-content:flex-start!important; height:46px; min-height:46px; padding:0 14px!important; gap:12px!important; font-size:15px!important; font-weight:450!important; border:0!important; box-shadow:none!important; background:transparent!important; color:var(--app-ink)!important; border-radius:9px!important; }
#app-sidebar .nav-button:hover { background:#e9e9ec!important; }
#app-sidebar .nav-button img { width:19px!important; height:19px!important; }
.sidebar-divider { height:16px; margin-top:14px; }
.sidebar-label { font-size:12px; color:#939398; padding:0 14px 10px; }
#conversation-history { flex:1!important; min-height:0!important; overflow-y:auto; padding:0!important; border:0!important; background:transparent!important; }
#conversation-history .wrap { display:flex!important; flex-direction:column!important; gap:3px!important; }
#conversation-history label { display:flex!important; width:100%; box-sizing:border-box; min-height:42px; border:0!important; border-radius:9px!important; background:transparent!important; padding:11px 13px!important; margin:0!important; box-shadow:none!important; }
#conversation-history label:hover { background:#ececef!important; }
#conversation-history label:has(input:checked) { background:#e7e7eb!important; }
#conversation-history input { position:absolute; opacity:0; width:1px; height:1px; }
#conversation-history label span { display:block; font-size:13px!important; font-weight:400!important; line-height:20px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#333!important; }
#conversation-history label:focus-within { outline:2px solid #999; outline-offset:-2px; }
#delete-conversation { flex:none!important; justify-content:flex-start!important; gap:9px!important; padding:9px 13px!important; border:0!important; background:transparent!important; color:#888!important; box-shadow:none!important; font-size:12px!important; border-radius:8px!important; }
#delete-conversation:hover { background:#ececef!important; color:#a24e4e!important; }
#delete-conversation:disabled { opacity:.4; }#delete-conversation img { width:16px; height:16px; }
#conversation-delete-confirmation { flex:none!important; min-height:0!important; gap:10px!important; padding:12px!important; border:1px solid #e5dcdc!important; background:#fffafa!important; border-radius:10px!important; }
#conversation-delete-confirmation p { font-size:12px!important; line-height:1.7!important; color:#875858!important; margin:0!important; overflow-wrap:anywhere; }
#conversation-delete-confirmation button { min-width:0!important; font-size:12px!important; border-radius:7px!important; padding:6px!important; }
#workspace-profile { flex:none!important; margin-top:auto!important; }
.workspace-profile { padding:12px 0 0; border-top:1px solid #e4e4e8; }
.profile-trigger { display:flex; align-items:center; gap:12px; width:100%; padding:10px!important; border:0!important; border-radius:12px!important; background:transparent!important; color:var(--app-ink)!important; text-align:left; cursor:pointer; }
.profile-trigger:hover { background:#e9e9ed!important; }
.profile-avatar { display:flex; flex:none; align-items:center; justify-content:center; width:44px; height:44px; overflow:hidden; border-radius:50%; background:#e3e3e8; color:#555861; font-size:18px; font-weight:600; }
.profile-avatar img { display:block; width:100%; height:100%; object-fit:cover; }
.profile-copy { display:block; flex:1; min-width:0; }
.profile-copy strong { display:block; font-size:15px; font-weight:550; line-height:1.5; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.workspace-profile small { display:block; margin-top:3px; color:var(--app-muted); font-size:12px; line-height:1.5; }
.profile-settings-icon { flex:none; width:19px; height:19px; color:#777b83; }
html[data-account=guest] .profile-settings-icon { display:none; }
#workspace { height:100%; min-height:0!important; min-width:0!important; gap:0!important; padding:0!important; background:#fff; }
.workspace-header { height:68px; display:flex; align-items:center; justify-content:space-between; padding:0 30px; }
.header-left { display:flex; align-items:center; gap:12px; min-width:0; font-size:17px; font-weight:550; }
#conversation-title { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.header-left .icon-button { display:none; }.header-caption { flex-shrink:0; color:#aaa; font-size:11px; padding-left:16px; }
#workspace-header { flex:none!important; }
#chat-view { flex:1!important; min-height:0!important; padding:0 32px 13px!important; gap:12px!important; align-items:center; justify-content:center; }
#welcome { width:100%; flex:none!important; }
.welcome-copy { text-align:center; margin-bottom:22px; }.welcome-copy h1 { font-size:29px!important; font-weight:600!important; color:#171717!important; margin:0 0 12px!important; letter-spacing:-.7px; }
.welcome-copy p { font-size:14px!important; color:#999!important; margin:0!important; line-height:1.7; }
#conversation { display:none!important; width:100%!important; max-width:800px; min-height:0!important; border:0!important; box-shadow:none!important; background:transparent!important; padding:0!important; }
#chat-view.has-messages { justify-content:flex-start; }
#chat-view.has-messages #welcome { display:none!important; }
#chat-view.has-messages #conversation { display:flex!important; flex:1!important; height:0!important; }
#conversation .message-wrap { padding:10px 2px 18px!important; }
#conversation .message { font-size:15px!important; line-height:1.85!important; border:0!important; box-shadow:none!important; color:#252525!important; }
#conversation .message.user { background:#f1f2f4!important; border-radius:22px!important; padding:11px 18px!important; max-width:85%!important; }
#conversation .message.bot { background:transparent!important; padding:12px 0!important; max-width:100%!important; }
#conversation .bubble-wrap,#conversation .wrapper,#conversation .message-row { background:transparent!important; }
#conversation p { line-height:1.85!important; }#conversation .prose { font-size:15px!important; }
#conversation button { color:#999!important; }
#conversation .top-panel { display:none!important; }
#conversation .message-wrap { gap:0!important; }
#conversation .message-row { margin:20px 0 0!important; }
#conversation .user-row { max-width:85%!important; width:fit-content!important; align-self:flex-end; }
#conversation .user.message { max-width:100%!important; box-sizing:border-box; }
#conversation .bot-row { max-width:100%!important; width:100%!important; }
#conversation .message-buttons { margin:3px 0 6px!important; padding:0!important; min-height:24px!important; }
#conversation .message-buttons-right { display:none!important; }
#conversation .icon-button-wrapper { border:0!important; background:transparent!important; padding:0!important; box-shadow:none!important; }
#conversation .icon-button { width:25px!important; height:25px!important; border:0!important; background:transparent!important; padding:5px!important; box-shadow:none!important; }
#conversation .icon-button svg { width:15px!important; height:15px!important; }
#conversation .message.thought { border:0!important; border-radius:0!important; background:transparent!important; padding-top:14px!important; }
#conversation .thought-group { border:1px solid #e9e9ed!important; border-radius:11px!important; background:#fafafa!important; font-size:13px!important; overflow:hidden; }
#conversation .thought-group .title { padding:9px 12px!important; gap:4px!important; }
#conversation .thought-group .prose { font-size:12px!important; color:#777!important; }
#conversation .thought-group p { margin:0!important; line-height:1.7!important; }
#chat-surface { position:relative; flex:none!important; width:100%!important; max-width:800px; gap:0!important; padding:0!important; min-width:0!important; }
#chat-surface .form { border:0!important; padding:0!important; box-shadow:none!important; }
#composer-input { background:var(--app-input)!important; border:1px solid #eeeff1!important; border-radius:23px!important; padding:0!important; box-shadow:none!important; overflow:hidden!important; }
#composer-input:focus-within { border-color:#d8d9dd!important; }
#composer-input textarea { font-size:15px!important; line-height:1.6!important; color:#262626!important; border:0!important; background:transparent!important; outline:none!important; box-shadow:none!important; padding:17px 21px 52px!important; min-height:114px!important; resize:none!important; }
#composer-input textarea::placeholder { color:#93969d!important; }
#composer-input button { position:absolute!important; bottom:12px!important; right:14px!important; width:34px!important; height:34px!important; min-width:34px!important; min-height:34px!important; border-radius:50%!important; border:0!important; color:#fff!important; background:#171717!important; padding:8px!important; box-shadow:none!important; }
#composer-input .submit-button svg { display:block!important; width:20px!important; height:20px!important; }
#composer-input .stop-button svg { display:none!important; }
#composer-input .stop-button:after { content:""; display:block; width:12px; height:12px; border-radius:2px; background:#fff; margin:auto; }
#composer-input .stop-button { opacity:1!important; cursor:pointer; }
#composer-input .submit-button:disabled { opacity:.35; }
#composer-attach { position:absolute!important; bottom:14px; left:16px; z-index:4; width:auto!important; min-width:0!important; height:30px!important; min-height:30px!important; padding:3px 7px!important; gap:8px!important; color:#666!important; background:transparent!important; border:0!important; border-radius:7px!important; box-shadow:none!important; font-size:12px!important; font-weight:400!important; }
#composer-attach:hover { background:#e6e7ea!important; }#composer-attach img { width:18px; height:18px; }
#composer-note { width:100%; flex:none!important; }.composer-note { margin:0!important; text-align:center; font-size:10px; color:#aaa; line-height:1.6; }
#sidebar-backdrop { display:contents!important; }#sidebar-scrim { display:none; }
#app-shell[data-sidebar="collapsed"] #app-sidebar { margin-left:calc(-1 * var(--rail-width)); }
#app-shell[data-sidebar="collapsed"] .header-left .icon-button { display:inline-flex; }
button { transition:background 140ms ease; }button:focus-visible { outline:2px solid #888!important; outline-offset:3px; }
@media(max-width:767px) {
 #app-sidebar { position:fixed; top:0; left:0; z-index:50; width:260px!important; min-width:260px!important; max-width:260px!important; transform:translateX(-100%); margin-left:0!important; }
 #app-shell[data-sidebar="open"] #app-sidebar { transform:translateX(0); }
 .header-left .icon-button { display:inline-flex; }.workspace-header { height:58px; padding:0 13px; }.header-left { font-size:14px; }.header-caption { display:none; }
 #chat-view { padding:0 16px 10px!important; gap:9px!important; }.welcome-copy h1 { font-size:25px!important; }.welcome-copy p { font-size:12px!important; }
 #composer-input textarea { font-size:14px!important; min-height:105px!important; padding-left:17px!important; }#composer-input { border-radius:21px!important; }
 .composer-note { font-size:9px; }#conversation .message,#conversation .prose { font-size:14px!important; }
 #documents-view { padding:25px 20px 35px!important; }
 #sidebar-backdrop.open #sidebar-scrim { display:block; position:fixed; inset:0; z-index:45; border:0; padding:0; background:#0004; }
}
@media(prefers-reduced-motion:reduce) { * { transition:none!important; scroll-behavior:auto!important; } }
#documents-view { box-sizing:border-box; width:100%; max-width:850px; align-self:center; flex:1!important; min-height:0!important; padding:48px 36px 64px!important; gap:22px!important; overflow-y:auto; }
#documents-view > * { flex-shrink:0!important; }
.documents-heading h1 { margin:0 0 10px!important; font-size:27px!important; font-weight:600!important; letter-spacing:-.6px; }
.documents-heading p { margin:0!important; color:#8a8a8a!important; font-size:14px; }
#document-upload { border:1px dashed #d8d8d8!important; background:#fafafa!important; border-radius:16px!important; padding:12px!important; box-shadow:none!important; }
#document-upload .wrap { border:0!important; }
#document-upload .file { background:#fff!important; border:1px solid #e9e9e9!important; color:#444!important; }
#document-upload .file td { padding:14px 12px!important; }
#document-upload .file .stem,#document-upload .file .ext { color:#444!important; }
#document-upload button { font-size:13px!important; color:#707070!important; }
#document-upload button .wrap { color:#747474!important; }
#document-upload .icon-wrap { color:#929292!important; }
.upload-hint { margin:0 0 -10px!important; font-size:12px; color:#868686; line-height:1.7; }
#upload-progress { padding:0!important; }
.upload-status { border:1px solid #e7e7e7; border-radius:14px; padding:20px; background:#fcfcfc; color:#303030; }
.upload-status-top { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.upload-status-top strong { font-size:14px; font-weight:600; }
.upload-elapsed { font-size:11px; color:#8b8b8b; white-space:nowrap; font-variant-numeric:tabular-nums; }
.upload-filename { margin:8px 0 18px!important; font-size:12px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.upload-steps { display:flex; list-style:none!important; gap:12px; margin:0!important; padding:0!important; }
.upload-steps li { display:flex; align-items:center; gap:7px; flex:1; font-size:12px; color:#a0a0a0; white-space:nowrap; }
.upload-steps li:not(:last-child)::after { content:""; height:1px; background:#e5e5e5; flex:1; margin-left:3px; }
.upload-step-dot { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border:1px solid #dedede; border-radius:50%; flex:none; font-size:11px; }
.upload-steps .active { color:#222; font-weight:500; }.upload-steps .active .upload-step-dot { color:white; background:#222; border-color:#222; }
.upload-steps .done { color:#535353; }.upload-steps .done .upload-step-dot { background:#eeeeed; border-color:transparent; color:#444; }
.upload-meter { height:4px; overflow:hidden; background:#e9e9e9; border-radius:5px; margin-top:20px; }
.upload-meter span { display:block; height:100%; background:#353535; border-radius:5px; transition:width 180ms ease; }
.upload-meter.indeterminate span { width:24%; animation:upload-working 1.8s ease-in-out infinite; }
@keyframes upload-working { from { transform:translateX(-100%); } to { transform:translateX(520%); } }
.upload-detail { margin:12px 0 0!important; color:#777; font-size:12px; line-height:1.7; }
.upload-status[data-state="done"] { background:#fafbf9; border-color:#e4e8e0; }
.upload-status[data-state="error"] { background:#fdfafa; border-color:#eedfdf; }
.upload-status[data-state="error"] .upload-status-top strong { color:#934c4c; }
.upload-issues { margin:12px 0 0!important; padding-left:16px!important; color:#934c4c; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
@media(max-width:767px) {
 #documents-view { padding:25px 18px 35px!important; gap:18px!important; }
 .upload-status { padding:16px; }.upload-steps { gap:7px; }.upload-steps li { font-size:11px; gap:5px; }
 .upload-step-dot { width:19px; height:19px; }.upload-steps li:not(:last-child)::after { margin-left:0; }
 .upload-status-top { gap:8px; }.upload-status-top strong { font-size:13px; }
}
@media(prefers-reduced-motion:reduce) { .upload-meter.indeterminate span { animation:none; width:24%; transform:translateX(150%); opacity:.5; }.upload-meter span { transition:none; } }
#document-actions { gap:10px!important; flex-wrap:nowrap!important; }
#document-actions button { border-radius:10px!important; height:42px!important; font-size:13px!important; box-shadow:none!important; }
#add-documents { background:#171717!important; border:1px solid #171717!important; color:#fff!important; flex:0 0 132px!important; }
#refresh-documents { background:#fff!important; border:1px solid #e5e5e5!important; color:#525252!important; flex:0 0 128px!important; }
#refresh-documents img { width:16px!important; height:16px!important; }
#document-actions button:disabled { opacity:.5; cursor:wait; }
.section-title { font-size:13px!important; color:#777!important; font-weight:500!important; margin:8px 0 0!important; }
#document-list { padding:0!important; }
#documents-view .form:has(#document-selection) { background:#fff!important; border:0!important; box-shadow:none!important; }
#document-selection { flex:none!important; min-height:auto!important; overflow:visible!important; border:0!important; background:#fff!important; padding:0!important; }
#document-selection [data-testid="checkbox-group"] { display:flex!important; flex-direction:column!important; gap:0!important; }
#document-selection label { display:flex; align-items:center; width:100%; box-sizing:border-box; margin:0!important; padding:17px 12px!important; border:0!important; border-bottom:1px solid #ededed!important; border-radius:0!important; background:transparent!important; color:#373737!important; box-shadow:none!important; }
#document-selection label:has(input:checked) { background:#f6f6f6!important; border-radius:8px!important; }
#document-selection label span { color:#373737!important; font-size:14px!important; overflow-wrap:anywhere; }
#delete-selected-documents { align-self:flex-start; flex:none!important; width:auto!important; padding:8px 16px!important; border-radius:9px!important; font-size:12px!important; color:#a35b5b!important; background:#fff!important; border:1px solid #e8dada!important; box-shadow:none!important; }
#delete-selected-documents:disabled { opacity:.4; }
.empty-documents { text-align:center; padding:42px 16px; border:1px solid #ededed; border-radius:16px; }
.empty-doc-icon { font-size:34px; color:#9a9a9a; margin-bottom:12px; }
.empty-documents h3 { font-size:15px!important; font-weight:500!important; margin:0 0 8px!important; }
.empty-documents p { color:#929292!important; font-size:12px!important; margin:0!important; }
.document-row { display:flex; align-items:center; gap:14px; padding:18px 2px; border-bottom:1px solid #ededed; }
.document-icon { display:flex; align-items:center; justify-content:center; width:40px; height:44px; border-radius:9px; background:#f6f6f6; color:#737373; flex-shrink:0; }
.document-icon svg { width:23px; height:23px; }
.document-row>div { min-width:0; }.document-row span { font-size:14px; overflow-wrap:anywhere; }
.document-row small { display:block; color:#9a9a9a; font-size:11px; margin-top:5px; }
#knowledge-footer { margin-top:8px; gap:12px!important; justify-content:space-between; }
#knowledge-footer button { flex:none!important; width:auto!important; padding:8px 0!important; border:0!important; background:transparent!important; box-shadow:none!important; font-size:12px!important; }
#back-to-chat { color:#666!important; }#clear-documents { color:#a35b5b!important; }
#clear-confirmation, #delete-confirmation { padding:18px!important; background:#faf7f7!important; border:1px solid #eddfdf!important; border-radius:12px; }
#clear-confirmation p, #delete-confirmation p, #delete-confirmation li { font-size:13px!important; color:#7c4444!important; }#clear-confirmation button, #delete-confirmation button { border-radius:8px!important; box-shadow:none!important; }
"""
