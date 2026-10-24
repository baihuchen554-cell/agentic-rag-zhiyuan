# Knowva 日常维护

以下 Linux 命令均在**香港服务器的 Ubuntu 终端**执行，也就是能看到 `root@…#` 的窗口。项目目录为 `/opt/knowva`。这些命令需要先上传本版本代码；本地修改不会自动更新服务器。

维护脚本只供有服务器终端权限的人使用，不会把管理员权限交给网页访客，也不会自动部署、停止或重启服务。不要把包含真实 `.env` 或用户数据库的备份上传 GitHub。

## 查看配置、账号和用量

检查模型、人机验证配置是否填写。结果只显示 `true/false`，不显示密钥；`true` 代表配置存在，**不代表已联网确认密钥有效**：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py check-config
```

Turnstile 的公开测试密钥不会被当作正式配置。正式启用前，在 Cloudflare 配置 `knowva.xin`，在 `project/.env` 填写自己的站点密钥和服务端密钥，然后重启服务。这里不接收、不生成任何第三方账户的真实密钥。

分页列出注册用户、显示姓名、角色和停用状态；不输出密码、恢复码或会话令牌：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py users --limit 50 --offset 0
```

下一页将 `--offset 0` 改为 `--offset 50`。最大每页 500 人。

查看用户 `alice` 今天的问答次数、文档处理字符量和上传字节量。请把 `alice` 换成网站上已经注册的用户名：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py usage alice
```

每日用量按北京时间零点重新计数，保存在账号数据库中。这是服务端的**准入记账**，不是模型服务商的 token 计费或人民币账单；已准入但随后失败、取消的操作也可能计数，不应据此向用户结算费用。取消操作后，正在进行的模型网络请求返回之前仍占用任务容量。

## 管理员和停用账号

先在网站正常注册自己的账号，再在服务器上将它设为管理员。以下例子假设用户名为 `owner`：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py grant-admin owner
```

这只改变已注册账号的角色，不创建默认密码，不创建公开的提权接口。维护脚本的授权来源是服务器终端本身；应保护 SSH 私钥和服务器登录权限。授权记录会写入管理员审计表。

停用指定账号，并立即撤销该账号已有的登录会话：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py disable-user alice
```

恢复账号使用权限，用户需要重新登录：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py enable-user alice
```

停用、启用也会留下审计记录。系统禁止停用最后一个仍可使用的管理员。停用账号不会删除他的知识库或聊天记录，也不保证已经发出的第三方模型请求立即停止。

## 当前默认资源限制

| 项目 | 默认值 |
| --- | --- |
| 每人每日问答 | 30 次 |
| 单次问题 / 最大模型输出 | 4,000 字符 / 2,048 tokens |
| 每批文件 / 单文件 | 3 个 / 10 MB |
| 每人每日上传 | 50 MB |
| 每人文档 / 工作目录预算 | 30 个 / 100 MB |
| PDF 页数 / 单文档正文 | 100 页 / 200,000 字符 |
| 单文档切块 / 每日文档向量处理量 | 600 块 / 500,000 字符 |
| 全站同时执行任务 / 文档导入 | 2 个 / 最多 1 个导入 |
| 单个用户同时执行任务 | 1 个 |
| 缓存用户工作空间 / 空闲回收 / 最长驻留 | 3 个 / 600 秒 / 3,600 秒 |
| 临时上传缓存预算 / 最低剩余磁盘 | 256 MB / 256 MB，另预留一批上传空间 |
| 单次问答内部执行线程 | 2 个，至少为 2 |

这些配置适配当前 2 核 2 GB 的小规模使用场景，需要实际观察峰值内存和响应时间后调整。工作空间仅在没有任务或回调使用时回收，磁盘数据保留。工作目录预算按已用文件大小和处理前的保守预估执行，写入期间再次检查，超额则回滚本次导入；它**不是操作系统磁盘硬配额**，例如 SQLite 删除内容后，数据库文件未必立即缩小。配额也不能替代服务商侧的消费上限。环境变量名称见 `project/.env.example`。

## 停止服务后备份

本工具提供**停机备份**，不承诺在线热备。它会拒绝处于 active、activating、deactivating 等状态的 `knowva` systemd 服务，也会检查本机应用端口和常见的手动启动进程。在备份完成前，请不要从其他终端重新启动程序或修改文件。

先停止服务。这段时间网站会暂时不可用：

```bash
systemctl stop knowva
```

确认服务已停止。看到 `inactive` 或已确认停止的 `failed` 才继续；`systemctl is-active` 在 inactive 时返回非零退出码，这是正常行为：

```bash
systemctl is-active knowva
```

创建备份。目标必须是**项目目录外、尚不存在的新目录**。请将例子中的 `20261024-2300` 换成本次备份的日期时间，每次使用新名字：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py backup /root/knowva-backups/20261024-2300
```

成功后会显示压缩包路径、整个压缩包的 SHA-256、文件数量和 SQLite 校验结果。目录权限为 `700`，压缩包权限为 `600`。工具不会覆盖已有目标，也不会自动重启服务。

**即使备份失败，也要查看原因并恢复网站服务**。确认备份命令已经结束后，执行下面命令重新启动网站：

```bash
systemctl start knowva
```

检查启动结果和最近日志，确认没有错误：

```bash
systemctl status knowva --no-pager -l
journalctl -u knowva -n 30 --no-pager
```

备份默认包含：

- `project/` 的代码和真实 `.env`，以及 `assets/`、依赖清单和根目录文档。
- `account_data/`：账号、密码哈希、头像、会话、角色、用量与管理员审计。
- `user_data/`：各用户的文档、向量索引、父文档和聊天记录。
- 迁移前保留的 `knowledge_base/`、`chat_history/`、`qdrant_db/`（若存在）。

备份不包括 `.venv`、Git 历史、测试目录、模型下载缓存、Python 缓存或临时上传目录，也不包括项目外的 Nginx、systemd、HTTPS 证书。恢复时需要重新准备 Python 3.11 和依赖，模型缓存可以重新下载。维护者应另外安全备份项目外的服务配置与证书；`DEPLOYMENT.md` 介绍已有服务的升级步骤，不包含从空服务器重建这些配置的完整流程。

SQLite 使用官方备份 API 合并已提交的 WAL 数据，并在备份过程中检查完整性。文件清单保存每个文件的哈希和大小，备份前后若发现源文件变化会放弃本次备份。**整个应用仍必须保持停止**，因为向量文件、正文文件和 SQLite 多个存储之间没有全局事务。不要只复制正在运行的 SQLite 主文件。

如果已经确认不再需要旧共享数据，可以加 `--no-legacy` 来省略那三个旧目录；它不会删除源数据。若修改过服务名称或应用端口，备份命令应传入实际的 `--service` 和 `--port`，默认分别为 `knowva`、`7860`。

## 验证备份和演练恢复

验证已有备份会检查路径、链接、文件数量、哈希和 SQLite 完整性。它不会覆盖或恢复运行中的项目：

```bash
/opt/knowva/.venv/bin/python /opt/knowva/project/manage.py verify-backup /root/knowva-backups/20261024-2300/knowva-backup.tar.gz
```

校验针对损坏和异常条目；**哈希清单不是数字签名**，不能证明压缩包来源可信。只恢复自己保存、来源明确的备份。备份包含 API 密钥和用户信息，下载到电脑后也应限制文件访问权限，并存放到加密磁盘或加密备份服务中。

建议定期把备份下载到服务器之外保存，并做一次隔离恢复演练。下面只解压到新建临时目录，不启动副本，不修改 `/opt/knowva`，也不更换网站数据。

先完成上面的 `verify-backup` 校验，再创建仅当前管理员可访问的新目录。下面的目录名每次演练都要更换，`mkdir` 若提示已存在，应停止并选择一个新名字：

```bash
mkdir -m 700 /root/knowva-restore-drill-20261024
```

将已经验证通过的压缩包解压到这个新目录。`--no-same-owner` 和 `--no-same-permissions` 避免采用压缩包记录的属主和权限：

```bash
tar --extract --gzip --file=/root/knowva-backups/20261024-2300/knowva-backup.tar.gz --directory=/root/knowva-restore-drill-20261024 --no-same-owner --no-same-permissions
```

检查恢复目录的代码、素材和个人数据目录。`find` 只列出目录名，不显示密钥或聊天内容：

```bash
find /root/knowva-restore-drill-20261024 -maxdepth 2 -type d
```

不要在演练目录直接启动 `project/app.py`，以免副本连接真实模型或与正式站点混淆。正式灾难恢复前，先停止正式服务并保留当前数据，核对备份日期、账号数量和文件清单，再由维护者决定目录切换。这里故意不提供覆盖现有数据或递归删除目录的命令。

## Windows 本地执行

在电脑的 **Windows PowerShell** 中，维护入口可以这样执行；它检查的是本地副本，不会修改香港服务器：

```powershell
& "D:\Desktop\knowva\.venv\Scripts\python.exe" "D:\Desktop\knowva\project\manage.py" check-config
```

本地备份前，先在启动应用的终端按 `Ctrl+C`。下面命令在项目外创建一个新备份目录，不包括虚拟环境，也不会上传服务器：

```powershell
& "D:\Desktop\knowva\.venv\Scripts\python.exe" "D:\Desktop\knowva\project\manage.py" backup "D:\Desktop\knowva-backups\20261024-2300"
```

Windows 备份目录及压缩包会移除继承权限，只授权当前 Windows 用户和 SYSTEM。遇到权限设置失败时工具会停止，不会继续写入包含密钥的数据。
