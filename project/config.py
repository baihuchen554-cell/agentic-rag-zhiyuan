import os
from dotenv import load_dotenv

# API 密钥填写在 project/.env；系统环境变量优先。
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- 目录配置 ---
_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
APP_NAME = "知源"
APP_TITLE = "知源 · ZhiYuan RAG"
ASSETS_DIR = os.path.join(_BASE_DIR, "assets")

# --- Qdrant 配置 ---
CHILD_COLLECTION = "document_child_chunks"
SPARSE_VECTOR_NAME = "sparse"

# --- 模型配置 ---
DENSE_MODEL = "qwen3.7-text-embedding-flash"
DENSE_DIMENSIONS = 1024
EMBEDDING_BATCH_SIZE = 20  # 百炼单次请求最多 20 条文本
EMBEDDING_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).strip().rstrip("/")
SPARSE_MODEL = "Qdrant/bm25"
# 官方 API 名称；当前对应 DeepSeek-V4.1-Flash-1017。
LLM_MODEL = "deepseek-flash"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).strip().rstrip("/")
MODEL_API_TIMEOUT = 120
MODEL_API_MAX_RETRIES = 2
LLM_TEMPERATURE = 0

# 模型和维度共同决定存储目录，旧本地模型的数据保留在原目录。
_INDEX_DIR = os.path.join(_BASE_DIR, "knowledge_base", f"{DENSE_MODEL}_{DENSE_DIMENSIONS}")
MARKDOWN_DIR = os.path.join(_INDEX_DIR, "markdown_docs")
PARENT_STORE_PATH = os.path.join(_INDEX_DIR, "parent_store")
QDRANT_DB_PATH = os.path.join(_INDEX_DIR, "qdrant_db")
CHAT_HISTORY_PATH = os.path.join(_BASE_DIR, "chat_history", "conversations.sqlite3")


def validate_model_api_settings():
    missing = [
        name for name, value in (
            ("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY),
            ("DASHSCOPE_API_KEY", EMBEDDING_API_KEY),
        ) if not value
    ]
    if missing:
        raise ValueError("请先在 project/.env 中填写：" + "、".join(missing))


# --- 检索配置 ---
RETRIEVAL_SCORE_THRESHOLD = 0.4
DEFAULT_RETRIEVAL_K = 7
CHILD_CHUNK_SEPARATOR = "\n\n<CHILD_CHUNK_BOUNDARY>\n\n"

# --- 联网补充配置（复用 DeepSeek 密钥）---
WEB_SEARCH_ENABLED = os.environ.get("WEB_SEARCH_ENABLED", "true").lower() == "true"
WEB_SEARCH_RESULT_COUNT = 5
WEB_SEARCH_TIMEOUT = 25
WEB_SOURCE_MAX_CHARS = 6000

# --- 智能体配置 ---
MAX_TOOL_CALLS = 8
MAX_ITERATIONS = 10
GRAPH_RECURSION_LIMIT = 50
MAIN_HISTORY_MESSAGES_TO_KEEP = 12
BASE_TOKEN_THRESHOLD = 2000
TOKEN_GROWTH_FACTOR = 0.9

# --- 终端执行日志配置 ---
EXECUTION_LOGGING_ENABLED = False
EXECUTION_LOG_MAX_CHARS = 1200
EXECUTION_LOG_USE_COLOR = True

# --- 文本分块器配置 ---
CHILD_CHUNK_SIZE = 500
CHILD_CHUNK_OVERLAP = 100
MIN_PARENT_SIZE = 2000
MAX_PARENT_SIZE = 4000
HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3")
]
