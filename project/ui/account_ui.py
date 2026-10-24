"""沿用主页面设计的账号弹窗；实际验证由服务端完成。"""
from pathlib import Path
from urllib.parse import quote
import config

ACCOUNT_DIALOG = """<dialog id="account-dialog" aria-labelledby="account-title">
<button type="button" class="account-close" aria-label="关闭登录窗口">×</button>
<div class="account-brand">knowva<span>让答案有据可循</span></div>
<div id="account-form-view">
<div class="account-tabs" role="tablist" aria-label="账号操作">
<button type="button" role="tab" data-mode="login" aria-selected="true">登录</button>
<button type="button" role="tab" data-mode="register" aria-selected="false">注册</button></div>
<h2 id="account-title">欢迎回来</h2><p id="account-intro">登录，继续你的知识探索。</p>
<form id="account-form">
<div class="account-names"><label>用户名<input id="account-username" name="username" autocomplete="username" required minlength="3" maxlength="24" placeholder="你的用户名"></label>
<label data-show="register" hidden>姓名<input id="account-display-name" name="display_name" autocomplete="nickname" maxlength="24" placeholder="怎么称呼你？"></label></div>
<label data-show="recover" hidden>账号恢复码<input id="account-recovery" name="recovery_code" autocomplete="off" maxlength="128" placeholder="注册时保存的恢复码"></label>
<label><span id="account-password-label">密码</span><span class="account-password-wrap"><input id="account-password" name="password" type="password" autocomplete="current-password" required maxlength="128" placeholder="输入密码"><button type="button" id="account-show-password" aria-label="显示密码">显示</button></span></label>
<p class="account-field-help" data-show="register recover" hidden>10–128 个字符，组合使用字母、数字或符号。</p>
<label data-show="register recover" hidden>确认密码<input id="account-confirm" name="confirm_password" type="password" autocomplete="new-password" maxlength="128" placeholder="再次输入密码"></label>
<div class="account-verification"><div class="account-verification-heading"><span>人机验证</span><button type="button" id="account-refresh">重新验证</button></div><div id="account-turnstile"></div><p id="account-verification-status" role="status" aria-live="polite">正在加载安全验证…</p></div>
<div class="account-options" data-show="login register"><label><input id="account-remember" type="checkbox">保持登录 30 天</label><button type="button" data-account-mode="recover" data-show="login">忘记密码？</button></div>
<label class="account-agreement" data-show="register" hidden><input id="account-accepted" type="checkbox"><span>我已了解：知识库和聊天记录仅对当前账号开放；文档问答会调用第三方 AI 服务。<button type="button" id="account-show-privacy">查看说明</button></span></label>
<p id="account-privacy" hidden>请只上传你有权处理的文档。必要的文档文本、检索内容和问题会发送至百炼或 DeepSeek，模型回答可能出错。账号安全验证由 Cloudflare Turnstile 提供，会处理必要的浏览器和网络信息。账号无需手机或邮箱，请妥善保管密码与恢复码。请勿上传密钥或敏感凭证。</p>
<p id="account-error" role="alert" aria-live="polite"></p>
<button type="submit" id="account-submit">登录</button>
</form>
<button type="button" class="account-back" data-account-mode="login" data-show="recover" hidden>返回登录</button>
<p class="account-footnote">不绑定手机号或邮箱。每个账号都有独立的知识空间。</p></div>
<section id="account-success" hidden><h2>保存你的账号恢复码</h2><p>忘记密码时可凭它重设密码。请保存到安全的位置，勿向他人透露。</p><code id="account-new-recovery"></code><button type="button" id="account-download-recovery">下载恢复码</button><label class="account-agreement"><input type="checkbox" id="account-recovery-saved">我已经妥善保存恢复码</label><button type="button" id="account-continue" disabled>进入我的知识空间</button></section>
</dialog>"""

_logo = "./gradio_api/file=" + quote(Path(config.APP_LOGO_PATH).resolve().as_posix(), safe="/:")
ACCOUNT_DIALOG = ACCOUNT_DIALOG.replace('<div class="account-brand">knowva',
    f'<div class="account-brand"><img src="{_logo}" alt="" width="26" height="32">knowva')

ACCOUNT_CSS = """
#account-surface { position:absolute!important; top:0; left:0; width:0!important; height:0!important; min-height:0!important; padding:0!important; border:0!important; }
#account-dialog { position:fixed; box-sizing:border-box; margin:0; top:50%; left:50%; right:auto; bottom:auto; transform:translate(-50%,-50%); width:min(460px,calc(100vw - 32px)); max-height:calc(100dvh - 32px); padding:32px; border:1px solid #e5e5e8; border-radius:20px; color:#202124; background:#fff; box-shadow:0 20px 80px #0002; font-family:inherit; overflow-y:auto; }
#account-dialog::backdrop { background:#1115; backdrop-filter:blur(3px); }
#account-dialog [hidden], #account-profile [hidden] { display:none!important; }
.account-close { position:absolute; top:14px; right:16px; width:30px; height:30px; border:0; border-radius:50%; background:transparent; font-size:25px; color:#737780; cursor:pointer; }
.account-close:hover { background:#f1f2f4; }
.account-brand { display:flex; align-items:baseline; gap:12px; margin-bottom:24px; font-size:24px; font-weight:650; letter-spacing:-.7px; }
.account-brand span { color:#90939a; font-size:12px; font-weight:400; letter-spacing:0; }
.account-brand img { align-self:center; object-fit:contain; }
.account-tabs { display:flex; gap:24px; border-bottom:1px solid #ececef; margin-bottom:24px; }
.account-tabs button { border:0; border-bottom:2px solid transparent; border-radius:0; background:none; padding:0 0 10px; color:#8c8e94; cursor:pointer; font-size:14px; }
.account-tabs [aria-selected=true] { color:#202124; border-color:#202124; }
#account-dialog h2 { margin:0 0 8px; font-size:23px; letter-spacing:-.5px; font-weight:600; }
#account-intro, #account-success p { font-size:13px; color:#858992; line-height:1.7; margin:0 0 22px; }
#account-form>label,.account-names>label { display:flex; flex-direction:column; gap:8px; margin:0 0 12px; font-size:13px; color:#44474e; }
#account-form[data-mode=register] .account-names { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; }
#account-dialog input:not([type=checkbox]) { box-sizing:border-box; width:100%; height:44px; padding:0 13px; border:1px solid #e4e5e9; border-radius:10px; color:#222; background:#f7f7f9; font-family:inherit; font-size:14px; outline:none; }
#account-dialog input:focus-visible { border-color:#a0a4ac; box-shadow:0 0 0 3px #00000007; }
#account-dialog input::placeholder { color:#a0a3aa; }
#account-dialog #account-form>label { margin-bottom:12px; }
#account-dialog input[type=checkbox] { width:15px; height:15px; accent-color:#252525; flex:none; }
.account-password-wrap { position:relative; display:block; }
.account-password-wrap input { padding-right:55px!important; }
#account-show-password { position:absolute; right:10px; top:12px; padding:0; border:0; background:none; font-size:12px; color:#777; cursor:pointer; }
.account-field-help { margin:-8px 0 16px; font-size:11px; line-height:1.6; color:#969aa2; }
.account-verification { margin:16px 0; }
.account-verification-heading { display:flex; justify-content:space-between; align-items:center; font-size:13px; color:#44474e; margin-bottom:10px; }
#account-refresh { border:0; background:none; padding:4px 0; font:inherit; font-size:12px; color:#737780; cursor:pointer; }
#account-turnstile { min-height:0; }
#account-verification-status { font-size:12px; color:#777b83; line-height:1.6; margin:8px 0 0; }
#account-verification-status[data-state=error] { color:#ad4141; }
#account-verification-status[data-state=success] { color:#38634a; }
.account-options { display:flex; align-items:center; justify-content:space-between; margin:0 0 16px; font-size:12px; color:#737780; }
.account-options label,.account-agreement { display:flex!important; flex-direction:row!important; align-items:flex-start; gap:8px!important; line-height:1.7; font-size:12px!important; color:#80848c!important; }
.account-options button,#account-show-privacy,.account-back { border:0; padding:0; font:inherit; background:none; color:#555b66; cursor:pointer; text-decoration:underline; text-underline-offset:3px; }
.account-agreement input { margin-top:3px; }
#account-privacy { background:#f7f7f9; border-radius:10px; padding:12px; font-size:12px; line-height:1.8; color:#6c727c; }
#account-error { color:#b23e3e; font-size:12px; line-height:1.6; margin:4px 0 12px; min-height:0; }
#account-error:empty { display:none; }
#account-submit,#account-continue,#account-download-recovery { width:100%; height:44px; border:0; border-radius:10px; background:#242424; color:white; font-family:inherit; font-size:14px; cursor:pointer; }
#account-submit:disabled,#account-continue:disabled { opacity:.4; cursor:default; }
.account-footnote { text-align:center; font-size:11px; color:#a0a3aa; margin:18px 0 0; line-height:1.7; }
.account-back { display:block; margin:16px auto 0; font-size:12px; }
#account-new-recovery { display:block; word-break:break-all; background:#f1f2f4; padding:16px; border-radius:10px; font-size:14px; margin:20px 0; }
#account-download-recovery { background:#f1f2f4; color:#30343b; margin-bottom:16px; }
#account-success .account-agreement { margin:16px 0; }
@media(max-width:480px) { #account-dialog { padding:24px 20px; border-radius:16px; } .account-brand { margin-top:4px; } }
"""

ACCOUNT_JS = r"""(() => {
const init = () => {
 const dialog=document.querySelector('#account-dialog');
 if(!dialog || dialog.dataset.ready) return !!dialog;
 dialog.dataset.ready='1';
 const $=id=>document.getElementById('account-'+id);
 let user=null, mode='login', challenge='', recovery='', busy=false, meLoaded=false, widget=null, verificationToken='', generation=0, scriptPromise=null, challengeQueue=Promise.resolve();
 const notices={login:['欢迎回来','登录，继续你的知识探索。','登录'],register:['创建你的知识空间','从空白开始，积累只属于你的知识。','创建账号'],recover:['找回你的账号','使用注册时保存的恢复码设置新密码。','重设密码']};
 const error=message=>{$('error').textContent=message;};
 const request=async(url,body)=>{
  const response=await fetch('/account/'+url,{credentials:'same-origin',cache:'no-store',method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Knowva-Request':'1'}:{},body:body?JSON.stringify(body):undefined});
  const result=await response.json();
  if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'提交内容有误，请检查后重试。');
  return result;
 };
 const verificationStatus=(message,state='')=>{$('verification-status').textContent=message;$('verification-status').dataset.state=state;};
 const loadTurnstile=()=>{
  if(scriptPromise)return scriptPromise;
  if(window.turnstile)return Promise.resolve(window.turnstile);
  scriptPromise=new Promise((resolve,reject)=>{
   const script=document.createElement('script');script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=knowvaTurnstileReady';script.async=true;
   const timer=setTimeout(()=>{script.remove();scriptPromise=null;reject(new Error('安全验证加载超时，请检查网络后重新验证。'));},20000);
   window.knowvaTurnstileReady=()=>{clearTimeout(timer);resolve(window.turnstile);};
   script.onerror=()=>{clearTimeout(timer);script.remove();scriptPromise=null;reject(new Error('无法连接安全验证服务，请检查网络后重试。'));};
   document.head.appendChild(script);
  });return scriptPromise;
 };
 const clearVerification=()=>{verificationToken='';challenge='';if(widget!==null&&window.turnstile){window.turnstile.remove(widget);widget=null;}$('turnstile').replaceChildren();};
 const refresh=async()=>{
  const run=++generation, action=mode;clearVerification();verificationStatus('正在加载安全验证…');$('refresh').disabled=true;
  try {
   const task=challengeQueue.then(()=>run===generation?request('challenge?action='+action):null);challengeQueue=task.catch(()=>{});
   const c=await task;if(!c||run!==generation)return;challenge=c.id;
   const api=await loadTurnstile();if(run!==generation||!dialog.open)return;
   verificationStatus('请完成下方的安全验证。');
   widget=api.render($('turnstile'),{sitekey:c.site_key,action:action,cData:c.id,theme:'light',size:window.innerWidth<360?'compact':'flexible',language:'zh-cn',
    callback:token=>{if(run===generation){verificationToken=token;verificationStatus('安全验证已通过','success');}},
    'expired-callback':()=>{if(run===generation){verificationToken='';verificationStatus('验证已过期，请重新验证。','error');}},
    'timeout-callback':()=>{if(run===generation){verificationToken='';verificationStatus('验证超时，请重新验证。','error');}},
    'error-callback':()=>{if(run===generation){verificationToken='';verificationStatus('安全验证未完成，请检查网络后重新验证。','error');}return true;}});
  }catch(e){if(run===generation)verificationStatus(e.message,'error');}finally{if(run===generation)$('refresh').disabled=false;}
 };
 const setMode=value=>{
  mode=value;error('');$('password').value='';$('confirm').value='';$('password').type='password';$('show-password').textContent='显示';
  $('form').dataset.mode=mode;
  $('form-view').hidden=false;$('success').hidden=true;
  const [title,intro,submit]=notices[mode];$('title').textContent=title;$('intro').textContent=intro;$('submit').textContent=submit;
  dialog.querySelectorAll('[data-show]').forEach(e=>{e.hidden=!e.dataset.show.split(' ').includes(mode);});
  dialog.querySelectorAll('[data-mode]').forEach(e=>e.setAttribute('aria-selected',String(e.dataset.mode===mode)));
  $('password-label').textContent=mode==='recover'?'新密码':'密码';
  $('password').autocomplete=mode==='login'?'current-password':'new-password';
  $('display-name').required=mode==='register';$('confirm').required=mode!=='login';$('recovery').required=mode==='recover';$('accepted').required=mode==='register';
  $('password').minLength=mode==='login'?1:10;
  refresh();
 };
 const open=value=>{setMode(value||'login');if(!dialog.open)dialog.showModal();setTimeout(()=>$('username').focus(),50);};
 const updateUser=value=>{
  user=value;document.documentElement.dataset.account=user?'member':'guest';
  if(!user)return;
  $('name').textContent=user.display_name;$('entry').dataset.accountAction='profile';$('entry').setAttribute('aria-label','打开账号设置');$('caption').textContent='个人知识空间';
  $('avatar').replaceChildren();if(user.avatar_url){const image=document.createElement('img');image.src=user.avatar_url;image.alt='';$('avatar').appendChild(image);}else $('avatar').textContent=Array.from(user.display_name)[0]?.toUpperCase()||'K';
 };
 document.addEventListener('knowva:user-updated',e=>updateUser(e.detail));
 request('me').then(result=>{
  meLoaded=true;updateUser(result.user);
 }).catch(()=>{meLoaded=true;document.documentElement.dataset.account='guest';});
 const checkAccount=()=>{
  if(!meLoaded || document.hidden || busy || (dialog.open && !$('success').hidden))return;
  request('me').then(result=>{if((result.user?.id||null)!==(user?.id||null))location.reload();}).catch(()=>{});
 };
 window.addEventListener('focus',checkAccount);
 document.addEventListener('visibilitychange',checkAccount);
 document.addEventListener('click',e=>{
  const action=e.target.closest('[data-account-action]')?.dataset.accountAction;
  if(action==='login'){e.preventDefault();e.stopImmediatePropagation();open('login');return;}
  if(action==='logout'){e.preventDefault();request('logout',{}).then(()=>location.reload()).catch(x=>{open('login');error(x.message)});return;}
  if(action==='profile'){e.preventDefault();window.knowvaOpenSettings?.(user);return;}
  const need=e.target.closest('#knowledge-nav,#composer-attach,#new-chat,#conversation-history,#delete-conversation,#composer-input .submit-button,#document-upload,#add-documents,#clear-documents');
  if(need && !user){e.preventDefault();e.stopImmediatePropagation();open('login');}
 },true);
 const close=()=>{if(busy)return;if(!$('success').hidden){if($('recovery-saved').checked)location.reload();else $('recovery-saved').focus();}else dialog.close();};
 dialog.querySelector('.account-close').addEventListener('click',close);
 dialog.addEventListener('cancel',e=>{if(busy||!$('success').hidden){e.preventDefault();close();}});
 dialog.addEventListener('close',()=>{generation++;clearVerification();});
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}});
 dialog.querySelectorAll('[data-mode]').forEach(e=>e.addEventListener('click',()=>{if(!busy)setMode(e.dataset.mode)}));
 dialog.querySelectorAll('[data-account-mode]').forEach(e=>e.addEventListener('click',()=>{if(!busy)setMode(e.dataset.accountMode)}));
 $('refresh').addEventListener('click',refresh);
 $('show-password').addEventListener('click',()=>{const show=$('password').type==='password';$('password').type=show?'text':'password';$('show-password').textContent=show?'隐藏':'显示';$('show-password').setAttribute('aria-label',show?'隐藏密码':'显示密码');});
 $('show-privacy').addEventListener('click',()=>{$('privacy').hidden=!$('privacy').hidden;});
 $('recovery-saved').addEventListener('change',()=>{$('continue').disabled=!$('recovery-saved').checked;});
 $('continue').addEventListener('click',()=>location.reload());
 $('download-recovery').addEventListener('click',()=>{
  const text=`knowva 账号恢复码\n用户名：${$('username').value.trim()}\n恢复码：${recovery}\n请勿向任何人透露。使用后会更换为新的恢复码。`;
  const link=document.createElement('a');const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));link.href=url;link.download='knowva-recovery.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 });
 $('form').addEventListener('submit',async e=>{
  e.preventDefault();if(busy)return;error('');
  if(!challenge||!verificationToken){error('请先完成人机验证。');return;}
  if(mode!=='login' && $('password').value!==$('confirm').value){error('两次输入的密码不一致。');return;}
  busy=true;$('submit').disabled=true;$('submit').textContent='正在处理…';
  try{
   const result=await request(mode,{username:$('username').value,password:$('password').value,display_name:$('display-name').value,confirm_password:$('confirm').value,recovery_code:$('recovery').value,challenge_id:challenge,verification_token:verificationToken,accepted:$('accepted').checked,remember:$('remember').checked});
   if(result.recovery_code){recovery=result.recovery_code;$('new-recovery').textContent=recovery;$('form-view').hidden=true;$('success').hidden=false;$('recovery-saved').checked=false;$('continue').disabled=true;if(mode==='recover'){$('continue').textContent='返回首页并重新登录';}}
   else location.reload();
  }catch(x){error(x.message);await refresh();}
  finally{busy=false;$('submit').disabled=false;$('submit').textContent=notices[mode][2];}
 });
 return true;
};
if(!init()){const observer=new MutationObserver(()=>{if(init())observer.disconnect()});observer.observe(document.body,{childList:true,subtree:true});}
})();"""
