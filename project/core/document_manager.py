from pathlib import Path
from dataclasses import dataclass
from threading import RLock
import shutil
import config
from utils import pdf_to_markdown, clear_directory_contents


@dataclass(frozen=True)
class DocumentProgress:
    stage: str
    filename: str = ""
    file_index: int = 0
    total_files: int = 0
    completed_chunks: int = 0
    total_chunks: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    issues: tuple[str, ...] = ()


class DocumentManager:

    def __init__(self, rag_system):
        # 保存 RAG 系统实例，并确保 Markdown 文档目录存在
        self.rag_system = rag_system
        self._mutation_lock = RLock()
        self.markdown_dir = Path(config.MARKDOWN_DIR)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

    def add_documents(self, document_paths, progress_callback=None):
        # 页面断开后后台任务仍会完成；同一实例的增删操作须保持互斥。
        with self._mutation_lock:
            return self._add_documents(document_paths, progress_callback)

    def _add_documents(self, document_paths, progress_callback=None):
        # 没有提供文件路径时，直接返回添加数和跳过数
        if not document_paths:
            return 0, 0

        # 统一文件路径格式，只保留 PDF 和 Markdown 文件
        document_paths = [document_paths] if isinstance(document_paths, str) else document_paths
        document_paths = [p for p in document_paths if p and Path(p).suffix.lower() in [".pdf", ".md"]]

        if not document_paths:
            return 0, 0

        added = skipped = failed = 0
        issues = []

        def report(stage, completed_chunks=0, total_chunks=0):
            if progress_callback:
                progress_callback(DocumentProgress(
                    stage=stage, filename=Path(doc_path).name,
                    file_index=i + 1, total_files=len(document_paths),
                    completed_chunks=completed_chunks, total_chunks=total_chunks,
                    added=added, skipped=skipped, failed=failed, issues=tuple(issues),
                ))

        for i, doc_path in enumerate(document_paths):
            source_path = Path(doc_path)
            doc_name = source_path.stem
            md_path = self.markdown_dir / f"{doc_name}.md"

            # 如果同名 Markdown 文件已存在，则跳过该文档
            if md_path.exists():
                skipped += 1
                report("skipped")
                continue

            parent_ids = []
            indexing_started = False
            stage = "parsing"
            try:
                report(stage)
                # Markdown 文件直接复制；PDF 文件转换为 Markdown
                if source_path.suffix.lower() == ".md":
                    shutil.copy(source_path, md_path)
                else:
                    pdf_to_markdown(source_path, self.markdown_dir)

                # 将 Markdown 文档切分为父块和子块
                stage = "chunking"
                report(stage)
                parent_chunks, child_chunks = self.rag_system.chunker.create_chunks_single(
                    md_path,
                    source_name=source_path.name,
                )

                if not child_chunks:
                    raise ValueError("未生成任何子块。")

                # 保存父块，并将子块添加到向量数据库
                parent_ids = [parent_id for parent_id, _ in parent_chunks]
                self.rag_system.parent_store.save_many(parent_chunks)
                collection = self.rag_system.vector_db.get_collection(
                    self.rag_system.collection_name
                )
                # 每批完成向量计算和写入后才更新计数，不用文件序号冒充进度。
                stage = "indexing"
                total_chunks = len(child_chunks)
                report(stage, 0, total_chunks)
                batch_size = max(1, config.EMBEDDING_BATCH_SIZE)
                indexing_started = True
                for start in range(0, total_chunks, batch_size):
                    batch = child_chunks[start:start + batch_size]
                    collection.add_documents(batch, batch_size=batch_size)
                    report(stage, start + len(batch), total_chunks)

                added += 1
                report("file_done", total_chunks, total_chunks)

            except Exception as e:
                # 分批写入失败时先回滚已写入的向量，避免重试留下残缺索引。
                try:
                    if indexing_started:
                        self.rag_system.vector_db.delete_sources(
                            self.rag_system.collection_name, [source_path.name]
                        )
                    self.rag_system.parent_store.delete_many(parent_ids)
                    md_path.unlink(missing_ok=True)
                    reason = ("向量处理未完成，请检查接口后重试" if stage == "indexing"
                              else "文档处理失败，请检查文件后重试")
                except Exception as cleanup_error:
                    # 回滚失败时保留来源和父块，使页面仍能选中并删除残留数据。
                    reason = "清理未完成，请在文档列表删除该文件后重试"
                    print(f"清理文件 {source_path.name} 时发生错误：{cleanup_error}")
                print(f"处理文件 {doc_path} 时发生错误：{e}")
                failed += 1
                issues.append(f"{source_path.name}：{reason}")
                report("failed")

        report("complete")
        # 保留原有二元返回值；进度事件单独区分重复文件与处理失败。
        return added, skipped + failed

    def get_markdown_files(self):
        # 优先获取父文档存储中记录的文档来源
        sources = self.rag_system.parent_store.list_sources()
        if sources:
            return sources

        # 如果没有来源记录，则读取 Markdown 目录中的文件名
        return sorted(p.name for p in self.markdown_dir.glob("*.md"))

    def delete_documents(self, sources):
        with self._mutation_lock:
            return self._delete_documents(sources)

    def _delete_documents(self, sources):
        sources = sorted(set(sources or []))
        if not sources:
            return 0
        known = set(self.get_markdown_files())
        if not set(sources).issubset(known):
            raise ValueError("所选文档已不存在，请刷新列表后重试。")

        markdown_paths = []
        root = self.markdown_dir.resolve()
        for source in sources:
            if "/" in source or "\\" in source or Path(source).name != source:
                raise ValueError("文档名称无效。")
            path = (root / f"{Path(source).stem}.md").resolve()
            if path.parent != root:
                raise ValueError("文档路径无效。")
            markdown_paths.append(path)
        parent_ids = self.rag_system.parent_store.find_ids_by_sources(sources)

        # 向量删除失败时保留文档和父块，便于重试，不产生失去来源的索引。
        self.rag_system.vector_db.delete_sources(self.rag_system.collection_name, sources)
        self.rag_system.parent_store.delete_many(parent_ids)
        for path in markdown_paths:
            path.unlink(missing_ok=True)
        return len(sources)

    def clear_all(self):
        with self._mutation_lock:
            self._clear_all()

    def _clear_all(self):
        # 清空前确保 Markdown 文档目录存在
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        # 删除当前向量集合
        self.rag_system.vector_db.delete_collection(self.rag_system.collection_name)

        # 清空 Markdown 文件和父文档存储
        clear_directory_contents(self.markdown_dir)
        self.rag_system.parent_store.clear_store()

        # 重新创建向量集合，供后续文档添加使用
        self.rag_system.vector_db.create_collection(self.rag_system.collection_name)
