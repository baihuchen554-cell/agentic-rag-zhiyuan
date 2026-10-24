"""可信服务器终端的维护入口；不提供远程无鉴权的管理接口。"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from core.backups import BackupError, create_backup, verify_backup


def configuration(root):
    """输出就绪状态，不输出密钥、配置内容、用户名或密码。"""
    from dotenv import dotenv_values
    values = {**dotenv_values(Path(root) / "project" / ".env", interpolate=False), **os.environ}
    site, secret = (str(values.get(name) or "").strip()
                    for name in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"))
    hostnames = [part.strip() for part in str(values.get("TURNSTILE_HOSTNAMES", "knowva.xin")).split(",") if part.strip()]
    return {
        "deepseek_key_configured": bool(str(values.get("DEEPSEEK_API_KEY") or "").strip()),
        "embedding_key_configured": bool(str(values.get("DASHSCOPE_API_KEY") or "").strip()),
        "turnstile_site_key_configured": bool(site),
        "turnstile_secret_key_configured": bool(secret),
        "turnstile_hostnames_configured": bool(hostnames),
        "turnstile_ready": bool(site and secret and hostnames and
                                not site.startswith(("1x000", "2x000", "3x000")) and
                                not secret.startswith(("1x000", "2x000", "3x000"))),
        "account_database_exists": (Path(root) / "account_data" / "accounts.sqlite3").is_file(),
    }


def _accounts(root):
    # 维护命令不在拼错路径时创建一个空账号库。
    path = Path(root) / "account_data" / "accounts.sqlite3"
    if not path.is_file():
        raise BackupError("此项目没有账号数据库。请先启动网站并注册账号，再执行账号管理。")
    from core.accounts import AccountStore
    return AccountStore(path)


def _user(accounts, username):
    with accounts.connect() as db:
        row = db.execute("SELECT id,username FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
    if row is None:
        raise BackupError("账号不存在，请先通过网站注册。")
    return dict(row)


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须为正整数。")
    return number


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("不能为负数。")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Knowva 服务器维护工具（输出不包含密码或密钥）")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="项目根目录")
    sub = parser.add_subparsers(dest="command", required=True)
    users = sub.add_parser("users", help="分页列出账号及启用状态")
    users.add_argument("--limit", type=_positive, default=50)
    users.add_argument("--offset", type=_nonnegative, default=0)
    usage = sub.add_parser("usage", help="查看某个用户当天的准入用量（北京时间）")
    usage.add_argument("username")
    for command, description in (("grant-admin", "将已注册账号设为管理员"),
                                 ("disable-user", "停用账号并撤销现有登录"),
                                 ("enable-user", "重新启用账号")):
        action = sub.add_parser(command, help=description)
        action.add_argument("username")
    sub.add_parser("check-config", help="只输出配置是否齐全，不显示配置值")
    backup = sub.add_parser("backup", help="服务停止后，将项目和数据备份到项目外的新目录")
    backup.add_argument("destination", type=Path, help="尚不存在的新目录")
    backup.add_argument("--no-legacy", action="store_true", help="不包括迁移前的共享知识库和聊天记录")
    backup.add_argument("--service", default="knowva", help="systemd 服务名称（默认 knowva）")
    backup.add_argument("--port", type=_positive, default=7860, help="实际应用监听端口（默认 7860）")
    verify = sub.add_parser("verify-backup", help="检查文件清单、哈希及 SQLite 完整性，不恢复数据")
    verify.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-config":
            result = configuration(args.root)
        elif args.command == "backup":
            result = create_backup(args.root, args.destination, include_legacy=not args.no_legacy,
                                   service=args.service, port=args.port)
        elif args.command == "verify-backup":
            result = verify_backup(args.archive)
        else:
            accounts = _accounts(args.root)
            if args.command == "users":
                result = accounts.list_users(min(args.limit, 500), args.offset)
            else:
                user = _user(accounts, args.username)
                if args.command == "usage":
                    from core.resource_limits import UsageLedger
                    result = {"username": user["username"], **UsageLedger(accounts).summary(user["id"])}
                elif args.command == "grant-admin":
                    accounts.grant_admin(user["username"])
                    result = {"username": user["username"], "role": "admin"}
                else:
                    disabled = args.command == "disable-user"
                    accounts.set_status(user["id"], disabled, actor="server-console")
                    result = {"username": user["username"], "disabled": disabled}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, OSError, sqlite3.Error) as error:
        # 系统异常可能包含用户路径，但不打印 SQL 参数、环境变量或配置内容。
        print(f"操作失败：{error}", file=sys.stderr)
        return 1
    except ValueError as error:
        # AccountError 是 ValueError，使用其面向用户的消息，不输出调用栈。
        from core.accounts import AccountError
        if isinstance(error, AccountError):
            print(f"操作失败：{error}", file=sys.stderr)
        else:
            print("操作失败：参数或配置格式不正确，请检查配置后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
