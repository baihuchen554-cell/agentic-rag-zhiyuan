"""停止服务后的私有备份与离线校验；不启动、停止或部署任何服务。"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile


class BackupError(ValueError):
    pass


CODE_ROOTS = {"project", "assets", "account_data", "user_data"}
LEGACY_ROOTS = {"knowledge_base", "chat_history", "qdrant_db"}
ROOT_FILES = {"requirements.txt", "README.md", "LICENSE", ".gitignore", "CHANGELOG.md",
              "DISCLAIMER.md", "SECURITY.md", "DEPLOYMENT.md", "OPERATIONS.md", "API.md"}
EXCLUDED = {".git", ".venv", "venv", "__pycache__", ".cache", ".pytest_cache", "tests", ".workbuddy"}
MAX_FILES = 200_000
MAX_TOTAL_BYTES = 50 * 1024 ** 3


def _private(path, directory=False):
    """仅用于本函数刚创建的目录/文件，避免改动已有父目录的权限。"""
    path.chmod(0o700 if directory else 0o600)
    if os.name == "nt":
        import csv
        output = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader(io.StringIO(output.strip())))[1]
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise BackupError("无法识别当前 Windows 用户，未写入私有备份。")
        rights = "(OI)(CI)F" if directory else "F"
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{sid}:{rights}", f"*S-1-5-18:{rights}"],
                       check=True, capture_output=True)


def assert_runtime_stopped(source, *, service="knowva", port=7860):
    """拒绝正在运行的 systemd 服务、手动启动的应用和占用应用端口的进程。"""
    source = Path(source).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.service)?", service) or not 1 <= port <= 65535:
        raise BackupError("服务名称或端口无效。")
    if sys.platform.startswith("linux"):
        try:
            state = subprocess.run(["systemctl", "is-active", service], capture_output=True,
                                   text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError("无法检查 systemd 服务状态，停止备份。请在可检查服务状态的服务器执行。") from None
        status = state.stdout.strip()
        if status not in {"inactive", "failed", "unknown"} or state.returncode not in {3, 4}:
            raise BackupError(f"服务尚未确认停止，请先执行 systemctl stop {service}，确认 inactive 后重试。")
        proc = Path("/proc")
        for item in proc.iterdir():
            if not item.name.isdigit() or int(item.name) == os.getpid():
                continue
            try:
                args = (item / "cmdline").read_bytes().split(b"\0")
                text_args = [arg.decode(errors="replace") for arg in args if arg]
                app_path = str(source / "project" / "app.py")
                cwd = (item / "cwd").resolve()
                if (app_path in text_args or
                        (cwd in {source, source / "project"} and
                         any(arg in {"app.py", "project/app.py", "uvicorn"} or "uvicorn" in arg
                             for arg in text_args))):
                    raise BackupError("发现手动启动的应用，请先在其终端按 Ctrl+C，再重新备份。")
            except (OSError, PermissionError):
                continue
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.3):
                raise BackupError(f"应用端口 {port} 仍在监听，请先停止应用，再执行备份。")
        except OSError:
            pass


def _inventory(source, include_legacy):
    allowed = CODE_ROOTS | (LEGACY_ROOTS if include_legacy else set())
    result = {}

    def visit(path):
        info = path.lstat()
        # Windows 目录联接同样不能指向项目之外。
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise BackupError(f"备份范围中存在链接，请先处理：{path.relative_to(source).as_posix()}")
        if not path.resolve().is_relative_to(source):
            raise BackupError("备份路径超出项目目录。")
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                if child.name not in EXCLUDED and child.suffix not in {".pyc", ".pyo"}:
                    visit(child)
        elif stat.S_ISREG(info.st_mode):
            result[path.relative_to(source).as_posix()] = (info.st_size, info.st_mtime_ns, info.st_ino)
        else:
            raise BackupError("备份范围内含有非常规文件，请先处理。")

    for name in sorted(allowed | ROOT_FILES):
        path = source / name
        if path.exists() or path.is_symlink():
            visit(path)
    if len(result) > MAX_FILES or sum(value[0] for value in result.values()) > MAX_TOTAL_BYTES:
        raise BackupError("备份内容超过工具的安全处理范围。")
    return result


def _sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sqlite_integrity(path):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            rows = db.execute("PRAGMA integrity_check").fetchall()
        if rows != [("ok",)]:
            raise BackupError("SQLite 完整性检查未通过。")
    except sqlite3.DatabaseError:
        raise BackupError("SQLite 完整性检查未通过。") from None


def create_backup(source, destination, *, include_legacy=True, service="knowva", port=7860):
    """destination 必须是尚不存在、位于项目目录外的新目录。"""
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if not source.is_dir() or not (source / "project").is_dir():
        raise BackupError("源目录不是 Knowva 项目。")
    if destination == source or destination.is_relative_to(source):
        raise BackupError("备份目标必须位于项目目录外。")
    if destination.exists():
        raise BackupError("目标目录已经存在，请使用一个新的备份目录；不会覆盖旧备份。")
    assert_runtime_stopped(source, service=service, port=port)
    before = _inventory(source, include_legacy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    archive = destination / "knowva-backup.tar.gz"
    try:
        _private(destination, directory=True)
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=destination) as temporary:
            stage = Path(temporary)
            _private(stage, directory=True)
            manifest = {"format": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                        "quiesced": True, "legacy_included": include_legacy, "files": []}
            for relative in sorted(before):
                # WAL/SHM 由 SQLite backup API 合并，不作为独立数据恢复。
                if relative.endswith(("-wal", "-shm")):
                    continue
                original, copied = source / relative, stage / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                with original.open("rb") as handle:
                    is_sqlite = handle.read(16) == b"SQLite format 3\0"
                if is_sqlite:
                    with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as db:
                        with closing(sqlite3.connect(copied)) as target:
                            db.backup(target)
                    _sqlite_integrity(copied)
                else:
                    with original.open("rb") as handle, copied.open("xb") as target:
                        while chunk := handle.read(1024 * 1024):
                            target.write(chunk)
                manifest["files"].append({"path": relative, "bytes": copied.stat().st_size,
                                          "sha256": _sha256(copied), "sqlite": is_sqlite})
            assert_runtime_stopped(source, service=service, port=port)
            if before != _inventory(source, include_legacy):
                raise BackupError("备份期间源文件发生变化，已放弃本次备份。请确认应用完全停止。")
            (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            # 文件创建后先限制权限，再写入任何配置或用户数据。
            with archive.open("xb") as handle:
                _private(archive)
                with tarfile.open(fileobj=handle, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
                    for name in ["manifest.json"] + [row["path"] for row in manifest["files"]]:
                        path = stage / name
                        member = tarfile.TarInfo(name)
                        member.size, member.mode = path.stat().st_size, 0o600
                        with path.open("rb") as content:
                            tar.addfile(member, content)
        verified = verify_backup(archive)
        return {"archive": str(archive), "sha256": _sha256(archive), **verified}
    except BaseException:
        archive.unlink(missing_ok=True)
        # 只移除本次创建且已空的目录，不删除任何已有文件夹。
        try:
            destination.rmdir()
        except OSError:
            pass
        raise


def _safe_member(member):
    name = member.name
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or "\0" in name or path.is_absolute()
            or ".." in path.parts or path.as_posix() != name or not member.isfile()
            or member.size < 0):
        raise BackupError("压缩包包含异常路径、链接或非常规文件。")
    first = path.parts[0] if path.parts else ""
    if name != "manifest.json" and first not in CODE_ROOTS | LEGACY_ROOTS and name not in ROOT_FILES:
        raise BackupError("压缩包包含备份范围以外的条目。")


def verify_backup(archive):
    """只读取、校验压缩包；绝不直接解压到用户提供的目标目录。"""
    try:
        with tarfile.open(Path(archive), "r:gz") as tar:
            members = {}
            total = 0
            for member in tar:
                _safe_member(member)
                if member.name in members:
                    raise BackupError("压缩包包含重复条目。")
                members[member.name] = member
                total += member.size
                if len(members) > MAX_FILES + 1 or total > MAX_TOTAL_BYTES:
                    raise BackupError("压缩包超过安全校验范围。")
            metadata = members.get("manifest.json")
            if metadata is None or metadata.size > 32 * 1024 * 1024:
                raise BackupError("缺少有效备份清单。")
            manifest = json.load(tar.extractfile(metadata))
            if manifest.get("format") != 1 or manifest.get("quiesced") is not True or not isinstance(manifest.get("files"), list):
                raise BackupError("备份清单格式无效。")
            expected = {}
            for row in manifest["files"]:
                if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                        or row["path"] in expected or row["path"] == "manifest.json"
                        or type(row.get("bytes")) is not int or row["bytes"] < 0
                        or not isinstance(row.get("sha256"), str)
                        or not re.fullmatch("[a-f0-9]{64}", row["sha256"])
                        or type(row.get("sqlite")) is not bool):
                    raise BackupError("备份清单条目无效。")
                expected[row["path"]] = row
            if set(expected) != set(members) - {"manifest.json"}:
                raise BackupError("压缩包与清单中的文件不一致。")
            sqlite_count = 0
            with tempfile.TemporaryDirectory(prefix="knowva-verify-") as temporary:
                temporary = Path(temporary)
                _private(temporary, directory=True)
                for name, row in expected.items():
                    member = members[name]
                    if member.size != row["bytes"]:
                        raise BackupError("文件大小与备份清单不一致。")
                    handle, checksum = tar.extractfile(member), hashlib.sha256()
                    # 不信任清单的 sqlite 标志，实际文件头也必须一致。
                    prefix = handle.read(16)
                    actual_sqlite = prefix == b"SQLite format 3\0"
                    if actual_sqlite != row["sqlite"]:
                        raise BackupError("SQLite 文件类型与清单不一致。")
                    checksum.update(prefix)
                    sqlite_path = temporary / "database.sqlite3"
                    target = sqlite_path.open("xb") if actual_sqlite else None
                    try:
                        if target:
                            target.write(prefix)
                        while chunk := handle.read(1024 * 1024):
                            checksum.update(chunk)
                            if target:
                                target.write(chunk)
                    finally:
                        if target:
                            target.close()
                        handle.close()
                    if checksum.hexdigest() != row["sha256"]:
                        raise BackupError("文件哈希与备份清单不一致。")
                    if actual_sqlite:
                        _sqlite_integrity(sqlite_path)
                        sqlite_path.unlink()
                        sqlite_count += 1
            return {"files": len(expected), "bytes": sum(row["bytes"] for row in expected.values()),
                    "sqlite_databases": sqlite_count, "verified": True}
    except BackupError:
        raise
    except (OSError, tarfile.TarError, ValueError, TypeError, KeyError, EOFError, AttributeError):
        raise BackupError("无法读取或校验备份包；请保留原备份并检查文件是否完整。") from None
