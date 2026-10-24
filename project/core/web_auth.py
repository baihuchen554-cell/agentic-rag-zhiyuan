"""读取站点级登录配置；由 Gradio 验证凭证并管理登录会话。"""

import os
from collections.abc import Mapping


def get_web_auth(environ: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    env = os.environ if environ is None else environ
    required = env.get("WEB_AUTH_REQUIRED", "false").strip().lower()
    if required not in {"true", "false"}:
        raise ValueError("WEB_AUTH_REQUIRED 只能填写 true 或 false。")

    username = env.get("WEB_AUTH_USERNAME", "").strip()
    password = env.get("WEB_AUTH_PASSWORD", "")
    if not username and not password and required == "false":
        return None
    if not username or not password.strip():
        raise ValueError("请在 project/.env 中同时填写 WEB_AUTH_USERNAME 和 WEB_AUTH_PASSWORD。")
    if len(password) < 12:
        raise ValueError("WEB_AUTH_PASSWORD 至少需要 12 个字符。")
    return username, password
