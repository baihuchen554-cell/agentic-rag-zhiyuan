# knowva 业务 API

这些接口与现有 Gradio 页面共用账号 Cookie、个人工作空间、每日额度和任务容量。前端仍是 Gradio，此次没有重写成独立前端项目，也无需增加第二台服务器。

除健康检查外均需有效的站点账号 Cookie。所有修改请求需同源，并发送 `X-Knowva-Request: 1`；JSON 请求设置 `Content-Type: application/json`。不要把 Cookie、密码或恢复码写入代码仓库。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/account/usage` 或 `/api/usage` | 当前账号的用量、文档数、工作目录占用及限制，不初始化模型 |
| GET | `/api/conversations?limit=50&offset=0` | 当前账号会话列表 |
| GET | `/api/conversations/{id}` | 当前账号指定会话的消息；不暴露模型内部检查点 |
| DELETE | `/api/conversations/{id}` | 删除当前账号会话与记忆 |
| GET | `/api/documents` | 文档来源列表，不初始化模型 |
| POST | `/api/documents` | multipart 上传，文件字段名 `files`；服务端暂存并入库，拒绝客户端路径 |
| DELETE | `/api/documents` | JSON `{"sources":["notes.md"]}` 删除指定文档及索引 |
| POST | `/api/chat` | JSON `{"message":"你好","conversation_id":null}`；返回 SSE 事件流 |
| POST | `/api/chat/{id}/stop` | 停止当前账号的指定回答；旧网络请求仍保留任务名额直到退出 |
| GET | `/api/admin/users?limit=25&offset=0` | 管理员查看账号和当日用量，不包含密码哈希、恢复码或会话令牌 |
| PATCH | `/api/admin/users/{id}` | 管理员提交 `{"disabled":true}` 停用账号，或 `false` 启用；保留数据 |
| GET | `/api/admin/runtime` | 管理员查看配置是否完整、任务/缓存数量和磁盘空间，不返回密钥 |
| GET | `/health/live` | 进程存活，返回最小状态 |
| GET | `/health/ready` | 模型配置、人机验证配置和账号数据库基础检查；不调用收费模型，不保证外部 API 当前可达 |

账号注册、登录、找回、资料和头像等原有接口仍位于 `/account/`。管理员角色只能通过可信的服务器终端授予，参考 [OPERATIONS.md](OPERATIONS.md)。

## 聊天事件与错误

新会话使用 `conversation_id:null`，从 `started` 事件获取服务端生成的 ID。继续聊天时传入该 ID。`update` 事件提供当前消息快照，完成时返回 `done`，中途故障返回 `error`；这些事件的 `data` 均为 JSON。断开浏览器连接会停止生成并释放页面使用权；仍在等待网络返回的底层任务会继续保留容量和资源保护。

输入不合法返回 400/422，未登录返回 401，权限或来源不符返回 403，当前账号内不存在的资源返回 404，超出大小/预算返回 413，超过额度或当前账号已有任务返回 429，全站任务繁忙或服务未配置返回 503。初始校验失败使用 HTTP 错误；SSE 开始后的错误通过事件说明。错误不回显密码或请求正文。

工作目录的存储预算不是操作系统的硬磁盘配额，向量库/SQLite 元数据仍有开销，删除内容不一定立即收缩数据库文件。生产环境仍需磁盘监控、备份及适合实际用户量的入口流量限制。
