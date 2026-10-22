"""通过 DeepSeek 官方搜索接口获取可引用的网页内容。"""

import re
from typing import Any
from urllib.parse import urlsplit

from openai import OpenAI
import config

NEED_WEB_SEARCH = "[NEED_WEB_SEARCH]"
UNVERIFIED_NOTICE = "以下内容基于模型知识，未能联网核实。"


class WebSearchClient:
    def search(self, query: str) -> list[dict]:
        query = query.strip()[:128]
        if not query or not config.WEB_SEARCH_ENABLED:
            return []
        base = config.DEEPSEEK_BASE_URL.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        with OpenAI(
            api_key=config.DEEPSEEK_API_KEY, base_url=base,
            timeout=config.WEB_SEARCH_TIMEOUT, max_retries=1,
        ) as client:
            data = client.post("/tools/search", cast_to=dict[str, Any], body={
                "query": query, "count": config.WEB_SEARCH_RESULT_COUNT,
                "need_content": True,
            })

        sources = []
        seen = set()
        for item in data.get("results", []):
            url = str(item.get("url") or "").strip()
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid or url in seen:
                continue
            # 摘要针对问题生成，长页面只保留有限正文，控制后续模型输入量。
            summary = str(item.get("summary") or item.get("snippet") or "")
            content = str(item.get("content") or "")[:config.WEB_SOURCE_MAX_CHARS]
            if not summary.strip() and not content.strip():
                continue
            seen.add(url)
            sources.append({
                "title": str(item.get("title") or parsed.hostname), "url": url,
                "summary": summary[:2000], "content": content,
                "date": item.get("date"), "authority": item.get("authority"),
            })
            if len(sources) >= config.WEB_SEARCH_RESULT_COUNT:
                break
        return sources


def add_verified_sources(answer: str, sources: list[dict]) -> str:
    """引用仅接受搜索实际返回的 URL，并保证最终答复附带来源。"""
    if not sources:
        return answer
    sources = list({source["url"]: source for source in sources}.values())
    allowed = {source["url"] for source in sources}
    cited = [source for source in sources if source["url"] in answer]

    def clean_link(match):
        label, url = match.groups()
        return match.group(0) if url in allowed else label

    answer = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", clean_link, answer)
    # 未使用的搜索结果无需全列；模型遗漏来源时补上前三个可核查网页。
    missing = [source for source in (cited or sources[:3])
               if f"]({source['url']})" not in answer]
    if missing:
        lines = []
        for source in missing:
            title = re.sub(r"[\[\]\r\n]", "", source["title"])
            lines.append(f"- [{title}]({source['url']})")
        answer = answer.rstrip() + "\n\n来源网站：\n" + "\n".join(lines)
    return answer


def mark_unverified(answer: str) -> str:
    """联网无结果时不能把模型生成的网址当作已检索的出处。"""
    answer = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", answer)
    answer = re.sub(r"https?://[^\s<>\]\)\u4e00-\u9fff]+", "（网址未核实）", answer)
    if UNVERIFIED_NOTICE not in answer:
        answer = UNVERIFIED_NOTICE + "\n\n" + answer
    return answer
