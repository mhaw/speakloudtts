# extractor.py

import json
import logging
import requests
import trafilatura
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from newspaper import Article
from readability import Document

logger = logging.getLogger("extractor")

# Use a full Chrome UA + Accept-Language + Referer to improve pay-walled extraction
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nytimes.com/"
}


def gm(soup, name=None, prop=None):
    """Helper to grab <meta name=...> or <meta property=...> content."""
    attrs = {}
    if name:
        attrs["name"] = name
    if prop:
        attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.has_attr("content") else ""


def extract_article(url: str) -> dict:
    resp = requests.get(url, headers=FETCH_HEADERS, timeout=15)
    html = resp.text
    last_mod = resp.headers.get("Last-Modified", "")
    etag     = resp.headers.get("ETag", "")

    # 1) Try Trafilatura with looser settings
    text = trafilatura.extract(
        html,
        include_comments=True,
        favor_precision=False,
        output_format="plain"
    ) or ""
    source = "trafilatura"

    # If Trafilatura yields too little, fallback immediately
    if len(text.split()) < 50:
        # 2) Newspaper3k
        art = Article(url)
        art.download(input_html=html)
        art.parse()
        text = art.text or ""
        source = "newspaper3k"

    # Final fallback: Readability
    if len(text.split()) < 50:
        doc = Document(html)
        summary_html = doc.summary()
        text = BeautifulSoup(summary_html, "html.parser").get_text()
        source = "readability"

    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD metadata
    ld_title = ld_author = ld_date = ld_section = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:
            continue
        entries = data if isinstance(data, list) else [data]
        for e in entries:
            ld_title   = e.get("headline", ld_title)
            a = e.get("author") or {}
            if isinstance(a, dict):
                ld_author = a.get("name", ld_author)
            elif isinstance(a, list):
                ld_author = ", ".join(x.get("name", "") for x in a)
            ld_date    = e.get("datePublished", ld_date)
            ld_section = e.get("articleSection", ld_section)

    # Standard meta tags
    title     = ld_title or gm(soup, prop="og:title") or (soup.title.string if soup.title else "")
    author    = ld_author or gm(soup, name="author")
    pubdate   = ld_date or gm(soup, prop="article:published_time") or gm(soup, name="publish_date")
    keywords  = gm(soup, name="keywords")
    tags      = [t.strip() for t in keywords.split(",")] if keywords else []

    # Favicon
    icon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon = icon["href"] if icon and icon.has_attr("href") else ""
    favicon  = urljoin(url, raw_icon) if raw_icon else ""

    # Domain, publisher, section
    parsed    = urlparse(url)
    domain    = parsed.netloc
    publisher = (
        gm(soup, prop="og:site_name")
        or gm(soup, name="publisher")
        or (soup.title.string.split("–")[0].strip() if soup.title else "")
    )
    section   = ld_section or gm(soup, prop="article:section") or ""

    # Word count & read time
    wc = len(text.split())
    rt = max(1, wc // 200)

    return {
        "url": url,
        "text": text.strip(),
        "source": source,
        "last_modified": last_mod,
        "etag": etag,
        "title": title.strip(),
        "author": author.strip(),
        "publish_date": pubdate.strip(),
        "favicon_url": favicon,
        "domain": domain,
        "publisher": publisher.strip(),
        "section": section.strip(),
        "word_count": wc,
        "reading_time_min": rt,
        "tags": tags,
    }