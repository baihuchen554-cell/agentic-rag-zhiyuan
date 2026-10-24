"""与主页面一致的账号设置弹窗；操作由账号接口鉴权。"""

SETTINGS_DIALOG = """<dialog id="settings-dialog" aria-labelledby="settings-title">
<header class="settings-heading"><div><h2 id="settings-title">账号设置</h2><p>让这个知识空间更像你。</p></div><button type="button" id="settings-close" aria-label="关闭账号设置">×</button></header>
<div class="settings-tabs" role="tablist" aria-label="设置分类"><button type="button" role="tab" data-settings-tab="profile" aria-selected="true">个人资料</button><button type="button" role="tab" data-settings-tab="security" aria-selected="false">账号安全</button><button type="button" role="tab" data-settings-tab="usage" aria-selected="false">使用额度</button></div>
<section id="settings-profile-panel" role="tabpanel" aria-label="个人资料">
<div class="settings-avatar-row"><span class="settings-avatar" id="settings-avatar"></span><div><strong>个人头像</strong><div class="settings-avatar-actions"><button type="button" id="settings-upload-avatar">更换头像</button><button type="button" id="settings-remove-avatar">移除</button></div><p>JPG、PNG 或 WebP，最大 2 MB</p></div></div>
<input id="settings-avatar-file" type="file" accept="image/jpeg,image/png,image/webp" hidden>
<form id="settings-profile-form"><label>姓名<input id="settings-name" autocomplete="nickname" maxlength="24" required placeholder="你希望我们如何称呼你？"></label><p class="settings-help">显示在侧栏和你的账号资料中，最多 24 个字符。</p><label>用户名<input id="settings-username" readonly autocomplete="username"></label><p class="settings-help">用于登录，注册后保持不变。</p><button type="submit" class="settings-primary" id="settings-save-profile">保存资料</button></form></section>
<section id="settings-security-panel" role="tabpanel" aria-label="账号安全" hidden>
<div class="settings-security-note"><strong>修改密码</strong><p>修改成功后，其他设备上的登录将失效。</p></div>
<form id="settings-password-form"><label>当前密码<span class="settings-password-wrap"><input id="settings-current-password" type="password" autocomplete="current-password" maxlength="128" required><button type="button" data-toggle-password="current-password" aria-label="显示当前密码">显示</button></span></label>
<label>新密码<span class="settings-password-wrap"><input id="settings-new-password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><button type="button" data-toggle-password="new-password" aria-label="显示新密码">显示</button></span></label><p class="settings-help">10–128 个字符，组合使用字母、数字或符号。</p>
<label>确认新密码<span class="settings-password-wrap"><input id="settings-confirm-password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><button type="button" data-toggle-password="confirm-password" aria-label="显示确认新密码">显示</button></span></label><button type="submit" class="settings-primary" id="settings-save-password">更新密码</button></form>
<p class="settings-recovery-note">账号不绑定手机或邮箱，请妥善保管注册时保存的恢复码。</p></section>
<section id="settings-usage-panel" role="tabpanel" aria-label="使用额度" hidden>
<div class="settings-usage-heading"><div><strong>我的使用额度</strong><p id="settings-usage-day">每日额度按北京时间零点重置</p></div><button type="button" id="settings-refresh-usage">刷新</button></div>
<p id="settings-usage-status" role="status" aria-live="polite"></p>
<div id="settings-usage-content" hidden>
<div class="settings-usage-row"><span>今日问答</span><strong id="settings-usage-questions"></strong><progress id="settings-meter-questions" aria-label="今日问答额度"></progress></div>
<div class="settings-usage-row"><span>今日上传</span><strong id="settings-usage-upload"></strong><progress id="settings-meter-upload" aria-label="今日上传额度"></progress></div>
<div class="settings-usage-row"><span>知识库文档</span><strong id="settings-usage-documents"></strong><progress id="settings-meter-documents" aria-label="知识库文档额度"></progress></div>
<div class="settings-usage-row"><span>工作目录占用</span><strong id="settings-usage-storage"></strong><progress id="settings-meter-storage" aria-label="存储预算"></progress></div>
<p id="settings-usage-file-help" class="settings-recovery-note"></p><p class="settings-recovery-note">问答、上传与向量处理按已接受的尝试计入额度；停止或重试不返还已使用额度。额度用于保护站点资源，不代表模型服务的实际计费。</p></div></section>
<p id="settings-status" role="status" aria-live="polite"></p>
<footer class="settings-footer"><span>你的资料与知识库独立保存</span><button type="button" id="settings-logout">退出登录</button></footer>
</dialog>"""

SETTINGS_CSS = """
#settings-dialog { position:fixed; box-sizing:border-box; margin:0; top:50%; left:50%; transform:translate(-50%,-50%); width:min(520px,calc(100vw - 32px)); max-height:calc(100dvh - 32px); padding:30px; overflow-y:auto; border:1px solid #e5e5e8; border-radius:20px; background:#fff; color:#24262a; box-shadow:0 20px 80px #0002; font-family:inherit; }
#settings-dialog::backdrop { background:#1115; backdrop-filter:blur(3px); }
#settings-dialog [hidden] { display:none!important; }
.settings-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.settings-heading h2 { font-size:23px; font-weight:600; letter-spacing:-.5px; margin:0 0 7px; }
.settings-heading p { color:#82858d; font-size:13px; margin:0; }
#settings-close { display:flex; align-items:center; justify-content:center; width:32px; height:32px; padding:0; border:0; border-radius:8px; background:#f5f5f6; color:#7d8087; font-size:23px; cursor:pointer; }
.settings-tabs { display:flex; gap:28px; margin:28px 0 26px; border-bottom:1px solid #ececef; }
.settings-tabs button { border:0; border-bottom:2px solid transparent; border-radius:0; padding:0 0 12px; background:none; color:#858890; font-family:inherit; font-size:14px; cursor:pointer; }
.settings-tabs [aria-selected=true] { border-color:#24262a; color:#24262a; font-weight:550; }
.settings-avatar-row { display:flex; align-items:center; gap:20px; margin:0 0 28px; }
.settings-avatar { display:flex; flex:none; align-items:center; justify-content:center; width:76px; height:76px; border-radius:50%; overflow:hidden; color:#626772; background:#ededf1; font-size:28px; font-weight:550; }
.settings-avatar img { display:block; width:100%; height:100%; object-fit:cover; }
.settings-avatar-row strong { font-size:14px; font-weight:550; }.settings-avatar-row p { font-size:11px; color:#93969d; margin:8px 0 0; line-height:1.6; }
.settings-avatar-actions { display:flex; gap:14px; margin-top:10px; }
.settings-avatar-actions button { border:0; background:none; padding:0; color:#4b5059; font:inherit; font-size:12px; cursor:pointer; }
#settings-remove-avatar { color:#94979e; }
#settings-dialog form>label { display:flex; flex-direction:column; gap:9px; font-size:13px; color:#454951; margin-bottom:16px; }
#settings-dialog input:not([type=file]) { box-sizing:border-box; width:100%; min-width:0; height:44px; padding:0 13px; border:1px solid #e4e5e9; border-radius:10px; color:#25272c; background:#f7f7f9; font-family:inherit; font-size:14px; outline:none; }
#settings-dialog input:focus-visible { border-color:#a0a4ac; box-shadow:0 0 0 3px #00000007; }
#settings-dialog input[readonly] { color:#92969f; background:#f4f4f6; }
.settings-help { margin:-8px 0 20px; color:#93979f; font-size:12px; line-height:1.6; }
.settings-primary { width:100%; height:44px; padding:0 16px; border:0; border-radius:10px; background:#242424; color:#fff; font-family:inherit; font-size:14px; cursor:pointer; margin-top:2px; }
#settings-dialog button:disabled { opacity:.4; cursor:default; }
.settings-password-wrap { position:relative; display:block; }.settings-password-wrap input { padding-right:60px!important; }
.settings-password-wrap button { position:absolute; right:12px; top:13px; background:none; border:0; padding:0; color:#777d86; font:inherit; font-size:12px; cursor:pointer; }
.settings-security-note strong { font-size:15px; font-weight:550; }.settings-security-note p { color:#848892; font-size:12px; margin:8px 0 22px; line-height:1.7; }
.settings-recovery-note { font-size:12px; color:#93979f; margin:20px 0 0; line-height:1.8; }
.settings-usage-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }.settings-usage-heading strong { font-size:15px; font-weight:550; }.settings-usage-heading p { font-size:12px; color:#93979f; margin:8px 0 22px; }
#settings-refresh-usage { border:1px solid #e5e5e9; border-radius:8px; background:white; color:#626874; padding:6px 11px; font:inherit; font-size:12px; cursor:pointer; }
#settings-usage-status { font-size:13px; color:#93979f; line-height:1.7; }#settings-usage-status:empty { display:none; }
.settings-usage-row { display:grid; grid-template-columns:1fr auto; gap:10px; margin:0 0 22px; font-size:13px; color:#626874; }.settings-usage-row strong { color:#34373f; font-size:12px; font-weight:500; }
.settings-usage-row progress { grid-column:1/-1; width:100%; height:5px; border:0; border-radius:6px; overflow:hidden; background:#eeeff2; accent-color:#535761; }.settings-usage-row progress::-webkit-progress-bar { background:#eeeff2; border-radius:6px; }.settings-usage-row progress::-webkit-progress-value { background:#535761; border-radius:6px; }
#settings-status { margin:16px 0 0; color:#38634a; font-size:13px; line-height:1.7; overflow-wrap:anywhere; }#settings-status:empty { display:none; }#settings-status[data-state=error] { color:#b23e3e; }
.settings-footer { display:flex; justify-content:space-between; align-items:center; gap:12px; border-top:1px solid #ececef; padding-top:20px; margin-top:26px; }
.settings-footer span { font-size:11px; color:#a0a3aa; }.settings-footer button { background:none; border:0; padding:0; color:#8b5c5c; font:inherit; font-size:13px; cursor:pointer; }
@media(max-width:480px) { #settings-dialog { padding:24px 20px; border-radius:16px; }.settings-avatar-row { gap:16px; }.settings-avatar { width:68px; height:68px; } }
"""

SETTINGS_JS = r"""(() => {
const init=()=>{
 const dialog=document.getElementById('settings-dialog');if(!dialog||dialog.dataset.ready)return !!dialog;dialog.dataset.ready='1';
 const $=id=>document.getElementById('settings-'+id);let user=null,busy=false;
 const status=(message,state='success')=>{$('status').textContent=message;$('status').dataset.state=state;};
 const update=value=>{
  user=value;$('avatar').replaceChildren();if(user.avatar_url){const image=document.createElement('img');image.src=user.avatar_url;image.alt='当前头像';$('avatar').appendChild(image);}else $('avatar').textContent=Array.from(user.display_name)[0]?.toUpperCase()||'K';
  $('name').value=user.display_name;$('username').value=user.username;$('remove-avatar').disabled=!user.avatar_url;
  document.dispatchEvent(new CustomEvent('knowva:user-updated',{detail:user}));
 };
 const request=async(path,body,raw=false)=>{
  const response=await fetch('/account/'+path,{method:'POST',credentials:'same-origin',headers:{'X-Knowva-Request':'1','Content-Type':raw?'application/octet-stream':'application/json'},body:raw?body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'提交失败，请稍后重试。');return result;
 };
 const loadUsage=async()=>{
  $('refresh-usage').disabled=true;$('usage-status').textContent='正在读取使用额度…';$('usage-content').hidden=true;
  try{
   const response=await fetch('/account/usage',{credentials:'same-origin',cache:'no-store'}),data=await response.json();
   if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'暂时无法读取额度，请稍后重试。');
   const usage=data.usage||data,limits=usage.limits;
   const mb=n=>n>0&&n<1024*1024?(n<1024?n+' B':(n/1024).toFixed(1)+' KB'):(n/1024/1024).toFixed(1)+' MB';
   const row=(id,value,max,text)=>{$('usage-'+id).textContent=text;$('meter-'+id).max=max;$('meter-'+id).value=Math.min(value,max);};
   row('questions',usage.questions,limits.questions,`${usage.questions} / ${limits.questions} 次`);
   row('upload',usage.upload_bytes,limits.upload_bytes,`${mb(usage.upload_bytes)} / ${mb(limits.upload_bytes)}`);
   row('documents',usage.documents,limits.documents,`${usage.documents} / ${limits.documents} 个`);
   row('storage',usage.storage_bytes,limits.storage_bytes,`${mb(usage.storage_bytes)} / ${mb(limits.storage_bytes)}`);
   $('usage-day').textContent=usage.day+' · 每日额度按北京时间零点重置';
   $('usage-file-help').textContent=`单个文件最多 ${mb(limits.file_bytes)}，PDF 最多 ${limits.pdf_pages} 页。单次问题最多 ${limits.question_chars} 个字符。`;
   $('usage-status').textContent='';$('usage-content').hidden=false;
  }catch(e){$('usage-status').textContent=e.message;}finally{$('refresh-usage').disabled=false;}
 };
 const setTab=tab=>{
  status('');$('profile-panel').hidden=tab!=='profile';$('security-panel').hidden=tab!=='security';$('usage-panel').hidden=tab!=='usage';
  dialog.querySelectorAll('[data-settings-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.settingsTab===tab)));
  if(tab==='usage')loadUsage();
 };
 const run=async(button,label,action)=>{
  if(busy)return;busy=true;const text=button.textContent;status('');button.textContent=label;
  dialog.querySelectorAll('button,input').forEach(element=>element.disabled=true);
  try{await action();}catch(e){status(e.message,'error');}finally{busy=false;button.textContent=text;dialog.querySelectorAll('button,input').forEach(element=>element.disabled=false);$('remove-avatar').disabled=!user?.avatar_url;}
 };
 window.knowvaOpenSettings=value=>{
  if(!value)return;update(value);setTab('profile');$('password-form').reset();dialog.querySelectorAll('[data-toggle-password]').forEach(button=>{ $(button.dataset.togglePassword).type='password';button.textContent='显示'; });
  if(!dialog.open)dialog.showModal();
 };
 $('close').addEventListener('click',()=>{if(!busy)dialog.close();});dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 dialog.addEventListener('click',e=>{if(e.target===dialog&&!busy){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
 dialog.querySelectorAll('[data-settings-tab]').forEach(button=>button.addEventListener('click',()=>{if(!busy)setTab(button.dataset.settingsTab);}));
 $('refresh-usage').addEventListener('click',loadUsage);
 dialog.querySelectorAll('[data-toggle-password]').forEach(button=>button.addEventListener('click',()=>{const input=$(button.dataset.togglePassword);const show=input.type==='password';input.type=show?'text':'password';button.textContent=show?'隐藏':'显示';button.setAttribute('aria-label',show?'隐藏密码':'显示密码');}));
 $('profile-form').addEventListener('submit',e=>{
  e.preventDefault();const name=$('name').value.trim();if(!name){status('请填写姓名。','error');return;}
  run($('save-profile'),'正在保存…',async()=>{const result=await request('profile',{display_name:name});update(result.user);status('个人资料已保存。');});
 });
 $('upload-avatar').addEventListener('click',()=>$('avatar-file').click());
 $('avatar-file').addEventListener('change',()=>{
  const file=$('avatar-file').files[0];$('avatar-file').value='';if(!file)return;
  if(file.size>2*1024*1024){status('请选择不超过 2 MB 的图片。','error');return;}
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)){status('头像支持 JPG、PNG 或 WebP 图片。','error');return;}
  const draft=$('name').value;
  run($('upload-avatar'),'正在上传…',async()=>{const result=await request('avatar',file,true);update(result.user);$('name').value=draft;status('头像已更新。');});
 });
 $('remove-avatar').addEventListener('click',()=>{const draft=$('name').value;run($('remove-avatar'),'移除中…',async()=>{const result=await request('avatar/remove',{});update(result.user);$('name').value=draft;status('已恢复默认头像。');});});
 $('password-form').addEventListener('submit',e=>{
  e.preventDefault();const password=$('new-password').value;
  if(password!==$('confirm-password').value){status('两次输入的新密码不一致。','error');return;}
  const body={current_password:$('current-password').value,new_password:password,confirm_password:$('confirm-password').value};
  run($('save-password'),'正在更新…',async()=>{const result=await request('password',body);update(result.user);$('password-form').reset();status('密码已更新，其他设备已退出登录。');});
 });
 $('logout').addEventListener('click',()=>run($('logout'),'正在退出…',async()=>{await request('logout',{});location.reload();}));
 return true;
};
if(!init()){const observer=new MutationObserver(()=>{if(init())observer.disconnect();});observer.observe(document.body,{childList:true,subtree:true});}
})();"""
