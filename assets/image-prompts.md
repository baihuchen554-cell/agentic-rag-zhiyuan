# 图表生成记录

## 流程图连线校订

首版图中跨面板的虚线容易混淆数据访问关系，最终版移除入库面板与问答面板之间的虚线，保留问答面板内的 SQLite 记忆回路，并在检索框中明确标注本地 Qdrant。以下是内置 GPT Image 的精确编辑提示词。

+### workflow_zh

```text
Edit this existing Chinese scientific workflow figure with one precise topology correction. Remove ALL dashed connector lines and arrowheads that cross from the top panel A (document ingestion) to the bottom panel B (question answering). There must be no arrows between panel A and panel B. They are two separate process views. In panel B change the teal box text from 强制检索知识库 to exactly 强制检索本地 Qdrant (wrap across two lines if needed). Keep ALL solid arrows, all other wording, every box, white background, navy/teal/amber scientific style, and the complete SQLite dashed feedback loop WITHIN panel B exactly intact. In particular the memory loop from final answer back to SQLite and SQLite to history rewriting MUST remain. Keep Qdrant cylinder and Parent JSON separate in panel A. No other edits. This removes misleading cross-panel data-access arrows while retaining the real knowledge-first flow.
```

### workflow_en

```text
Edit this existing English scientific workflow figure with a precise topology correction. Remove ALL dashed connector lines starting from Parent JSON store, Dense + sparse vectors, and Local Qdrant in panel A. Remove the small label Data access for local retrieval between panels. There must be NO dashed or solid arrows between the top ingestion panel A and bottom question-answering panel B, and NO arrow linking Parent JSON store to Qdrant. The two panels are separate process views. Change ONLY the bottom retrieval box label from Mandatory local retrieval to exactly Mandatory local Qdrant retrieval (wrap neatly). Preserve EVERY solid process arrow, all other text, node placement, typography, title, navy/teal/amber scientific style and the entire SQLite dashed feedback loop INSIDE panel B. The memory loop from final answer back to SQLite and SQLite to history rewriting MUST remain unchanged. Keep ample margins and text crisp. No other changes.
```

使用内置 GPT Image 生成；图片是架构说明，实际行为以源代码和测试为准。图中文字不包含真实文档、聊天记录或密钥。

## workflow_zh.png

```text
Use case: scientific-educational. Asset: Chinese research-style architecture workflow figure for the actual open-source application “知源 · ZhiYuan RAG”. Create a crisp high-resolution wide landscape diagram on pure white, publication-quality, generous margins, consistent slim vector-like strokes, aligned rectangular boxes, restrained navy, slate gray and muted teal; use amber only for the web fallback. Clean Simplified Chinese typography, large legible labels, no cartoon, no photos, no gradients, no shadows, no watermark, no fabricated metrics. Render only the specified technical labels accurately.
Title: “知源 · ZhiYuan RAG”
Subtitle: “知识库优先的文档问答流程”
Two horizontal panels. Panel A heading “A  文档入库”. Left-to-right chain: “PDF / Markdown” → “解析文档” (small line “PyMuPDF4LLM”) → “父子分块”. From parent-child split, branch to a small store “父文档 JSON”; main chain continues to “稠密 + 稀疏向量” (small line “Qwen API + BM25”) → cylinder “本地 Qdrant”. Connect both the parent store and Qdrant down into the local retrieval component in panel B using subtle dashed data-access lines.
Panel B heading “B  问答与记忆”. Main chain from “用户问题” to “历史摘要与问题改写” to “强制检索知识库” to decision diamond “证据充足？”. YES / “是” branch goes to “本地文档回答” with small line “按需获取父文档”; NO / “否” branch goes to amber “联网搜索补充” with small line “DeepSeek Search API”. Both branches merge into “DeepSeek 整合答案” → “流式回答 + 来源引用”. Under the NO search box add small note “搜索不可用：明确标注未联网核实”.
Show a slim “SQLite 聊天记录与记忆” bar beneath panel B: dashed arrows from this store to history/rewrite and from final answer back to it, a genuine feedback loop, clearly not a replacement for Qdrant.
At the bottom a single small footer note: “普通聊天使用会话记忆；文档问题先检索；支持停止生成”.
All arrows must be unambiguous: web search only after local retrieval fails to supply enough evidence, never before retrieval. Keep this high-level architecture faithful and readable, not a dense code graph. All content inside canvas.
```

## workflow_en.png

```text
Use case: scientific-educational. Asset: English research-style architecture workflow figure for the actual project “ZhiYuan RAG”. Create a crisp high-resolution wide landscape figure on pure white with generous margins, publication-quality clean sans-serif typography, aligned rectangular nodes, slim vector-like arrows, navy/slate and muted teal palette; amber reserved for web fallback. No cartoon, photography, gradients, shadows, watermark or invented metrics.
Title exactly “ZhiYuan RAG”
Subtitle “Knowledge-first document question answering”
Two horizontal panels. Panel A title “A  DOCUMENT INGESTION”. Left-to-right: “PDF / Markdown” → “Document parsing” (small text “PyMuPDF4LLM”) → “Parent–child chunking”. Split a branch to a small store “Parent JSON store”; main path goes to “Dense + sparse vectors” (small text “Qwen API + BM25”) → cylinder “Local Qdrant”. Subtle dashed data-access arrows from the parent store and Qdrant to local retrieval in panel B.
Panel B title “B  QUESTION ANSWERING & MEMORY”. Left-to-right main path: “User question” → “History summary & query rewriting” → “Mandatory local retrieval” → decision diamond “Enough evidence?”. Branch YES to “Document-grounded answer” (small text “Fetch parents as needed”). Branch NO to amber “Web search fallback” (small text “DeepSeek Search API”). Merge both paths at “DeepSeek answer synthesis” → “Streamed answer + citations”.
Beneath the search fallback include small note “If search fails: clearly mark unverified model knowledge”.
Below panel B, a slim store “SQLite conversation history & memory” with dashed feedback arrows: store to history/rewrite, and streamed answer back to store. Keep SQLite distinct from Qdrant.
Footer “Conversation-only turns use memory • Document questions retrieve first • Generation can be stopped”.
Correct flow is essential: web search only after mandatory local retrieval lacks sufficient evidence. Legible high-level architecture, not a dense node graph. All labels comfortably inside canvas.
```

## tech_stack.png

```text
Use case: scientific-educational. Asset: bilingual technology stack figure for the real Python application “知源 · ZhiYuan RAG”. Publication-quality wide landscape on pure white, clear typography, navy headers, thin slate borders, very light teal grouping, generous spacing, consistent minimal vector-like line art. No logos copied from vendors, no cartoon, no gradients, no shadows, no charts of invented measurements, no watermark. Clear crisp Chinese and English labels.
Title exactly “知源 · ZhiYuan RAG”
Subtitle exactly “技术栈 / Technology Stack”
Show four clearly labeled horizontal architectural layers, with three or four aligned rectangular cards per layer. Make headings and technology names large, centered and precisely spelled.
Layer 1: “交互层 / Interface”. Cards: “Gradio 6” with subtitle “Web UI & streaming”; “HTML · CSS · JavaScript” with subtitle “Minimal responsive interface”.
Layer 2: “应用与编排 / Application”. Cards: “Python 3.11”; “LangGraph” with subtitle “Stateful agent workflow”; “LangChain + Pydantic” with subtitle “Model adapters & schemas”.
Layer 3: “解析与模型 / Parsing & Models”. Group LOCAL on left and CLOUD API on right, explicitly distinguished with small labels “本地 / Local” and “云端 API / Cloud APIs”. Local cards “PyMuPDF + PyMuPDF4LLM” subtitle “PDF to Markdown” and “FastEmbed · BM25” subtitle “Sparse embeddings”. Cloud API cards “Qwen Embedding API” subtitle “Dense embeddings” and “DeepSeek API” subtitle “Chat · decisions · synthesis · search”.
Layer 4: “数据层 / Storage”. Cards: “Local Qdrant” subtitle “Dense + sparse vectors”; “SQLite” subtitle “Chat history & memory”; “Markdown + JSON” subtitle “Documents & parent chunks”.
Use subtle straight connectors between layer groups, no misleading direct flow arrows among unrelated tools. Small bottom caption “本地存储，云端模型 / Local storage, cloud models”. This is a single integrated Python / Gradio application, not separate React/Node services. Do not include Langfuse, telemetry services, Docker, Redis, PostgreSQL or unimplemented tools.
```
