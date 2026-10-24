import os
import hashlib
import tempfile
from dotenv import load_dotenv

# API 密钥填写在 project/.env；系统环境变量优先。
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- 目录配置 ---
_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
os.environ.setdefault('GRADIO_TEMP_DIR', os.path.join(tempfile.gettempdir(),
    'knowva-gradio-' + hashlib.sha256(_BASE_DIR.encode()).hexdigest()[:12]))
APP_NAME = "knowva"
APP_TITLE = APP_NAME
ASSETS_DIR = os.path.join(_BASE_DIR, "assets")
APP_LOGO_PATH = os.path.join(ASSETS_DIR, "logo.svg")

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
USER_DATA_DIR = os.path.join(_BASE_DIR, "user_data")
ACCOUNT_DB_PATH = os.path.join(_BASE_DIR, "account_data", "accounts.sqlite3")
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
TURNSTILE_HOSTNAMES = tuple(host.strip().lower() for host in
    os.environ.get("TURNSTILE_HOSTNAMES", "knowva.xin").split(",") if host.strip())


def _positive_env(name, default, minimum=1):
    value = int(os.environ.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} 必须是大于等于 {minimum} 的整数")
    return value


# 默认针对 2 核 2 GB 单进程服务；全部在服务端执行。
DAILY_QUESTIONS = _positive_env("DAILY_QUESTIONS", 30)
DAILY_EMBEDDING_CHARS = _positive_env("DAILY_EMBEDDING_CHARS", 500_000)
DAILY_UPLOAD_BYTES = _positive_env("DAILY_UPLOAD_MB", 50) * 1024 * 1024
MAX_UPLOAD_BYTES = _positive_env("MAX_UPLOAD_MB", 10) * 1024 * 1024
MAX_UPLOAD_BATCH = _positive_env("MAX_UPLOAD_BATCH", 3)
MAX_DOCUMENTS = _positive_env("MAX_DOCUMENTS", 30)
USER_STORAGE_BYTES = _positive_env("USER_STORAGE_MB", 100) * 1024 * 1024
MAX_PDF_PAGES = _positive_env("MAX_PDF_PAGES", 100)
MAX_DOCUMENT_CHARS = _positive_env("MAX_DOCUMENT_CHARS", 200_000)
MAX_DOCUMENT_CHUNKS = _positive_env("MAX_DOCUMENT_CHUNKS", 600)
MAX_QUESTION_CHARS = _positive_env("MAX_QUESTION_CHARS", 4000)
MODEL_MAX_OUTPUT_TOKENS = _positive_env("MODEL_MAX_OUTPUT_TOKENS", 2048)
MAX_ACTIVE_TASKS = _positive_env("MAX_ACTIVE_TASKS", 2)
MAX_CACHED_WORKSPACES = _positive_env("MAX_CACHED_WORKSPACES", 3)
WORKSPACE_IDLE_SECONDS = _positive_env("WORKSPACE_IDLE_SECONDS", 600)
WORKSPACE_MAX_AGE_SECONDS = _positive_env("WORKSPACE_MAX_AGE_SECONDS", 3600)
# 流式读取也占用执行线程；1 会让读取等待阻塞图节点执行。
GRAPH_MAX_CONCURRENCY = _positive_env("GRAPH_MAX_CONCURRENCY", 2, minimum=2)
UPLOAD_TTL_SECONDS = _positive_env("UPLOAD_TTL_SECONDS", 3600)
QUEUE_MAX_SIZE = _positive_env("QUEUE_MAX_SIZE", 16)
MAX_UPLOAD_CACHE_BYTES = _positive_env("MAX_UPLOAD_CACHE_MB", 256) * 1024 * 1024
MIN_DISK_FREE_BYTES = _positive_env("MIN_DISK_FREE_MB", 256) * 1024 * 1024


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
