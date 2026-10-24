# knowva 账号版部署

更新 GitHub 仓库不会自动部署到现有服务器；以下升级步骤需在服务器单独执行。

## 升级已有香港服务

1. 在维护窗口停止 `knowva.service`，备份现有项目配置、知识库和聊天记录。之后的更新还需备份新增的 `account_data/` 和 `user_data/`，建议保留可恢复的服务器快照。
2. 上传本次的 `project/` 源代码、`requirements.txt`、`assets/logo.svg` 和使用到的 `assets/icons/`。保留服务器 `project/.env`；不要用本地文件覆盖它。不要上传本地虚拟环境、数据库、缓存或测试账号。
3. 使用服务器虚拟环境的 Python 安装新版依赖。原环境如果未安装 pip，先执行 `/opt/knowva/.venv/bin/python -m ensurepip`，再执行 `/opt/knowva/.venv/bin/python -m pip install -r /opt/knowva/requirements.txt`。依赖版本已在本地验证，不需要升级系统 Python。
4. 按下方步骤配置 Cloudflare Turnstile。未配置正式密钥时，首页仍能浏览，登录、注册和找回密码会明确提示服务未配置，不会退回简单图片验证码。
5. 仍用 `/opt/knowva/.venv/bin/python -u /opt/knowva/project/app.py` 启动；现有 systemd、Nginx 和 HTTPS 端口配置可继续使用。服务保持单进程；不要启用多个 Uvicorn workers。
6. 重启 `knowva.service`，检查服务日志。在浏览器隐私窗口确认首页可以直接打开，使用功能会提示登录，注册后知识库为空，第二个账号看不到第一个账号的数据。验证设置中的姓名、头像和密码修改。

## 配置正式人机验证

1. 在 [Cloudflare Turnstile 控制台](https://dash.cloudflare.com/?to=/:account/turnstile) 创建小组件，选择 **Managed（托管）**，域名填写 `knowva.xin`。不需要迁移现有阿里云域名解析或网站服务器。
2. 打开香港服务器 `/opt/knowva/project/.env`，添加 `TURNSTILE_SITE_KEY`（Site Key）和 `TURNSTILE_SECRET_KEY`（Secret Key），以及 `TURNSTILE_HOSTNAMES=knowva.xin`。密钥只在服务器填写，不要发到聊天或提交 Git。多个允许域名用英文逗号隔开，控制台也要添加相同域名。
3. 重启服务后，用真实浏览器在 `https://knowva.xin` 检查登录、注册与找回密码。浏览器需能访问 `https://challenges.cloudflare.com`，服务器需能向该域名发送 HTTPS 验证请求。本站不会代理或缓存 Turnstile 脚本。
4. 正式服务拒绝官方“总是通过”的测试密钥。自动化测试使用单独临时应用和测试替身，不能用其结果替代正式域名的真实验证。

服务端核验成功标记、域名、操作（登录/注册/找回密码）与当前浏览器的一次性请求绑定；令牌还由 Cloudflare 检查有效期和重复使用。配置缺失、网络失败或任何字段不匹配都会拒绝本次账号操作。实现依据：[服务端验证](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)、[小组件配置](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/)。

## 新版账号行为

- 旧版 `WEB_AUTH_REQUIRED`、`WEB_AUTH_USERNAME`、`WEB_AUTH_PASSWORD` 不再作为站点门禁，也不会自动变成用户账号。上线后用户通过注册创建账号。
- 注册不要求手机号或邮箱；注册、登录与找回密码使用 Cloudflare Turnstile 和服务端验证，接口保留 IP 和用户名频率限制。
- 密码以带盐 scrypt 哈希存储，登录会话可撤销。HTTPS 请求使用 Secure、HttpOnly、SameSite Cookie。
- 注册时展示账号恢复码。用户忘记密码后可以用它重设密码，旧恢复码与全部旧会话随后失效。必须提醒用户妥善保存。
- 账号数据库为 `account_data/accounts.sqlite3`。个人知识库、向量库、父文档和聊天记录位于 `user_data/<内部用户ID>/`；新账号从空白开始。
- 点击侧栏底部的账号打开设置，可修改姓名、更换或移除头像、验证旧密码后修改密码。头像限制 2 MB/800 万像素，服务端重新编码为 256×256 WebP，存储在账号数据库中。密码更新后撤销全部旧会话，并为当前浏览器换发一天有效的新会话。
- 旧账号数据库首次启动时补充头像、角色、停用状态、用量与审计数据表，用户 ID 和个人数据目录保持不变；仍应先备份再升级。
- 旧版 `knowledge_base/` 和 `chat_history/` 保留在原位置，不会自动导入新账号，也不对游客公开。若需要导入旧资料，应由指定账号在界面重新上传；不要把旧共享数据库发给所有用户。

## 运维边界

代码升级不能覆盖 `.env`、`account_data/` 或 `user_data/`。账号和用户数据已加入 `.gitignore`，不要通过 Git 或公开下载链接分发。备份目录应限制权限，用户目录不能配置为静态网站目录。

Turnstile 属于第三方反自动化服务，不能保证阻止所有攻击，也不替代接口限流和模型用量管理。当前提供按用户的服务端资源额度、管理员 CLI/API、健康检查及备份校验，仍未实现付费系统、完整的可视化管理后台或多进程部署。资源限制配置见 `project/.env.example`；生产运维步骤见 [OPERATIONS.md](OPERATIONS.md)。

回滚到旧版本会恢复旧版共享数据访问方式；操作前关闭公网入口，恢复匹配的源代码和依赖，并检查旧版站点登录配置，不要把新版注册账号误当作旧版站点凭证。
