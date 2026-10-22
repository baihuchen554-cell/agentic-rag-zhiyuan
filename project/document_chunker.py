import config
from pathlib import Path
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


class DocumentChunker:
    def __init__(self):
        # 检查父块大小配置是否合法
        if config.MIN_PARENT_SIZE <= 0 or config.MAX_PARENT_SIZE < config.MIN_PARENT_SIZE:
            raise ValueError("父块大小配置必须为正数，且 MIN_PARENT_SIZE 不能大于 MAX_PARENT_SIZE。")

        # 子块重叠长度必须小于子块大小
        if not 0 <= config.CHILD_CHUNK_OVERLAP < config.CHILD_CHUNK_SIZE:
            raise ValueError("子块重叠长度 CHILD_CHUNK_OVERLAP 必须小于子块大小 CHILD_CHUNK_SIZE。")

        # 子块重叠长度必须小于父块最大长度
        if config.CHILD_CHUNK_OVERLAP >= config.MAX_PARENT_SIZE:
            raise ValueError("子块重叠长度 CHILD_CHUNK_OVERLAP 必须小于父块最大长度 MAX_PARENT_SIZE。")

        # 按 Markdown 标题切分文档，并保留标题内容
        self.__parent_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=config.HEADERS_TO_SPLIT_ON,
            strip_headers=False
        )

        # 将父块进一步切分成子块，并设置子块之间的重叠长度
        self.__child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHILD_CHUNK_SIZE,
            chunk_overlap=config.CHILD_CHUNK_OVERLAP
        )

        # 保存父块的最小和最大长度配置
        self.__min_parent_size = config.MIN_PARENT_SIZE
        self.__max_parent_size = config.MAX_PARENT_SIZE

    @staticmethod
    def __merge_metadata(target, source, prepend=False):
        # 合并两个块的元数据，尽量保留已有信息
        for key, value in source.items():
            if key not in target:
                target[key] = value
            else:
                # prepend=True 时，将新元数据放在原元数据之前
                first, second = (value, target[key]) if prepend else (target[key], value)

                # 按路径顺序合并元数据，并去除重复项
                values = [
                    item.strip()
                    for raw in (first, second)
                    for item in str(raw).split(" -> ")
                    if item.strip()
                ]
                target[key] = " -> ".join(dict.fromkeys(values))

    def create_chunks_single(self, md_path, source_name=None):
        doc_path = Path(md_path)

        # 默认使用 Markdown 文件名加上 PDF 后缀作为来源名称
        source_name = source_name or f"{doc_path.stem}.pdf"

        # 读取 Markdown 文档，并按标题切分出初始父块
        with open(doc_path, "r", encoding="utf-8") as f:
            parent_chunks = self.__parent_splitter.split_text(f.read())

        # 合并过小的父块、拆分过大的父块，并清理剩余的小块
        merged_parents = self.__merge_small_parents(parent_chunks)
        split_parents = self.__split_large_parents(merged_parents)
        cleaned_parents = self.__clean_small_chunks(split_parents)

        # 检查最终父块是否超过最大长度
        if any(len(chunk.page_content) > self.__max_parent_size for chunk in cleaned_parents):
            raise ValueError("父块切分后仍存在超过 MAX_PARENT_SIZE 最大长度限制的块。")

        all_parent_chunks, all_child_chunks = [], []

        # 为父块分配 ID，并进一步生成子块
        self.__create_child_chunks(
            all_parent_chunks,
            all_child_chunks,
            cleaned_parents,
            doc_path,
            source_name,
        )

        return all_parent_chunks, all_child_chunks

    def __merge_small_parents(self, chunks):
        # 没有待处理的块时，直接返回空列表
        if not chunks:
            return []

        merged, current = [], None

        for chunk in chunks:
            if current is None:
                current = chunk
            else:
                # 将当前块追加到正在合并的块后面
                current.page_content += "\n\n" + chunk.page_content
                self.__merge_metadata(current.metadata, chunk.metadata)

            # 达到最小长度后保存当前父块，并开始合并下一块
            if len(current.page_content) >= self.__min_parent_size:
                merged.append(current)
                current = None

        # 处理最后剩余的块，优先合并到前一个父块
        if current:
            if merged:
                merged[-1].page_content += "\n\n" + current.page_content
                self.__merge_metadata(merged[-1].metadata, current.metadata)
            else:
                merged.append(current)

        return merged

    def __split_large_parents(self, chunks):
        # 保存处理后的父块
        split_chunks = []

        for chunk in chunks:
            # 长度未超出限制的父块直接保留
            if len(chunk.page_content) <= self.__max_parent_size:
                split_chunks.append(chunk)
            else:
                # 超长父块继续切分，防止单个父块过大
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.__max_parent_size,
                    chunk_overlap=config.CHILD_CHUNK_OVERLAP
                )
                sub_chunks = splitter.split_documents([chunk])
                split_chunks.extend(sub_chunks)

        return split_chunks

    def __rebalance_pair(self, first, second):
        # 合并相邻两个父块的文本，准备重新划分长度
        combined = first.page_content.rstrip() + "\n\n" + second.page_content.lstrip()

        # 计算切分位置的上下界，尽量保证两个块都不超过最大长度
        lower = max(1, len(combined) - self.__max_parent_size)
        upper = min(self.__max_parent_size, len(combined) - 1)

        # 总长度足够时，尽可能让两个块都达到最小长度
        if len(combined) >= 2 * self.__min_parent_size:
            lower = max(lower, self.__min_parent_size)
            upper = min(upper, len(combined) - self.__min_parent_size)

        # 优先选择文本中间附近作为切分位置
        preferred = min(max(len(combined) // 2, lower), upper)
        split_at = preferred

        # 优先在段落、换行或空格处切分，尽量避免截断句子
        for separator in ("\n\n", "\n", " "):
            before = combined.rfind(separator, lower, preferred + 1)
            after = combined.find(separator, preferred, upper + 1)

            if before >= lower:
                split_at = before
                break
            if after != -1:
                split_at = after
                break

        # 去除切分后两侧多余的空白字符
        left_text = combined[:split_at].rstrip()
        right_text = combined[split_at:].lstrip()

        # 如果切分后的某个块过小，则改用中间位置切分
        if len(combined) >= 2 * self.__min_parent_size and (
            len(left_text) < self.__min_parent_size
            or len(right_text) < self.__min_parent_size
        ):
            split_at = preferred
            left_text, right_text = combined[:split_at], combined[split_at:]

        # 任意一部分为空时，不修改原来的两个块
        if not left_text or not right_text:
            return first, second

        # 合并两个块的元数据，并将合并后的元数据分别赋给两个块
        metadata = dict(first.metadata)
        self.__merge_metadata(metadata, second.metadata)
        first.page_content, first.metadata = left_text, dict(metadata)
        second.page_content, second.metadata = right_text, dict(metadata)

        return first, second

    def __clean_small_chunks(self, chunks):
        # 清理过小的父块，并尝试与相邻块合并
        cleaned = []

        for i, chunk in enumerate(chunks):
            # 对小于最小长度的块，优先尝试与前一个块合并
            if len(chunk.page_content) < self.__min_parent_size:
                if cleaned and len(cleaned[-1].page_content) + 2 + len(chunk.page_content) <= self.__max_parent_size:
                    cleaned[-1].page_content += "\n\n" + chunk.page_content
                    self.__merge_metadata(cleaned[-1].metadata, chunk.metadata)

                # 无法与前一个块合并时，尝试合并到后一个块
                elif (
                    i < len(chunks) - 1
                    and len(chunk.page_content) + 2 + len(chunks[i + 1].page_content) <= self.__max_parent_size
                ):
                    chunks[i + 1].page_content = chunk.page_content + "\n\n" + chunks[i + 1].page_content
                    self.__merge_metadata(chunks[i + 1].metadata, chunk.metadata, prepend=True)

                # 前后都无法合并时，暂时保留该块
                else:
                    cleaned.append(chunk)
            else:
                cleaned.append(chunk)

        # 再次检查剩余的小块，并尝试与相邻块重新平衡长度
        for i, chunk in enumerate(cleaned):
            if len(chunk.page_content) >= self.__min_parent_size or len(cleaned) == 1:
                continue

            if i < len(cleaned) - 1:
                cleaned[i], cleaned[i + 1] = self.__rebalance_pair(chunk, cleaned[i + 1])
            else:
                cleaned[i - 1], cleaned[i] = self.__rebalance_pair(cleaned[i - 1], chunk)

        return cleaned

    def __create_child_chunks(self, all_parent_pairs, all_child_chunks, parent_chunks, doc_path, source_name):
        # 遍历所有父块，为每个父块生成唯一 ID，并记录来源文件
        for i, p_chunk in enumerate(parent_chunks):
            parent_id = f"{doc_path.stem}_p{i}"
            p_chunk.metadata.update({"source": source_name, "parent_id": parent_id})

            # 保存父块 ID 和文档对象，供后续存储和检索使用
            all_parent_pairs.append((parent_id, p_chunk))

            # 将父块进一步切分为更小的子块，用于向量检索
            all_child_chunks.extend(self.__child_splitter.split_documents([p_chunk]))
