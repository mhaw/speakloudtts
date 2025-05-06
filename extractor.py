# extractor.py
import os
import json
import logging
from urllib.parse import urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup
from newspaper import Article
from readability import Document

# reuse your USER_AGENT and headers
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/112.0.0.0 Safari/537.36"
)
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

logger = logging.getLogger("extractor")

def extract_article(url: str) -> dict:
    """
    Fetches the URL, extracts full text (via Trafilatura → newspaper → readability),
    and pulls common metadata (title, author, date, tags, favicon, etc).
    """
    sess = requests.Session()
    sess.headers.update(FETCH_HEADERS)

    resp = sess.get(url, timeout=10)
    resp.raise_for_status()
    html = resp.text

    last_mod = resp.headers.get("Last-Modified", "")
    etag     = resp.headers.get("ETag", "")

    # 1) Trafilatura
    text = trafilatura.extract(html) or ""
    source = "trafilatura"

    # 2) newspaper fallback
    if not text or len(text) < 200:
        logger.info("Trafilatura fail → newspaper3k")
        try:
            from newspaper import Article, Config
            cfg = Config()
            cfg.browser_user_agent = USER_AGENT
            cfg.request_timeout    = 15
            cfg.fetch_images       = False
            art = Article(url, config=cfg)
            art.download(); art.parse()
            text = art.text or ""
            source = "newspaper3k"
        except Exception as e:
            logger.warning("newspaper3k extraction failed: %s", e)
            text = ""

    # 3) readability fallback
    if not text or len(text) < 200:
        logger.info("newspaper3k fail → readability")
        doc = Document(html)
        summary_html = doc.summary()
        text = BeautifulSoup(summary_html, "html.parser").get_text()
        source = "readability"

    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD metadata
    ld_title = ld_author = ld_date = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
            arr  = data if isinstance(data, list) else [data]
            for e in arr:
                if e.get("@type") in ("NewsArticle","Article"):
                    ld_title  = e.get("headline","") or ld_title
                    a = e.get("author","")
                    if isinstance(a, dict):
                        ld_author = a.get("name","")
                    elif isinstance(a, list):
                        ld_author = ", ".join(x.get("name","") for x in a)
                    ld_date    = e.get("datePublished","") or ld_date
        except Exception:
            continue

    def gm(name=None, prop=None):
        sel = {"property": prop} if prop else {"name": name}
        m = soup.find("meta", attrs=sel)
        return m["content"] if m and m.has_attr("content") else ""

    title   = ld_title or gm(prop="og:title") or (soup.title.string if soup.title else "")
    author  = ld_author or gm(name="author")
    pubdate = ld_date or gm(prop="article:published_time") or gm(name="publish_date")
    keywords= gm(name="keywords")
    tags    = [t.strip() for t in keywords.split(",")] if keywords else []

    icon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon = icon["href"] if icon and icon.has_attr("href") else ""
    favicon  = urljoin(url, raw_icon) if raw_icon else ""

    # word count & read time
    wc = len(text.split())
    rt = max(1, wc // 200)

    logger.info("Extractor=%s | %r | %r | %d words", source, title, author, wc)

    return {
        "text": text,
        "url": url,
        "title": title,
        "author": author,
        "publish_date": pubdate,
        "tags": tags,
        "favicon_url": favicon,
        "word_count": wc,
        "reading_time_min": rt,
        "last_modified": last_mod,
        "etag": etag,
    }