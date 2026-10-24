import uuid
import config
from db.vector_db_manager import VectorDbManager
from db.parent_store_manager import ParentStoreManager
from document_chunker import DocumentChunker
from rag_agent.tools import ToolFactory
from rag_agent.graph import create_agent_graph
from langchain_deepseek import ChatDeepSeek

class RAGSystem:

    def __init__(self, collection_name=config.CHILD_COLLECTION, paths=None):
        config.validate_model_api_settings()
        # 保存向量集合名称，并初始化数据库和文档切分器。
        self.collection_name = collection_name
        self.markdown_dir = paths.markdown if paths else config.MARKDOWN_DIR
        self.vector_db = VectorDbManager(db_path=paths.vectors) if paths else VectorDbManager()
        self.parent_store = ParentStoreManager(paths.parents) if paths else ParentStoreManager()
        self.chunker = DocumentChunker()

        # 智能体工作流将在 initialize() 中创建
        self.agent_graph = None

        # 为当前会话生成唯一 ID，用于区分不同的聊天会话
        self.thread_id = str(uuid.uuid4())

        # 设置 LangGraph 工作流的最大递归深度
        self.recursion_limit = config.GRAPH_RECURSION_LIMIT

    def initialize(self):
        # 创建或准备向量集合，并获取集合对象
        self.vector_db.create_collection(self.collection_name)
        collection = self.vector_db.get_collection(self.collection_name)

        # 所有生成和决策节点共用 DeepSeek API。
        # 关闭思考模式，保持工具调用和流式输出简洁。
        llm = ChatDeepSeek(
            model=config.LLM_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            api_base=config.DEEPSEEK_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.MODEL_API_TIMEOUT,
            max_retries=config.MODEL_API_MAX_RETRIES,
            max_tokens=config.MODEL_MAX_OUTPUT_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )

        # 根据向量集合创建检索工具，并构建智能体工作流
        tools = ToolFactory(collection, parent_store=self.parent_store).create_tools()
        self.agent_graph = create_agent_graph(llm, tools)

    def get_config(self, thread_id=None):
        # 设置会话 ID 和工作流递归限制
        return {
            "configurable": {"thread_id": thread_id or self.thread_id},
            "recursion_limit": self.recursion_limit,
            "max_concurrency": config.GRAPH_MAX_CONCURRENCY,
        }
