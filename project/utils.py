import os
import shutil
import pymupdf.layout
import pymupdf4llm
from pathlib import Path
import tiktoken
from functools import lru_cache


def clear_directory_contents(directory: Path) -> None:
    """清空指定目录中的所有内容，但保留目录本身，避免误删 Docker 卷或绑定挂载的根目录。"""
    directory = Path(directory)
    if not directory.is_dir():
        return

    # 遍历目录中的所有文件和子目录，并逐一删除
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


# 禁用分词器的并行处理，避免相关警告或额外的进程开销
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def pdf_to_markdown(pdf_path, output_dir):
    # 打开 PDF 文件，并将其转换为 Markdown 格式
    with pymupdf.open(pdf_path) as doc:
        md = pymupdf4llm.to_markdown(
            doc,
            header=False,
            footer=False,
            page_separators=True,
            ignore_images=True,
            write_images=False,
            image_path=None
        )

    # 清理可能存在的无效字符，确保内容可以正常写入 UTF-8 文件
    md_cleaned = md.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='ignore')

    # 使用 PDF 原文件名作为 Markdown 文件名，并写入输出目录
    output_path = Path(output_dir) / f"{Path(pdf_path).stem}.md"
    output_path.write_bytes(md_cleaned.encode('utf-8'))


@lru_cache(maxsize=1)
def _get_token_encoding():
    # 优先获取 GPT-4 对应的分词编码器，并缓存结果以避免重复加载
    try:
        return tiktoken.encoding_for_model("gpt-4")
    except Exception:
        # 如果无法获取指定模型的编码器，则尝试使用通用编码器
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            # 两种编码方式均不可用时，返回 None，后续使用字符数估算
            return None


def estimate_context_tokens(messages: list) -> int:
    # 提取消息对象中非空的文本内容
    contents = [
        str(msg.content)
        for msg in messages
        if hasattr(msg, "content") and msg.content
    ]

    # 获取分词编码器，并估算所有消息内容的 Token 总数
    encoding = _get_token_encoding()
    if encoding is None:
        # 编码器不可用时，按每 4 个字符约 1 个 Token 进行粗略估算
        return sum(max(1, len(content) // 4) for content in contents)

    # 使用分词器逐条统计 Token 数量，并累加得到总数
    return sum(len(encoding.encode(content)) for content in contents)
