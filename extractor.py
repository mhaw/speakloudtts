import logging
import requests
import trafilatura
import time
from trafilatura.settings import use_config
from readability import Document
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser
from newspaper import Article as NewspaperArticle
from gcp import db # Import Firestore instance

logger = logging.getLogger(__name__)

# --- Caching for rules ---
_rules_cache = None
_rules_last_fetched = None
_RULES_CACHE_TTL = 300 # 5 minutes

# Configuration Constants
REQUEST_TIMEOUT = 20
MIN_EXTRACTED_TEXT_LENGTH = 250

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

def _get_extraction_rules():
    """Fetches extraction rules from Firestore with caching."""
    global _rules_cache, _rules_last_fetched
    now = time.time()
    if _rules_cache and _rules_last_fetched and (now - _rules_last_fetched < _RULES_CACHE_TTL):
        return _rules_cache
    
    try:
        rules = []
        rules_query = db.collection("extraction_rules").stream()
        for doc in rules_query:
            rule = doc.to_dict()
            rule["id"] = doc.id
            rules.append(rule)
        _rules_cache = rules
        _rules_last_fetched = now
        logger.info(f"Fetched and cached {len(rules)} extraction rules.")
        return rules
    except Exception as e:
        logger.error(f"Could not fetch extraction rules from Firestore: {e}", exc_info=True)
        return []

def _find_matching_rule(url: str, domain: str, rules: list):
    """Finds the best matching extraction rule for a given URL."""
    for rule in rules:
        if rule["pattern_type"] == "domain" and rule["pattern"] == domain:
            return rule
    for rule in rules:
        if rule["pattern_type"] == "url_prefix" and url.startswith(rule["pattern"]):
            return rule
    return None

def _parse_structured_content(html_content: str) -> list:
    soup = BeautifulSoup(html_content, "html.parser")
    content = []
    allowed_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote']
    
    for tag in soup.find_all(allowed_tags):
        if tag.name == 'p':
            text = tag.get_text(strip=True)
            if text: content.append({"type": "p", "text": text})
        elif tag.name.startswith('h'):
            text = tag.get_text(strip=True)
            if text: content.append({"type": tag.name, "text": text})
        elif tag.name in ['ul', 'ol']:
            items = [li.get_text(strip=True) for li in tag.find_all('li') if li.get_text(strip=True)]
            if items: content.append({"type": tag.name, "items": items})
        elif tag.name == 'blockquote':
            text = tag.get_text(strip=True)
            if text: content.append({"type": "blockquote", "text": text})
    return content

def get_meta_content(soup, name=None, prop=None):
    attrs = {}
    if name: attrs["name"] = name
    if prop: attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.has_attr("content") else ""

def _validate_and_log_text(text: str, url: str, min_length: int) -> str:
    if not text or not text.strip():
        raise ValueError("Extracted text is empty or only whitespace.")
    if len(text) < min_length:
        raise ValueError(f"Extracted text is too short ({len(text)} chars), less than the minimum of {min_length}.")
    
    preview = text[:200].replace('\n', ' ')
    logger.info(f"Text preview for {url}: '{preview}...' ")
    
    replacement_char_count = text.count('\ufffd')
    if len(text) > 0:
        replacement_ratio = replacement_char_count / len(text)
        if replacement_ratio > 0.1:
            raise ValueError(f"Extracted text contains too many replacement characters ({replacement_ratio:.1%}).")
    
    text_lower = text.lower()
    if "<html>" in text_lower or "<body>" in text_lower:
        raise ValueError("Extracted text appears to be HTML, not clean text.")
    return text

def _extract_with_newspaper(html_content: str, url: str) -> dict:
    article = NewspaperArticle(url, language='en')
    article.download(input_html=html_content)
    article.parse()
    return { "text": article.text, "title": article.title, "author": ", ".join(article.authors), "structured_text": [{"type": "p", "text": p.strip()} for p in article.text.split('\n') if p.strip()] }

def _extract_with_trafilatura(html_content: str, url: str) -> dict:
    new_config = use_config()
    new_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "150")
    new_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
    text = trafilatura.extract(html_content, config=new_config, include_comments=False, include_tables=False, deduplicate=True)
    return { "text": text, "structured_text": [{"type": "p", "text": p.strip()} for p in text.split('\n') if p.strip()] }

def _extract_with_readability(html_content: str, url: str) -> dict:
    doc = Document(html_content)
    summary_html = doc.summary()
    text_parts = []
    structured_content = _parse_structured_content(summary_html)
    for item in structured_content:
        if item['type'] in ['p', 'blockquote'] or item['type'].startswith('h'):
            text_parts.append(item['text'])
        elif item['type'] in ['ul', 'ol']:
            text_parts.extend(item['items'])
    return { "text": "\n\n".join(text_parts), "title": doc.short_title(), "structured_text": structured_content }

def extract_article(url: str) -> dict:
    logger.info(f"📰 Attempting to extract article from URL: {url}")
    step_status = {"fetch": "pending", "newspaper3k": "pending", "trafilatura": "pending", "readability": "pending"}
    text, title, author, publish_date, source_lib = "", "", "", "", "unknown"
    html_content, last_modified_header, etag_header = "", "", ""
    structured_text = []
    error_context, used_rule_id = None, None
    domain = urlparse(url).netloc

    try:
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=REQUEST_TIMEOUT)
        status_code, content_type = resp.status_code, resp.headers.get("Content-Type", "unknown").lower()
        logger.info(f"Fetched {url} | Status: {status_code}, Content-Type: {content_type}")
        if status_code != 200: raise ValueError(f"Could not fetch content. Server responded with status {status_code}.")
        if 'text/html' not in content_type: raise ValueError(f"Content is not a standard HTML page (Content-Type: '{content_type}').")
        resp.raise_for_status()
        try:
            html_content = resp.content.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(f"UTF-8 decoding failed for {url}. Falling back to detected encoding.")
            html_content = resp.text
        last_modified_header, etag_header = resp.headers.get("Last-Modified", ""), resp.headers.get("ETag", "")
        step_status["fetch"] = "success"
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching {url}: {e}", exc_info=True)
        raise ValueError(f"Could not connect to the website. Please check the link.") from e
    except Exception as e:
        logger.error(f"Failed to fetch/validate {url}: {e}", exc_info=True)
        if isinstance(e, ValueError): raise
        return { "url": url, "title": "", "author": "", "text": "", "structured_text": [], "publish_date": "", "source": "fetch_error", "error": f"fetch_error: {e}", "last_modified": "", "etag": "", "extract_status": step_status, "used_rule_id": None }

    soup = BeautifulSoup(html_content, "html.parser")
    title = get_meta_content(soup, prop="og:title") or (soup.title.string if soup.title else "")
    author = get_meta_content(soup, name="author") or get_meta_content(soup, prop="article:author")
    date_str_meta = get_meta_content(soup, prop="article:published_time") or get_meta_content(soup, name="publish_date") or get_meta_content(soup, name="datePublished")
    if date_str_meta:
        try:
            publish_date = date_parser.isoparse(date_str_meta).isoformat()
        except (date_parser.ParserError, TypeError) as e:
            logger.warning(f"Could not parse date string '{date_str_meta}': {e}")
    icon_tag = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon_href = icon_tag["href"] if icon_tag and icon_tag.has_attr("href") else ""
    favicon_url = urljoin(url, raw_icon_href) if raw_icon_href else ""
    publisher = get_meta_content(soup, prop="og:site_name") or domain
    section = get_meta_content(soup, prop="article:section")

    extraction_methods = [
        ("newspaper3k", _extract_with_newspaper),
        ("trafilatura", _extract_with_trafilatura),
        ("readability-lxml", _extract_with_readability),
    ]
    
    rules = _get_extraction_rules()
    matching_rule = _find_matching_rule(url, domain, rules)
    if matching_rule:
        used_rule_id = matching_rule["id"]
        preferred = matching_rule["preferred_extractor"]
        logger.info(f"Found matching rule {used_rule_id}: Preferring '{preferred}' for {url}.")
        extraction_methods.sort(key=lambda x: x[0] != preferred)

    for name, func in extraction_methods:
        logger.debug(f"Attempting extraction with {name} for {url}")
        try:
            extracted_data = func(html_content, url)
            text = _validate_and_log_text(extracted_data.get("text", ""), url, MIN_EXTRACTED_TEXT_LENGTH)
            source_lib = name
            step_status[name] = "success"
            if extracted_data.get("title"): title = extracted_data["title"]
            if extracted_data.get("author"): author = extracted_data["author"]
            if extracted_data.get("structured_text"): structured_text = extracted_data["structured_text"]
            logger.info(f"Successfully extracted content with {name} for {url}.")
            break
        except Exception as e:
            logger.warning(f"{name} extraction failed for {url}: {e}")
            step_status[name] = f"failed: {e}"
    
    if not text:
        error_context = "all_extractors_failed"
        logger.error(f"Extraction failed for {url} after all methods.")
    
    word_count = len(text.split()) if text else 0
    reading_time_min = max(1, word_count // 200) if word_count > 0 else 0

    return {
        "url": url, "title": title.strip() if title else "Untitled", "author": author.strip() if author else "",
        "text": text.strip() if text else "", "structured_text": structured_text,
        "publish_date": publish_date.strip() if publish_date else "", "favicon_url": favicon_url,
        "domain": domain, "publisher": publisher, "section": section, "word_count": word_count,
        "reading_time_min": reading_time_min, "source": source_lib, "last_modified": last_modified_header,
        "etag": etag_header, "error": error_context, "extract_status": step_status, "used_rule_id": used_rule_id
    }