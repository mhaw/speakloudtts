import logging
import requests
import trafilatura
from trafilatura.settings import use_config
from newspaper import Article
from readability import Document  # from readability-lxml
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

def gm(soup, name=None, prop=None):
    attrs = {}
    if name: attrs["name"] = name
    if prop: attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.has_attr("content") else ""

def extract_article(url: str) -> dict:
    logger.info(f"📰 Attempting to extract article from URL: {url}")

    # For admin debugging:
    step_status = {
        "fetch": None,
        "trafilatura": None,
        "newspaper3k": None,
        "readability": None
    }

    new_config = use_config()
    new_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "1000")
    new_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "500")

    text, title, author, publish_date, source_lib = "", "", "", "", "unknown"
    html_content, last_modified_header, etag_header = "", "", ""
    error_context = None

    try:
        logger.debug(f"Fetching URL: {url} with headers: {FETCH_HEADERS}")
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=20)
        resp.raise_for_status()
        html_content = resp.text
        last_modified_header = resp.headers.get("Last-Modified", "")
        etag_header = resp.headers.get("ETag", "")
        logger.info(f"Fetched URL: {url} (status: {resp.status_code}, length: {len(html_content)})")
        step_status["fetch"] = "success"
    except Exception as e:
        logger.error(f"Failed to fetch URL {url}: {e}", exc_info=True)
        error_context = f"fetch_error: {str(e)}"
        step_status["fetch"] = "failed"
        return {
            "url": url, "title": "", "author": "", "text": "", "publish_date": "",
            "source": "fetch_error", "error": error_context,
            "last_modified": "", "etag": "",
            "extract_status": step_status
        }

    # 1) Trafilatura
    logger.debug(f"Trying Trafilatura for {url}")
    text_trafilatura = trafilatura.extract(
        html_content, config=new_config, include_comments=False,
        include_tables=False, deduplicate=True
    )
    if text_trafilatura and len(text_trafilatura) > 300:
        text = text_trafilatura
        source_lib = "trafilatura"
        step_status["trafilatura"] = "success"
        logger.info(f"Trafilatura OK for {url} (length: {len(text)})")
    else:
        logger.warning(f"Trafilatura insufficient (length: {len(text_trafilatura or '')}) for {url}")
        step_status["trafilatura"] = "failed"

        # 2) Newspaper3k fallback
        logger.debug(f"Trying Newspaper3k for {url}")
        try:
            art = Article(url, fetch_images=False, request_timeout=15)
            art.download(input_html=html_content)
            art.parse()
            if art.text and len(art.text) > 200:
                text = art.text
                title = art.title
                if art.authors: author = ", ".join(art.authors)
                if art.publish_date:
                    try: publish_date = art.publish_date.isoformat()
                    except Exception: publish_date = str(art.publish_date)
                source_lib = "newspaper3k"
                step_status["newspaper3k"] = "success"
                logger.info(f"Newspaper3k OK for {url} (length: {len(text)})")
            else:
                logger.warning(f"Newspaper3k insufficient (length: {len(art.text or '')}) for {url}")
                step_status["newspaper3k"] = "failed"
        except Exception as e_np3k:
            logger.error(f"Newspaper3k failed for {url}: {e_np3k}", exc_info=True)
            step_status["newspaper3k"] = f"failed: {e_np3k}"

        # 3) Readability fallback
        if not text:
            logger.debug(f"Trying Readability-LXML for {url}")
            try:
                doc = Document(html_content)
                summary_html = doc.summary()
                text_readability = BeautifulSoup(summary_html, "html.parser").get_text(separator="\n\n", strip=True)
                if text_readability and len(text_readability) > 100:
                    text = text_readability
                    if not title: title = doc.short_title()
                    source_lib = "readability"
                    step_status["readability"] = "success"
                    logger.info(f"Readability OK for {url} (length: {len(text)})")
                else:
                    logger.warning(f"Readability insufficient (length: {len(text_readability or '')}) for {url}")
                    step_status["readability"] = "failed"
            except Exception as e_read:
                logger.error(f"Readability-LXML failed for {url}: {e_read}", exc_info=True)
                step_status["readability"] = f"failed: {e_read}"

    if not text:
        logger.error(f"Extraction failed for {url} after all methods")
        error_context = "all_extractors_failed"

    # Metadata
    soup = BeautifulSoup(html_content, "html.parser")
    if not title:
        title = gm(soup, prop="og:title") or (soup.title.string if soup.title else "")
    if not author:
        author = gm(soup, name="author") or gm(soup, prop="article:author")
    if not publish_date:
        date_str_meta = gm(soup, prop="article:published_time") or gm(soup, name="publish_date") or gm(soup, name="datePublished")
        if date_str_meta:
            try:
                from dateutil import parser as date_parser
                dt_obj = date_parser.isoparse(date_str_meta)
                publish_date = dt_obj.isoformat()
            except Exception:
                pass
        else:
            # Try JSON-LD as fallback
            for script_tag in soup.find_all("script", type="application/ld+json"):
                try:
                    ld_data = json.loads(script_tag.string or "{}")
                    entries = ld_data if isinstance(ld_data, list) else [ld_data]
                    for entry in entries:
                        if entry.get("@type") in ["Article", "NewsArticle", "BlogPosting"]:
                            if not title and entry.get("headline"): title = entry.get("headline")
                            if not author and entry.get("author"):
                                auth = entry.get("author")
                                if isinstance(auth, dict) and auth.get("name"): author = auth["name"]
                                elif isinstance(auth, list) and auth: author = ", ".join(a.get("name", "") for a in auth if a.get("name"))
                                elif isinstance(auth, str): author = auth
                            if not publish_date and entry.get("datePublished"):
                                try:
                                    from dateutil import parser as date_parser
                                    dt_obj = date_parser.isoparse(entry.get("datePublished"))
                                    publish_date = dt_obj.isoformat()
                                    break
                                except Exception:
                                    pass
                        if publish_date: break
                    if publish_date: break
                except Exception:
                    pass

    icon_tag = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon_href = icon_tag["href"] if icon_tag and icon_tag.has_attr("href") else ""
    favicon_url = urljoin(url, raw_icon_href) if raw_icon_href else ""

    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    publisher = gm(soup, prop="og:site_name") or domain
    section = gm(soup, prop="article:section")

    word_count = len(text.split()) if text else 0
    reading_time_min = max(1, word_count // 200) if word_count > 0 else 0

    result = {
        "url": url,
        "title": title.strip() if title else "Untitled",
        "author": author.strip() if author else "",
        "text": text.strip() if text else "",
        "publish_date": publish_date.strip() if publish_date else "",
        "favicon_url": favicon_url,
        "domain": domain,
        "publisher": publisher,
        "section": section,
        "word_count": word_count,
        "reading_time_min": reading_time_min,
        "source": source_lib,
        "last_modified": last_modified_header,
        "etag": etag_header,
        "error": error_context,
        "extract_status": step_status  # Add for admin/troubleshooting view
    }
    logger.info(f"Extraction finished for {url}. Source: {source_lib}, Title: '{result['title']}'.")
    return result