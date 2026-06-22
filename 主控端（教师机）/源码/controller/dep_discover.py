"""
依赖域名自动发现：抓取目标网页 HTML，解析里面引用的外部资源域名。

用于白名单条目添加时一键展开"主域名 → 它的 CDN / API / 第三方资源域名"。

局限：
  - 只能扫到 HTML 静态标签里的资源（<script src>、<link href>、<img src>、
    <iframe src>、<source src>、<form action> 等）。
  - 抓不到 JavaScript 运行时才发起的请求（XHR/fetch、动态注入的脚本等）。
    这些必须配合浏览器 F12 抓包补全。
"""
from __future__ import annotations

import re
import logging
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("dep_discover")

_DEFAULT_TIMEOUT = 8
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# (tag_name, attr_name) 列表 —— 外部资源常出现的标签和属性
_RESOURCE_ATTRS = [
    ("script", "src"),
    ("link",   "href"),
    ("img",    "src"),
    ("iframe", "src"),
    ("source", "src"),
    ("video",  "src"),
    ("audio",  "src"),
    ("form",   "action"),
    ("a",      "href"),   # 站内导航也带上，老师可以根据需要再勾
]

# 从内联 JS / CSS 里再额外扫一遍 URL（保守正则，不求全）
_URL_RE = re.compile(r'https?://([a-zA-Z0-9][-a-zA-Z0-9.]+\.[a-zA-Z]{2,})')


def _to_registrable_domain(host: str) -> str:
    """
    把 host (e.g., 'lf-cdn-tos.bytescm.com') 收敛到通配主域 (e.g., '*.bytescm.com')。
    简单规则：取最后两段；遇到 .com.cn / .org.cn / .gov.cn / .net.cn 这类二级 TLD 取最后三段。
    """
    host = host.lower().strip(".")
    if not host or host.replace(".", "").isdigit():   # 纯 IP 跳过
        return ""
    parts = host.split(".")
    if len(parts) < 2:
        return ""
    last2 = ".".join(parts[-2:])
    if len(parts) >= 3 and parts[-2] in {"com", "org", "gov", "net", "edu"} and parts[-1] == "cn":
        return ".".join(parts[-3:])
    return last2


def _normalize_input(domain_or_url: str) -> str:
    """把 'doubao.com' / 'www.doubao.com' / 'https://www.doubao.com/' 都规整成完整 URL。"""
    s = domain_or_url.strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    return s


def discover_dependencies(domain_or_url: str,
                          timeout: int = _DEFAULT_TIMEOUT,
                          include_self: bool = True) -> tuple[list[str], str]:
    """
    抓取目标网页并提取依赖的外部域名（按主域归并，自动加 `*.` 通配前缀）。

    Returns:
      (domains, error)：
        domains —— 排序去重后的域名 patterns，例如 ['*.bytescm.com', '*.byteimg.com', ...]
        error   —— 出错时的错误消息（非空表示失败），成功时为 ""
    """
    url = _normalize_input(domain_or_url)
    if not url:
        return [], "输入为空"

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_UA},
            allow_redirects=True,
        )
    except requests.exceptions.SSLError:
        # HTTPS 证书有问题，回退到 HTTP 再试一次
        http_url = url.replace("https://", "http://", 1)
        try:
            resp = requests.get(http_url, timeout=timeout, headers={"User-Agent": _DEFAULT_UA})
        except Exception as e:
            return [], f"抓取失败: {e}"
    except Exception as e:
        return [], f"抓取失败: {e}"

    if resp.status_code >= 400:
        return [], f"HTTP {resp.status_code}"

    final_url = resp.url
    self_domain = _to_registrable_domain(urlparse(final_url).hostname or "")

    found: set[str] = set()
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        return [], f"HTML 解析失败: {e}"

    # 1. 扫各种带 src/href 的标签
    for tag, attr in _RESOURCE_ATTRS:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if not val:
                continue
            absolute = urljoin(final_url, val)
            host = urlparse(absolute).hostname
            if not host:
                continue
            reg = _to_registrable_domain(host)
            if reg:
                found.add(reg)

    # 2. 从内联 script / style 文本里再扫一遍 URL
    for tag in soup.find_all(["script", "style"]):
        text = tag.string or ""
        for match in _URL_RE.finditer(text):
            reg = _to_registrable_domain(match.group(1))
            if reg:
                found.add(reg)

    # 3. 去掉本站（除非 include_self），并加通配前缀
    result: list[str] = []
    for d in sorted(found):
        if d == self_domain and not include_self:
            continue
        result.append(f"*.{d}")

    # 同时把主域本身（不带通配）放在最前，便于精确匹配
    if self_domain and include_self:
        bare = self_domain
        # 如果列表里已经有 *.self_domain，bare 单独再加一条
        if bare not in {p.lstrip("*.") for p in result}:
            result.insert(0, bare)
        else:
            # 保证 bare 也单独在列表里
            if bare not in result:
                result.insert(0, bare)

    return result, ""
