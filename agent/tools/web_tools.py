"""受限 Web 工具 — web_search + web_fetch。

复用 httpx（已是依赖），轻量 HTTP，不做浏览器/CDP。
- 结果截断 + 来源记录 + 超时保护
- NETWORK 类，LOW danger_level，受 Hook 管控
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

_MAX_FETCH_CHARS = 500_000
_DEFAULT_TIMEOUT = 15.0
_MAX_SEARCH_RESULTS = 10


def _clean_html(text: str) -> str:
    """简单 HTML 清洗：去标签 + 合并空白。"""
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def web_fetch(arguments: dict) -> dict[str, Any]:
    """抓取网页内容（HTTP GET，轻量文本提取）。

    Args:
        url (str): 目标 URL [required]
        max_chars (int): 最大返回字符数 (默认 100000)
        timeout_sec (float): 超时秒数 (默认 15)

    Returns:
        dict with content/url/status_code/truncated/source
    """
    if isinstance(arguments, dict):
        url = arguments.get("url", "")
        max_chars = arguments.get("max_chars", 100_000)
        timeout = arguments.get("timeout_sec", _DEFAULT_TIMEOUT)
    else:
        url = str(arguments)
        max_chars = 100_000
        timeout = _DEFAULT_TIMEOUT

    if not url:
        return {"success": False, "error": "缺少参数: url", "source": ""}

    # URL 校验
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"success": False, "error": f"不支持的协议: {parsed.scheme}", "source": url}
    except Exception:
        return {"success": False, "error": f"无效 URL: {url}", "source": url}

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Sinan-Embedded-Agent/0.1"})
    except httpx.TimeoutException:
        return {"success": False, "error": f"请求超时 ({timeout}s)", "source": url}
    except httpx.ConnectError:
        return {"success": False, "error": f"无法连接: {url}", "source": url}
    except Exception as exc:
        return {"success": False, "error": f"请求失败: {type(exc).__name__}: {exc}", "source": url}

    content = resp.text
    content_type = resp.headers.get("content-type", "")

    # HTML 清洗
    if "text/html" in content_type:
        content = _clean_html(content)

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + f"\n... (截断: {len(content)} -> {max_chars} chars)"

    return {
        "success": True,
        "content": content,
        "url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": content_type,
        "truncated": truncated,
        "source": str(resp.url),
        "chars": min(len(content), max_chars),
    }


def web_search(arguments: dict) -> dict[str, Any]:
    """Web 搜索（基于 DuckDuckGo HTML，轻量免 API key）。

    Args:
        query (str): 搜索关键词 [required]
        limit (int): 最大结果数 (默认 5, 最大 10)
        timeout_sec (float): 超时秒数 (默认 15)

    Returns:
        dict with results/query/count/source
    """
    if isinstance(arguments, dict):
        query = arguments.get("query", "")
        limit = min(arguments.get("limit", 5), _MAX_SEARCH_RESULTS)
        timeout = arguments.get("timeout_sec", _DEFAULT_TIMEOUT)
    else:
        query = str(arguments)
        limit = 5
        timeout = _DEFAULT_TIMEOUT

    if not query or not query.strip():
        return {"success": False, "error": "缺少参数: query", "results": [], "source": "duckduckgo"}

    search_url = "https://html.duckduckgo.com/html/"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(
                search_url,
                data={"q": query},
                headers={"User-Agent": "Sinan-Embedded-Agent/0.1"},
            )
            resp.raise_for_status()
    except httpx.TimeoutException:
        return {"success": False, "error": f"搜索超时 ({timeout}s)", "results": [], "source": "duckduckgo"}
    except httpx.ConnectError:
        return {"success": False, "error": "无法连接搜索引擎", "results": [], "source": "duckduckgo"}
    except Exception as exc:
        return {"success": False, "error": f"搜索失败: {type(exc).__name__}: {exc}",
                "results": [], "source": "duckduckgo"}

    results = _parse_ddg_results(resp.text, limit)
    return {
        "success": True,
        "query": query,
        "results": results,
        "count": len(results),
        "source": "duckduckgo",
    }


def _parse_ddg_results(html: str, limit: int) -> list[dict]:
    """解析 DuckDuckGo HTML 搜索结果。"""
    results: list[dict] = []

    # 匹配 result__a (标题 + URL) 和 result__snippet (摘要)
    link_pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    snippet_pattern = re.compile(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(links):
        if i >= limit:
            break
        snippet = _clean_html(snippets[i]) if i < len(snippets) else ""
        title_clean = _clean_html(title)
        results.append({
            "title": title_clean[:200],
            "url": href,
            "snippet": snippet[:500],
        })

    return results
