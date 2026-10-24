"""维护工具使用临时目录，绝不访问真实密钥、账户或服务器。"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from core.accounts import AccountStore, AccountError
from core.backups import BackupError, assert_runtime_stopped, create_backup, verify_backup
from core.resource_limits import UsageLedger
from manage import main, configuration


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "knowva"
        (self.root / "project").mkdir(parents=True)
        (self.root / "project" / "app.py").write_text("print('offline fixture')", encoding="utf-8")
        self.destination = Path(self.temp.name) / "backup"

    def backup(self):
        with patch("core.backups.assert_runtime_stopped"):
            return create_backup(self.root, self.destination)

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = main(["--root", str(self.root), *args])
        return result, output.getvalue(), errors.getvalue()

    def test_backup_preserves_sqlite_wal_and_private_config_excludes_runtime_and_legacy_optional(self):
        (self.root / "project" / ".env").write_text("SECRET=fixture-not-a-real-secret", encoding="utf-8")
        for directory in ["assets", ".venv", "project/__pycache__", "project/.cache", "tests", "knowledge_base", "user_data/alice"]:
            path = self.root / directory
            path.mkdir(parents=True, exist_ok=True)
            (path / "file.txt").write_text(directory, encoding="utf-8")
        (self.root / "account_data").mkdir()
        connection = sqlite3.connect(self.root / "account_data" / "accounts.sqlite3")
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE fixture (value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('committed-in-wal')")
        connection.commit()
        result = self.backup()
        self.assertTrue(result["verified"])
        self.assertEqual(result["sqlite_databases"], 1)
        archive = Path(result["archive"])
        self.assertEqual(result["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        with tarfile.open(archive) as tar:
            names = set(tar.getnames())
            self.assertIn("project/.env", names)
            self.assertIn("knowledge_base/file.txt", names)
            self.assertIn("user_data/alice/file.txt", names)
            self.assertFalse(any(name.startswith((".venv", "tests")) or "__pycache__" in name or ".cache" in name
                                 or name.endswith(("-wal", "-shm")) for name in names))
            restored = Path(self.temp.name) / "restored.sqlite3"
            restored.write_bytes(tar.extractfile("account_data/accounts.sqlite3").read())
        with contextlib.closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute("SELECT value FROM fixture").fetchone()[0], "committed-in-wal")
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
        with patch("core.backups.assert_runtime_stopped"):
            result = create_backup(self.root, Path(self.temp.name) / "no-legacy", include_legacy=False)
        with tarfile.open(result["archive"]) as tar:
            self.assertNotIn("knowledge_base/file.txt", tar.getnames())

    def test_backup_does_not_overwrite_or_write_inside_project(self):
        with self.assertRaises(BackupError):
            create_backup(self.root, self.root / "backup")
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(BackupError):
            create_backup(self.root, self.destination)
        self.assertEqual(marker.read_text(), "keep")

    def test_source_change_during_snapshot_discards_partial_backup(self):
        checks = []

        def stopped(*args, **kwargs):
            checks.append(1)
            if len(checks) == 2:
                (self.root / "project" / "app.py").write_text("changed during backup", encoding="utf-8")

        with patch("core.backups.assert_runtime_stopped", side_effect=stopped):
            with self.assertRaisesRegex(BackupError, "发生变化"):
                create_backup(self.root, self.destination)
        self.assertFalse((self.destination / "knowva-backup.tar.gz").exists())

    def test_source_links_are_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("do not archive", encoding="utf-8")
        try:
            (self.root / "project" / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("当前 Windows 会话不能创建测试符号链接")
        with patch("core.backups.assert_runtime_stopped"):
            with self.assertRaisesRegex(BackupError, "链接"):
                create_backup(self.root, self.destination)

    def test_active_systemd_and_failed_status_probe_prevent_backup(self):
        for stdout, returncode in [("active\n", 0), ("activating\n", 0), ("deactivating\n", 3), ("", 1)]:
            with self.subTest(stdout=stdout), patch("core.backups.sys.platform", "linux"), \
                    patch("core.backups.subprocess.run", return_value=subprocess.CompletedProcess([], returncode, stdout, "")):
                with self.assertRaises(BackupError):
                    assert_runtime_stopped(self.root)
        with patch("core.backups.sys.platform", "win32"), \
                patch("core.backups.socket.create_connection", return_value=contextlib.nullcontext()):
            with self.assertRaisesRegex(BackupError, "仍在监听"):
                assert_runtime_stopped(self.root)  # Windows test host skips systemctl.

    def malicious_archive(self, name="project/file.txt", payload=b"data", *, kind=None, duplicate=False,
                          sqlite_flag=False, wrong_hash=False):
        path = Path(self.temp.name) / "malicious.tar.gz"
        row = {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "sqlite": sqlite_flag}
        if wrong_hash:
            row["sha256"] = "0" * 64
        manifest = json.dumps({"format": 1, "quiesced": True, "files": [row]}).encode()
        with tarfile.open(path, "w:gz") as tar:
            metadata = tarfile.TarInfo("manifest.json")
            metadata.size = len(manifest)
            tar.addfile(metadata, io.BytesIO(manifest))
            for _ in range(2 if duplicate else 1):
                entry = tarfile.TarInfo(name)
                entry.size = len(payload)
                if kind:
                    entry.type, entry.linkname, entry.size = kind, "../../outside", 0
                tar.addfile(entry, io.BytesIO(payload) if not kind else None)
        return path

    def test_archive_verifier_rejects_traversal_links_duplicate_and_unlisted_roots(self):
        for name in ["../../outside", "/project/file.txt", "project/../outside", "project\\outside", "C:/outside", "unexpected/file.txt"]:
            with self.subTest(name=name), self.assertRaises(BackupError):
                verify_backup(self.malicious_archive(name))
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]:
            with self.subTest(kind=kind), self.assertRaises(BackupError):
                verify_backup(self.malicious_archive(kind=kind))
        with self.assertRaisesRegex(BackupError, "重复"):
            verify_backup(self.malicious_archive(duplicate=True))
        self.assertFalse((Path(self.temp.name) / "outside").exists())

    def test_verifier_checks_content_hash_and_sqlite_even_if_attacker_updates_manifest(self):
        with self.assertRaisesRegex(BackupError, "哈希"):
            verify_backup(self.malicious_archive(wrong_hash=True))
        invalid_database = b"SQLite format 3\0" + b"invalid database content"
        with self.assertRaisesRegex(BackupError, "SQLite"):
            verify_backup(self.malicious_archive(payload=invalid_database, sqlite_flag=True))
        with self.assertRaisesRegex(BackupError, "类型"):
            verify_backup(self.malicious_archive(payload=invalid_database, sqlite_flag=False))

    def test_local_admin_commands_audit_revoke_sessions_and_show_usage_without_credentials(self):
        accounts = AccountStore(self.root / "account_data" / "accounts.sqlite3")
        admin, _ = accounts.register("owner", "站长", "owner-password-123")
        member, recovery = accounts.register("alice", "小林", "member-password-123")
        token, _ = accounts.new_session(member["id"])
        ledger = UsageLedger(accounts)
        ledger.consume(member["id"], "questions", 2, 30)
        code, output, errors = self.cli("grant-admin", "owner")
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(json.loads(output)["role"], "admin")
        code, output, _ = self.cli("usage", "alice")
        self.assertEqual(json.loads(output)["questions"], 2)
        self.assertEqual(code, 0)
        code, output, _ = self.cli("users")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["total"], 2)
        for secret in ["member-password-123", "owner-password-123", recovery, token]:
            self.assertNotIn(secret, output)
        self.assertEqual(self.cli("disable-user", "alice")[0], 0)
        self.assertIsNone(accounts.user(token))
        with self.assertRaises(AccountError):
            accounts.login("alice", "member-password-123")
        self.assertEqual(self.cli("enable-user", "alice")[0], 0)
        self.assertEqual(accounts.login("alice", "member-password-123")["id"], member["id"])
        self.assertEqual(self.cli("disable-user", "owner")[0], 1)
        with accounts.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_audit").fetchone()[0], 3)

    def test_config_check_prints_booleans_only_and_rejects_official_test_keys(self):
        fixture = self.root / "project" / ".env"
        fixture.write_text("DEEPSEEK_API_KEY=private-fixture\nDASHSCOPE_API_KEY=another-private-fixture\n"
                           "TURNSTILE_SITE_KEY=1x00000000000000000000AA\nTURNSTILE_SECRET_KEY=secret-fixture\n", encoding="utf-8")
        with patch.dict("os.environ", {}, clear=True):
            result = configuration(self.root)
            self.assertTrue(result["deepseek_key_configured"])
            self.assertFalse(result["turnstile_ready"])
            code, output, _ = self.cli("check-config")
        self.assertEqual(code, 0)
        self.assertTrue(all(type(value) is bool for value in json.loads(output).values()))
        self.assertNotIn("private-fixture", output)
        self.assertNotIn("secret-fixture", output)

    def test_mistyped_root_does_not_initialize_an_empty_account_database(self):
        code, _, errors = self.cli("users")
        self.assertEqual(code, 1)
        self.assertIn("没有账号数据库", errors)
        self.assertFalse((self.root / "account_data").exists())


if __name__ == "__main__":
    unittest.main()
