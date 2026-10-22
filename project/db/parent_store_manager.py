import json
import config
from utils import clear_directory_contents
from pathlib import Path
from typing import List, Dict


class ParentStoreManager:
    # 父文档存储目录路径
    __store_path: Path

    def __init__(self, store_path=None):
        # 将存储路径转换为 Path 对象，并在目录不存在时自动创建
        self.__store_path = Path(store_path or config.PARENT_STORE_PATH)
        self.__store_path.mkdir(parents=True, exist_ok=True)

    def save(self, parent_id: str, content: str, metadata: Dict) -> None:
        # 使用父文档块 ID 作为文件名，将内容和元数据保存为 JSON 文件
        file_path = self._path_for(parent_id)
        file_path.write_text(
            json.dumps(
                {
                    "page_content": content,
                    "metadata": metadata
                },
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

    def save_many(self, parents: List) -> None:
        # 批量保存父文档块，每个元素包含父文档块 ID 和文档对象
        for parent_id, doc in parents:
            self.save(parent_id, doc.page_content, doc.metadata)

    def delete_many(self, parent_ids: List[str]) -> None:
        # 根据父文档块 ID 批量删除对应的 JSON 文件
        file_paths = [self._path_for(parent_id) for parent_id in parent_ids]
        for file_path in file_paths:
            if file_path.exists():
                file_path.unlink()

    def load(self, parent_id: str) -> Dict:
        # 根据 ID 读取 JSON 文件，同时兼容传入带有 .json 后缀的文件名
        file_path = self._path_for(parent_id)
        return json.loads(file_path.read_text(encoding="utf-8"))

    def load_content(self, parent_id: str) -> Dict:
        # 读取父文档块，并整理成统一的数据结构
        try:
            data = self.load(parent_id)
        except FileNotFoundError:
            return {}
        return {
            "content": data["page_content"],
            "parent_id": parent_id,
            "metadata": data["metadata"]
        }

    def _path_for(self, parent_id: str) -> Path:
        # 工具参数来自模型，只允许本目录中的单个 JSON 文件，防止越界读写。
        if not isinstance(parent_id, str) or not parent_id or parent_id in {".", ".."}:
            raise ValueError("父文档标识无效。")
        if any(char in parent_id for char in '<>:"/\\|?*\x00'):
            raise ValueError("父文档标识不能包含路径。")
        filename = parent_id if parent_id.lower().endswith(".json") else f"{parent_id}.json"
        file_path = (self.__store_path / filename).resolve()
        if file_path.parent != self.__store_path.resolve():
            raise ValueError("父文档路径超出存储目录。")
        return file_path

    def list_sources(self) -> List[str]:
        return sorted({source for _, source in self._sources()})

    def find_ids_by_sources(self, sources: List[str]) -> List[str]:
        selected = set(sources)
        return [path.stem for path, source in self._sources() if source in selected]

    def _sources(self):
        # 单个损坏的父块不能阻止其他文档显示或删除。
        for path in self.__store_path.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            metadata = data.get("metadata") if isinstance(data, dict) else None
            source = metadata.get("source") if isinstance(metadata, dict) else None
            if isinstance(source, str) and source:
                yield path, source

    def clear_store(self) -> None:
        # 确保存储目录存在，然后清空目录中的所有内容，但保留目录本身
        self.__store_path.mkdir(parents=True, exist_ok=True)
        clear_directory_contents(self.__store_path)
