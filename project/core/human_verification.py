"""Cloudflare Turnstile：仅服务端决定是否允许账号操作。"""
import httpx

from core.accounts import AccountError


class TurnstileVerifier:
    URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    def __init__(self, site_key, secret_key, hostnames, client=None):
        self.site_key, self.secret_key = site_key, secret_key
        self.hostnames = frozenset(hostnames)
        self.client = client

    @property
    def configured(self):
        # 官方测试密钥会无条件通过；真实应用永远不接受这些密钥。
        return bool(self.site_key and self.secret_key and self.hostnames
                    and not self.site_key.startswith(("1x000", "2x000", "3x000"))
                    and not self.secret_key.startswith(("1x000", "2x000", "3x000")))

    def require_configured(self):
        if not self.configured:
            raise AccountError("人机验证服务尚未配置，暂时无法登录或注册，请联系站点维护者。", 503)

    def verify(self, token, *, ip, hostname, action, challenge_id):
        self.require_configured()
        if not token or len(token) > 2048:
            raise AccountError("请先完成人机验证。")
        if hostname not in self.hostnames:
            raise AccountError("当前域名未启用人机验证。", 403)
        try:
            payload = {"secret": self.secret_key, "response": token, "remoteip": ip}
            if self.client:
                response = self.client.post(self.URL, data=payload)
            else:
                response = httpx.post(self.URL, data=payload, timeout=10, follow_redirects=False)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise AccountError("人机验证服务暂时不可用，请稍后重试。", 503) from None
        if (not isinstance(result, dict) or result.get("success") is not True
                or result.get("hostname", "").lower() != hostname
                or result.get("action") != action or result.get("cdata") != challenge_id):
            raise AccountError("人机验证未通过或已失效，请重新验证。")
