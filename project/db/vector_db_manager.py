import config
import logging
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from langchain_qdrant.sparse_embeddings import SparseEmbeddings
from threading import RLock


class SharedSparseEmbeddings(SparseEmbeddings):
    """BM25 是无用户数据的编码器；跨工作空间共享，并串行保护编码调用。"""
    _instances = {}
    _creation_lock = RLock()

    @classmethod
    def get(cls):
        key = (FastEmbedSparse, config.SPARSE_MODEL)
        with cls._creation_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(FastEmbedSparse(model_name=config.SPARSE_MODEL))
            return cls._instances[key]

    def __init__(self, model):
        self.model, self.lock = model, RLock()

    def embed_documents(self, texts):
        with self.lock:
            return self.model.embed_documents(texts)

    def embed_query(self, text):
        with self.lock:
            return self.model.embed_query(text)


class KnowledgeBaseInUseError(RuntimeError):
    """本地数据库已被另一个进程独占。"""


class VectorDbManager:
    # 声明 Qdrant 客户端和两种向量嵌入模型
    __client: QdrantClient
    __dense_embeddings: OpenAIEmbeddings
    __sparse_embeddings: FastEmbedSparse

    def __init__(self, db_path=None):
        config.validate_model_api_settings()
        # 初始化本地 Qdrant 向量数据库
        try:
            self.__client = QdrantClient(path=db_path or config.QDRANT_DB_PATH)
        except RuntimeError as exc:
            if "already accessed by another instance" in str(exc):
                raise KnowledgeBaseInUseError(
                    "知识库正在被另一个程序使用。请在旧程序终端按 Ctrl+C 停止后，再重新启动。"
                ) from exc
            raise

        try:
            # 初始化稠密向量模型和稀疏向量模型
            self.__dense_embeddings = OpenAIEmbeddings(
                model=config.DENSE_MODEL,
                api_key=config.EMBEDDING_API_KEY,
                base_url=config.EMBEDDING_BASE_URL,
                dimensions=config.DENSE_DIMENSIONS,
                chunk_size=config.EMBEDDING_BATCH_SIZE,
                # 百炼接收原始文本；不使用 OpenAI 分词器或 base64 向量。
                check_embedding_ctx_length=False,
                model_kwargs={"encoding_format": "float"},
                request_timeout=config.MODEL_API_TIMEOUT,
                max_retries=config.MODEL_API_MAX_RETRIES,
            )
            self.__sparse_embeddings = SharedSparseEmbeddings.get()

        except Exception:
            self.__client.close()
            raise

    def _dense_vector_size(self):
        # 维度已经显式指定，无需在每次启动时额外请求向量 API。
        return config.DENSE_DIMENSIONS

    def close(self):
        self.__client.close()

    @staticmethod
    def _collection_vector_size(collection_info):
        # 获取向量集合的向量配置，兼容不同的数据结构
        vectors_config = collection_info.config.params.vectors

        # 处理单个稠密向量的配置
        if hasattr(vectors_config, "size"):
            return vectors_config.size

        # 处理以字典形式保存的向量配置
        if isinstance(vectors_config, dict) and vectors_config:
            first_vector = next(iter(vectors_config.values()))
            return getattr(first_vector, "size", None)

        # 无法获取向量维度时返回 None
        return None

    def create_collection(self, collection_name):
        # 获取当前稠密向量模型生成的向量维度
        expected_size = self._dense_vector_size()

        # 如果集合不存在，则创建新的向量集合
        if not self.__client.collection_exists(collection_name):
            logging.getLogger(__name__).info("正在创建向量集合：%s...", collection_name)

            self.__client.create_collection(
                collection_name=collection_name,

                # 配置稠密向量的维度和余弦相似度计算方式
                vectors_config=qmodels.VectorParams(
                    size=expected_size,
                    distance=qmodels.Distance.COSINE
                ),

                # 配置稀疏向量，用于混合检索
                sparse_vectors_config={
                    config.SPARSE_VECTOR_NAME: qmodels.SparseVectorParams()
                },
            )

            logging.getLogger(__name__).info("✓ 向量集合创建成功：%s", collection_name)

        else:
            # 集合已存在时，检查其稠密向量维度是否与当前模型匹配
            collection_info = self.__client.get_collection(collection_name)
            existing_size = self._collection_vector_size(collection_info)

            if existing_size and existing_size != expected_size:
                raise ValueError(
                    f"Qdrant 向量集合“{collection_name}”的稠密向量维度为 "
                    f"{existing_size}，但模型“{config.DENSE_MODEL}”生成的向量维度为 "
                    f"{expected_size}。更换嵌入模型后，请清空并重新建立索引。"
                )

            logging.getLogger(__name__).info("✓ 向量集合已存在：%s", collection_name)

    def delete_sources(self, collection_name, sources):
        if not sources:
            return
        # 按原始文件名精确匹配，等待向量删除完成后再清理本地文档。
        self.__client.delete(
            collection_name=collection_name,
            points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
                qmodels.FieldCondition(
                    key="metadata.source", match=qmodels.MatchAny(any=list(sources)),
                ),
            ])),
            wait=True,
        )

    def delete_collection(self, collection_name):
        # 删除指定的向量集合
        try:
            if self.__client.collection_exists(collection_name):
                print(f"正在删除现有的 Qdrant 向量集合：{collection_name}")
                self.__client.delete_collection(collection_name)

        except Exception as e:
            # 删除失败时抛出异常，并保留原始异常作为错误原因
            raise RuntimeError(
                f"无法删除 Qdrant 向量集合“{collection_name}”。"
            ) from e

    def get_collection(self, collection_name) -> QdrantVectorStore:
        # 获取向量集合，并配置混合检索所需的嵌入模型
        try:
            return QdrantVectorStore(
                client=self.__client,
                collection_name=collection_name,

                # 配置稠密向量和稀疏向量嵌入模型
                embedding=self.__dense_embeddings,
                sparse_embedding=self.__sparse_embeddings,

                # 使用稠密向量与稀疏向量相结合的混合检索模式
                retrieval_mode=RetrievalMode.HYBRID,

                # 指定稀疏向量在 Qdrant 中的名称
                sparse_vector_name=config.SPARSE_VECTOR_NAME,
                # create_collection 已校验维度，避免 SDK 再次调用收费 API 探测。
                validate_collection_config=False,
            )

        except Exception as e:
            # 初始化集合失败时抛出异常，并保留原始异常作为错误原因
            raise RuntimeError(
                f"无法初始化 Qdrant 向量集合“{collection_name}”。"
            ) from e
