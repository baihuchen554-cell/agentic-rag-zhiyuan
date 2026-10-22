from langchain_core.tools import tool
import config
from db.parent_store_manager import ParentStoreManager
from core.execution_logger import log_error, log_tool_end, log_tool_start


class ToolFactory:

    def __init__(self, collection):
        # 保存向量数据库集合，并初始化父文档存储管理器
        self.collection = collection
        self.parent_store_manager = ParentStoreManager()

    def _search_child_chunks(self, query: str, limit: int = config.DEFAULT_RETRIEVAL_K) -> str:
        """搜索与用户问题相关的文档片段。

        这是文档检索的第一步。返回结果包含父文档块 ID、文件名和子块文本。
        如果检索到的片段与问题相关，但内容过于零散，无法可靠地回答问题，
        则可以使用返回的 parent_id 调用 retrieve_parent_chunks 获取完整父文档块。

        参数：
            query：包含问题核心关键词的检索查询。
            limit：最多返回的子文档块数量。
        """
        # 记录检索工具的调用信息
        log_tool_start("search_child_chunks", {"query": query, "limit": limit})

        try:
            # 在向量数据库中执行相似度检索
            results = self.collection.similarity_search(
                query,
                k=limit,
                score_threshold=config.RETRIEVAL_SCORE_THRESHOLD,
            )

            # 没有找到符合相似度阈值的结果时，返回约定的状态标识
            if not results:
                output = "NO_RELEVANT_CHUNKS"
                log_tool_end("search_child_chunks", output)
                return output

            # 整理检索结果，包含父文档块 ID、文件名和文本内容
            # 多个子块之间使用配置中的分隔符连接
            output = config.CHILD_CHUNK_SEPARATOR.join([
                f"父文档块标识：{doc.metadata.get('parent_id', '')}\n"
                f"文件名：{doc.metadata.get('source', '')}\n"
                f"内容：{doc.page_content.strip()}"
                for doc in results
            ])

            # 记录工具输出并返回检索结果
            log_tool_end("search_child_chunks", output)
            return output

        except Exception as e:
            # 发生检索异常时，记录错误并返回错误标识
            log_error("search_child_chunks", e)
            output = f"RETRIEVAL_ERROR: {str(e)}"
            log_tool_end("search_child_chunks", output)
            return output

    def _retrieve_parent_chunks(self, parent_id: str) -> str:
        """根据父文档块 ID 获取完整的父文档块内容。

        仅当 search_child_chunks 返回了相关的 parent_id，
        且子块片段缺少必要的上下文时，才调用此工具。
        不要重复获取压缩上下文中已经包含的父文档块。

        参数：
            parent_id：由 search_child_chunks 返回的父文档块 ID。
        """
        # 记录父文档块检索工具的调用信息
        log_tool_start("retrieve_parent_chunks", {"parent_id": parent_id})

        try:
            # 根据父文档块 ID 从父文档存储中读取完整内容
            parent = self.parent_store_manager.load_content(parent_id)

            # 如果没有找到对应的父文档块，返回约定的状态标识
            if not parent:
                output = "NO_PARENT_DOCUMENT"
                log_tool_end("retrieve_parent_chunks", output)
                return output

            # 整理父文档块信息，方便模型结合完整上下文进行回答
            output = (
                f"父文档块标识：{parent.get('parent_id', '未提供')}\n"
                f"文件名：{parent.get('metadata', {}).get('source', '未知')}\n"
                f"内容：{parent.get('content', '').strip()}"
            )

            # 记录工具输出并返回完整父文档块
            log_tool_end("retrieve_parent_chunks", output)
            return output

        except Exception as e:
            # 发生异常时，记录错误并返回父文档检索错误标识
            log_error("retrieve_parent_chunks", e)
            output = f"PARENT_RETRIEVAL_ERROR: {str(e)}"
            log_tool_end("retrieve_parent_chunks", output)
            return output

    def create_tools(self) -> list:
        """创建并返回供智能体调用的工具列表。"""

        # 将普通 Python 方法包装成 LangChain 工具
        search_tool = tool("search_child_chunks")(self._search_child_chunks)
        retrieve_tool = tool("retrieve_parent_chunks")(self._retrieve_parent_chunks)

        # 返回子块搜索工具和父文档块检索工具
        return [search_tool, retrieve_tool]