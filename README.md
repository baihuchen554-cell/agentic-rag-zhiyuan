<p align="center"><img src="assets/logo.png" width="84" alt="知源项目图标"></p>

<h1 align="center">知源 · ZhiYuan RAG</h1>

<p align="center">先查文档，再补充互联网。让回答有来源，让对话有记忆。</p>

知源是一个本地运行的中文文档问答应用：上传 PDF / Markdown，构建知识库，并通过对话查询资料。文档问题首先执行本地混合检索，资料不足时联网补充，并展示实际搜索到的网站来源。

基于 [Giovanni Pasqualino 的 agentic-rag-for-dummies](https://github.com/GiovanniPasq/agentic-rag-for-dummies) 改造，保留原作者署名，继续使用 [MIT License](LICENSE)。

**当前为知源初始预览版 v0.1.0**，发布标签为 `zhiyuan-v0.1.0`，后续会持续迭代。此版本号属于本复刻项目，与上游版本号独立。仓库名称为 `agentic-rag-zhiyuan`。

这是独立维护的学习与二次开发项目，核心架构源自上游；本项目不代表原作者或相关模型服务商，未获其官方背书。当前适合个人本地使用和部署测试，尚未实现用户登录、管理员权限、按用户隔离的数据或调用配额，请勿直接作为开放的多用户服务上线。已实现内容见下文，版本记录见 [CHANGELOG.md](CHANGELOG.md)，使用前请阅读 [免责声明](DISCLAIMER.md) 和 [安全说明](SECURITY.md)。

## 功能

- **知识库优先**：程序强制执行首次本地检索，模型不能跳过；检索异常会提示重试，不会被当作“无资料”转去联网。
- **混合检索与父子分块**：Qwen API 稠密向量 + FastEmbed BM25 稀疏向量，由本地 Qdrant 检索，按需获取父文档补充上下文。
- **联网补充与引用**：调用 DeepSeek 搜索接口，引用链接以实际搜索结果为准；搜索不可用时标注“未能联网核实”。
- **持久聊天记忆**：SQLite 保存记录与记忆，支持历史切换、重启后继续提问、独立会话及删除对话。
- **真实入库状态**：展示解析、切分、索引阶段及实际写入段数，不用文件序号冒充进度；支持失败重试和选择删除文档。
- **极简中文界面**：手机布局、流式回答、复制回答、Enter 发送、Shift+Enter 换行、生成中随时停止。
- **处理过程可见**：回答上方展示可折叠的执行摘要，不输出模型内部推理原文。

## 快速开始

### 环境

使用 **Python 3.11 及以上版本**。在 Windows PowerShell 中：

```powershell
git clone https://github.com/baihuchen554-cell/agentic-rag-zhiyuan.git
cd agentic-rag-zhiyuan
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

已有项目直接进入当前根目录即可，本地文件夹名称不影响应用名称。

### 配置 API

配置文件是 **`project/.env`**。首次使用时复制模板，已有配置不会覆盖：

```powershell
if (-not (Test-Path project/.env)) {
    Copy-Item project/.env.example project/.env
}
```

编辑 `project/.env`：

```dotenv
DASHSCOPE_API_KEY=你的百炼密钥
DEEPSEEK_API_KEY=你的DeepSeek密钥
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_BASE_URL=https://api.deepseek.com
WEB_SEARCH_ENABLED=true
```

系统环境变量优先于 `.env`。模型名称、维度和分块参数在 [project/config.py](project/config.py)。

### 启动和停止

```powershell
.\.venv\Scripts\python.exe project\app.py
```

打开终端显示的地址，通常是 **http://127.0.0.1:7860**。首次启动可能需要下载 BM25 模型。

请在自己的终端以前台方式运行，停止时在同一终端按 **Ctrl+C**。本地 Qdrant 的同一份知识库只能由一个应用实例打开；修改代码后重启应用。

<details>
<summary>Linux / macOS</summary>

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 首次使用才复制模板，已有 project/.env 则跳过
cp -n project/.env.example project/.env
# 编辑 project/.env 后启动
.venv/bin/python project/app.py
```

</details>

## 使用

### 文档入库

1. 点击“知识库”，选择或拖入 PDF / Markdown 文件。
2. 上传结束后点击“开始入库”。
3. 状态卡依次显示“解析文档 → 文本切分 → 建立索引”。解析耗时未知时不显示虚假百分比；索引按成功写入的文本段计数。
4. 显示“入库完成”后即可提问；失败时保留所选文件，点击“重试入库”重试。
5. 已入库列表中勾选文档，点击“删除所选”并确认，可同时删除文档与对应索引。

按不含扩展名的名称判重，例如 `手册.pdf` 和 `手册.md` 视为同一文档。更新文件时先删除旧文档，再上传新版本。原始 PDF 不作为长期归档保存，请自行保留原件。

### 聊天与记忆

- **Enter** 发送，**Shift+Enter** 换行。
- 生成时按钮切换为停止方块；点击后停止页面输出，保留已有回答，并可继续提问。已发出的远程请求可能仍由服务商处理，迟到结果不会覆盖新回答。
- 文档问题先检索知识库，资料不足时联网；问候、记录个人偏好和回顾本次聊天使用会话记忆。
- 历史列表可恢复旧会话；“删除当前对话”确认后同时移除聊天记录与对应记忆。
- 回答上方的“处理过程”展示真实执行阶段和来源摘要，完成后自动折叠，不会作为用户事实传回模型。

## 工作流程

![中文项目流程图](assets/workflow_zh.png)

<details>
<summary>English workflow</summary>

![English workflow](assets/workflow_en.png)

</details>

实际路径：

```text
问题 + 会话记忆 → 历史摘要与问题改写
  ├─ 普通聊天 → 根据记忆回复
  └─ 文档问答 → 强制本地混合检索
       ├─ 证据充足 → 文档回答，按需获取父文档
       └─ 证据不足 → 联网搜索；不可用时标注未核实
     → DeepSeek 整合答案与来源 → 流式显示 → 保存记忆
```

不清晰的问题会先请求澄清；多个独立子问题分别检索后再整合。工作流包含检索上下文压缩和工具调用次数限制。

## 技术栈与配置

![技术栈](assets/tech_stack.png)

| 用途 | 当前配置 | 位置 |
| --- | --- | --- |
| 对话、改写、检索决策、整合 | DeepSeek API：`deepseek-flash` | 云端 |
| 稠密向量 | `qwen3.7-text-embedding-flash`，1024 维 | 百炼 API |
| 稀疏向量 | `Qdrant/bm25`，FastEmbed | 本地 |
| 联网检索 | DeepSeek `/v1/tools/search` | 云端 |
| 向量存储 | Qdrant 本地模式 | 本机 |
| 聊天记录与记忆 | SQLite | 本机 |
| 界面与编排 | Gradio 6、LangGraph、LangChain、Pydantic | Python |
| PDF 解析 | PyMuPDF、PyMuPDF4LLM | 本机 |

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `EMBEDDING_BATCH_SIZE` | 20 | 每批向量化及写入的段数 |
| `CHILD_CHUNK_SIZE` / `CHILD_CHUNK_OVERLAP` | 500 / 100 | 子块字符数与重叠量 |
| `MIN_PARENT_SIZE` / `MAX_PARENT_SIZE` | 2000 / 4000 | 父文档块长度范围 |
| `DEFAULT_RETRIEVAL_K` / `RETRIEVAL_SCORE_THRESHOLD` | 7 / 0.4 | 召回数量与得分阈值 |
| `MAIN_HISTORY_MESSAGES_TO_KEEP` | 12 | 工作流近期消息窗口，包含本轮消息 |
| `MODEL_API_TIMEOUT` | 120 秒 | 模型请求超时 |
| `MAX_TOOL_CALLS` / `MAX_ITERATIONS` | 8 / 10 | 单个子问题执行预算 |
| `WEB_SEARCH_ENABLED` | true | 可在 `.env` 中关闭联网补充 |

更换稠密向量模型或维度后会使用新的知识库目录，需要重新入库；聊天记录独立保存，不随模型更换而清空。

图表使用内置 **GPT Image** 生成，采用白底科研风。提示词和修订记录见 [assets/image-prompts.md](assets/image-prompts.md)。

## 项目结构

```text
assets/
  logo.png                项目图标
  icons/                  界面 SVG 图标
  workflow_zh.png         中文项目流程图
  workflow_en.png         英文项目流程图
  tech_stack.png          中英双语技术栈图
  image-prompts.md        图表提示词与生成记录
project/
  app.py                  程序入口
  config.py               名称、模型、路径和参数
  .env.example            API 配置模板
  core/                   文档、聊天、记忆、联网和执行状态
  db/                     Qdrant 与父文档存储
  rag_agent/              LangGraph 工作流、路由和提示词
  ui/                     Gradio 页面、样式、交互和中文翻译
  document_chunker.py     父子分块
  utils.py                PDF 转换、Token 估算
tests/                    离线回归测试
knowledge_base/            按模型和维度隔离的知识库（运行时生成）
chat_history/             SQLite 聊天记录（运行时生成）
requirements.txt          锁定的运行依赖
LICENSE                   MIT 许可与原作者署名
```

资源统一放在 `assets/`，不依赖开发者电脑上的临时图片。根目录如已有旧版 `qdrant_db/` 数据会保留，当前应用使用 `knowledge_base/<模型>_<维度>/`。

## 数据与备份

- Markdown、父块 JSON 和向量索引：`knowledge_base/<模型>_<维度>/`。
- 聊天记录与记忆：`chat_history/`，与向量索引相互独立。
- 备份前停止应用，再复制整个 `knowledge_base/` 和 `chat_history/`；恢复到原位置后启动。
- `project/.env` 单独妥善保管，勿提交版本库。运行数据与密钥均已列入 `.gitignore`。
- **本地存储不代表完全离线**：文档文本会发送到向量 API；召回内容、问题和必要的会话上下文会发送到 DeepSeek；联网补充时向搜索接口发送检索问题。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 缺少 API 配置 | 检查 `project/.env` 中两个密钥，以及终端环境变量是否覆盖它们。 |
| 知识库被另一实例占用 | 在旧应用所在终端按 Ctrl+C，确认退出后再启动。不要删除数据库锁文件。 |
| 当前终端 Ctrl+C 无效 | 若终端已回到提示符，它没有运行服务；请在实际启动旧实例的终端停止。 |
| 上传后尚未入库 | 上传只传输文件；结束后点击“开始入库”，查看下方状态卡。 |
| 长时间停在解析 | 检查 PDF 页数、扫描内容和复杂表格；解析速度与向量 API 无关。可先转换为 Markdown 再上传。 |
| 停在建立索引 | 检查向量接口网络和限流；仅在每批写入成功后增加段数。 |
| 同名文件无法更新 | 先删除旧文档及索引，再上传新版本。 |
| 联网回答没有来源 | 搜索未返回可用网页时会标注未联网核实，不把模型生成的网址当作已检索出处。 |

## 开发检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q project tests
.\.venv\Scripts\python.exe -m pip check
```

测试使用临时数据、测试数据库和模拟接口，覆盖知识库优先、来源校验、记忆恢复、会话删除、停止生成、分批入库与失败回滚、文档删除、PDF 转换和数据库占用，不调用真实付费模型，不修改现有知识库。

## 致谢与许可

原项目：[agentic-rag-for-dummies](https://github.com/GiovanniPasq/agentic-rag-for-dummies)，作者 **Giovanni Pasqualino**，Copyright © 2025。

本项目在原实现基础上加入中文界面、云端模型接口、知识库优先检索、持久会话记忆、联网来源校验、可中止流式生成和分阶段入库状态，整理为“知源 · ZhiYuan RAG”。2026 年新增修改由 ZhiYuan RAG contributors 贡献。

继续采用 MIT 许可，原始版权声明与许可条款完整保留在 [LICENSE](LICENSE)。第三方依赖和服务遵循各自的许可及使用条款。

代码的 MIT 许可不代表第三方依赖、模型、字体或用户文档均适用 MIT；分发或商用时应另行核实各自的许可和使用条件。软件按现状提供，AI 回答及其引用需要使用者自行核验，详细说明见 [DISCLAIMER.md](DISCLAIMER.md)。
