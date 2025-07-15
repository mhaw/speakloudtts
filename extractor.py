import logging
import requests
import trafilatura
from trafilatura.settings import use_config
from readability import Document
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# Configuration Constants
REQUEST_TIMEOUT = 20
MIN_READABILITY_LENGTH = 100
MIN_TRAFILATURA_CONTENT_LENGTH = 300

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

def _parse_structured_content(html_content: str) -> list:
    """Parses HTML to extract structured content (headings, paragraphs, lists)."""
    soup = BeautifulSoup(html_content, "html.parser")
    content = []
    # Supported tags for structured extraction
    allowed_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote']
    
    for tag in soup.find_all(allowed_tags):
        if tag.name == 'p':
            text = tag.get_text(strip=True)
            if text:
                content.append({"type": "p", "text": text})
        elif tag.name.startswith('h'):
            text = tag.get_text(strip=True)
            if text:
                content.append({"type": tag.name, "text": text})
        elif tag.name in ['ul', 'ol']:
            items = [li.get_text(strip=True) for li in tag.find_all('li') if li.get_text(strip=True)]
            if items:
                content.append({"type": tag.name, "items": items})
        elif tag.name == 'blockquote':
            text = tag.get_text(strip=True)
            if text:
                content.append({"type": "blockquote", "text": text})
                
    return content

def get_meta_content(soup, name=None, prop=None):
    """Extracts content from a meta tag."""
    attrs = {}
    if name: attrs["name"] = name
    if prop: attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.has_attr("content") else ""

def extract_article(url: str) -> dict:
    logger.info(f"📰 Attempting to extract article from URL: {url}")

    step_status = {"fetch": None, "readability": None, "trafilatura": None}
    text, title, author, publish_date, source_lib = "", "", "", "", "unknown"
    html_content, last_modified_header, etag_header = "", "", ""
    structured_text = []
    error_context = None
    domain = urlparse(url).netloc

    try:
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html_content = resp.text
        last_modified_header = resp.headers.get("Last-Modified", "")
        etag_header = resp.headers.get("ETag", "")
        step_status["fetch"] = "success"
    except Exception as e:
        logger.error(f"Failed to fetch URL {url} (domain: {domain}): {e}", exc_info=True)
        error_context = f"fetch_error: {str(e)}"
        step_status["fetch"] = "failed"
        return {
            "url": url, "title": "", "author": "", "text": "", "structured_text": [],
            "publish_date": "", "source": "fetch_error", "error": error_context,
            "last_modified": "", "etag": "", "extract_status": step_status
        }

    # Primary strategy: readability-lxml for structure
    logger.debug(f"Trying Readability-LXML for structured content from {url}")
    try:
        doc = Document(html_content)
        title = doc.short_title()
        summary_html = doc.summary()
        
        structured_text = _parse_structured_content(summary_html)
        
        # Generate plain text from structured content for TTS
        plain_text_parts = []
        for item in structured_text:
            if item['type'] in ['p', 'blockquote'] or item['type'].startswith('h'):
                plain_text_parts.append(item['text'])
            elif item['type'] in ['ul', 'ol']:
                plain_text_parts.extend(item['items'])
        
        text = "\n\n".join(plain_text_parts)

        if text and len(text) > MIN_READABILITY_LENGTH:
            source_lib = "readability"
            step_status["readability"] = "success"
            logger.info(f"Readability OK for {url} (length: {len(text)})")
        else:
            logger.warning(f"Readability insufficient (length: {len(text or '')}) for {url}")
            step_status["readability"] = "failed"
    except Exception as e_read:
        logger.error(f"Readability-LXML failed for {url}: {e_read}", exc_info=True)
        step_status["readability"] = f"failed: {e_read}"

    # Fallback: Trafilatura for plain text if readability fails
    if not text:
        logger.debug(f"Falling back to Trafilatura for {url}")
        new_config = use_config()
        new_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "1000")
        new_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "500")
        
        text_trafilatura = trafilatura.extract(
            html_content, config=new_config, include_comments=False,
            include_tables=False, deduplicate=True
        )
        if text_trafilatura and len(text_trafilatura) > MIN_TRAFILATURA_CONTENT_LENGTH:
            text = text_trafilatura
            source_lib = "trafilatura"
            step_status["trafilatura"] = "success"
            logger.info(f"Trafilatura fallback OK for {url} (length: {len(text)})")
            # Since trafilatura doesn't provide structure, create a simple one
            structured_text = [{"type": "p", "text": p.strip()} for p in text.split('\n') if p.strip()]
        else:
            logger.warning(f"Trafilatura fallback insufficient (length: {len(text_trafilatura or '')}) for {url}")
            step_status["trafilatura"] = "failed"

    if not text:
        logger.error(f"Extraction failed for {url} (domain: {domain}) after all methods")
        error_context = "all_extractors_failed"

    # Metadata extraction
    soup = BeautifulSoup(html_content, "html.parser")
    if not title:
        title = get_meta_content(soup, prop="og:title") or (soup.title.string if soup.title else "")
    if not author:
        author = get_meta_content(soup, name="author") or get_meta_content(soup, prop="article:author")
    if not publish_date:
        date_str_meta = get_meta_content(soup, prop="article:published_time") or get_meta_content(soup, name="publish_date") or get_meta_content(soup, name="datePublished")
        if date_str_meta:
            try:
                dt_obj = date_parser.isoparse(date_str_meta)
                publish_date = dt_obj.isoformat()
            except (date_parser.ParserError, TypeError) as e:
                logger.warning(f"Could not parse date string '{date_str_meta}': {e}")

    icon_tag = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon_href = icon_tag["href"] if icon_tag and icon_tag.has_attr("href") else ""
    favicon_url = urljoin(url, raw_icon_href) if raw_icon_href else ""
    
    publisher = get_meta_content(soup, prop="og:site_name") or domain
    section = get_meta_content(soup, prop="article:section")
    word_count = len(text.split()) if text else 0
    reading_time_min = max(1, word_count // 200) if word_count > 0 else 0

    result = {
        "url": url,
        "title": title.strip() if title else "Untitled",
        "author": author.strip() if author else "",
        "text": text.strip() if text else "",
        "structured_text": structured_text,
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
        "extract_status": step_status
    }
    logger.info(f"Extraction finished for {url}. Source: {source_lib}, Title: '{result['title']}'.")
    return result