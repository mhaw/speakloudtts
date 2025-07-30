import logging
import requests
from urllib.parse import urlparse

# Mapping of domain names to specific extraction logic
DOMAIN_RULES = {
    "nytimes.com": lambda url, soup: soup.find("section", {"name": "articleBody"}),
    "defector.com": lambda url, soup: soup.find("div", {"data-testid": "article-content"}),
    "newyorker.com": lambda url, soup: soup.select_one("section[class*='body__inner-container']"),
    "washingtonpost.com": lambda url, soup: soup.find("article"),
    "bbc.com": lambda url, soup: soup.find("article"),
    "scientificamerican.com": lambda url, soup: soup.find("article"),
    "theatlantic.com": lambda url, soup: soup.find("div", {"class": "article-body"}),
}
import trafilatura
import time
import random
from tenacity import retry, stop_after_attempt, wait_exponential
from trafilatura.settings import use_config
from readability import Document
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser
from newspaper import Article as NewspaperArticle
from gcp import db # Import Firestore instance
from exceptions import ExtractionError

logger = logging.getLogger(__name__)

# --- Caching for rules ---
_rules_cache = None
_rules_last_fetched = None
_RULES_CACHE_TTL = 300 # 5 minutes

# Configuration Constants
REQUEST_TIMEOUT = 20
MIN_EXTRACTED_TEXT_LENGTH = 250

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

def _get_randomized_headers(url: str):
    """Returns a dict of headers with a random User-Agent and a dynamic Referer."""
    headers = BASE_HEADERS.copy()
    headers["User-Agent"] = random.choice(USER_AGENTS)
    
    parsed_url = urlparse(url)
    referer = f"{parsed_url.scheme}://{parsed_url.netloc}/"
    headers["Referer"] = referer
    
    return headers

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

def _clean_html(html_content: str) -> str:
    """Aggressively cleans HTML content by removing common non-article elements."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Common selectors for elements to remove
    cleaning_selectors = [
        "script", "style", "noscript", "meta", "link", "svg", "img", # Remove common non-content tags
        ".ad", ".advertisement", ".banner", ".comments", ".cookie-banner", ".footer",
        ".header", ".nav", ".navbar", ".newsletter-signup", ".related-articles",
        ".share-buttons", ".sidebar", ".social-links", ".popup", ".modal",
        "aside", "footer", "header", "nav", "form", "iframe",
        "[class*=\"ad\"], [id*=\"ad\"]", # Catch more generic ad classes/ids
        "[class*=\"cookie\"], [id*=\"cookie\"]", # Catch more generic cookie classes/ids
        "[class*=\"popup\"], [id*=\"popup\"]", # Catch more generic popup classes/ids
        "[class*=\"banner\"], [id*=\"banner\"]", # Catch more generic banner classes/ids
    ]

    for selector in cleaning_selectors:
        for element in soup.select(selector):
            element.decompose()

    return str(soup)

def _validate_and_log_text(text: str, url: str, min_length: int) -> str:
    if not text or not text.strip():
        raise ExtractionError("Extracted text is empty or only whitespace.")
    if len(text) < min_length:
        raise ExtractionError(f"Extracted text is too short ({len(text)} chars), less than the minimum of {min_length}.")
    
    preview = text[:200].replace('\n', ' ')
    logger.info(f"Text preview for {url}: '{preview}...' ", extra=log_extra)
    
    replacement_char_count = text.count('\ufffd')
    if len(text) > 0:
        replacement_ratio = replacement_char_count / len(text)
        if replacement_ratio > 0.1:
            raise ExtractionError(f"Extracted text contains too many replacement characters ({replacement_ratio:.1%}).")
    
    text_lower = text.lower()
    if "<html>" in text_lower or "<body>" in text_lower:
        raise ExtractionError("Extracted text appears to be HTML, not clean text.")
    return text

def _extract_with_newspaper(html_content: str, url: str) -> dict:
    article = NewspaperArticle(url, language='en')
    article.download(input_html=html_content)
    article.parse()
    return { "text": article.text, "title": article.title, "author": ", ".join(article.authors), "structured_text": [{"type": "p", "text": p.strip()} for p in article.text.split('\n') if p.strip()] }

def _extract_with_trafilatura(html_content: str, url: str) -> dict:
    if html_content is None:
        raise ExtractionError("No HTML content provided for trafilatura.")
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

def _extract_with_domain_specific_rules(html_content: str, url: str) -> dict | None:
    soup = BeautifulSoup(html_content, "html.parser")
    domain = urlparse(url).netloc.replace("www.", "").lower()

    text = ""
    structured_text = []
    source_lib = "domain_specific"

    extractor = DOMAIN_RULES.get(domain)

    if extractor:
        try:
            main_content = extractor(url, soup)
            if main_content is None:
                raise ExtractionError(f"Domain-specific extractor for {domain} returned None.")
            if main_content:
                paragraphs = main_content.find_all("p")
                if paragraphs:
                    text = " ".join(p.get_text().strip() for p in paragraphs)
                    structured_text = _parse_structured_content(str(main_content))
                    logger.info(f"Extracted with domain-specific rule for {domain} for {url}")
        except Exception as e:
            logger.warning(f"Domain-specific extractor failed for {domain}: {e}")

    if text:
        return {"text": text, "structured_text": structured_text, "source_lib": source_lib}
    return None

from playwright.sync_api import sync_playwright

def extract_with_playwright(url: str, soup=None) -> dict:
    logger.info(f"Attempting extraction with Playwright for {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000) # 30 seconds timeout
            html = page.content()
            if not html or not isinstance(html, str) or "<html" not in html.lower():
                raise ExtractionError("Playwright returned invalid HTML or binary data.")
            browser.close()
            
            # Use BeautifulSoup to parse the HTML and extract text/structured content
            soup = BeautifulSoup(html, "html.parser")
            text_parts = []
            structured_content = _parse_structured_content(html)
            for item in structured_content:
                if item['type'] in ['p', 'blockquote'] or item['type'].startswith('h'):
                    text_parts.append(item['text'])
                elif item['type'] in ['ul', 'ol']:
                    text_parts.extend(item['items'])
            
            title = get_meta_content(soup, prop="og:title") or (soup.title.string if soup.title else "")
            author = get_meta_content(soup, name="author") or get_meta_content(soup, prop="article:author")

            return {
                "text": "\n\n".join(text_parts),
                "title": title,
                "author": author,
                "structured_text": structured_content
            }
    except Exception as e:
        logger.error(f"Playwright extraction failed for {url}: {e}", exc_info=True)
        return {"text": "", "title": "", "author": "", "structured_text": [], "error": str(e)}

def _choose_best_extraction(results: list) -> dict:

    """
    Chooses the best extraction result based on heuristics.
    - Prioritizes extractions with both title and author, then by word count.
    - Falls back to structured content, then longest text.
    """
    if not results:
        return None

    # 1. Prioritize extractions with both title and author, then by word count
    with_title_and_author = [r for r in results if r.get("title") and r.get("author") and r.get("text")]
    if with_title_and_author:
        return max(with_title_and_author, key=lambda r: len(r.get("text", "")))

    # 2. Fallback: Prefer extractions that produced structured text
    with_structured_text = [r for r in results if r.get("structured_text")]
    if with_structured_text:
        return max(with_structured_text, key=lambda r: len(r.get("text", "")))

    # 3. Final Fallback: return the one with the longest text
    return max(results, key=lambda r: len(r.get("text", "")))

extraction_methods = [
    ("newspaper3k", _extract_with_newspaper),
    ("trafilatura", _extract_with_trafilatura),
    ("readability", _extract_with_readability),
    ("domain_specific", _extract_with_domain_specific_rules),
    ("playwright", extract_with_playwright),
]

def extract_article(url: str, log_extra: dict = None) -> dict:
    if log_extra is None:
        log_extra = {}
    logger.info(f"📰 Attempting to extract article from URL: {url}", extra=log_extra)
    step_status = {"fetch": "pending", "newspaper3k": "pending", "trafilatura": "pending", "readability": "pending"}
    html_content, last_modified_header, etag_header, canonical_url = "", "", "", ""
    error_context, used_rule_id = None, None
    domain = urlparse(url).netloc
    resp = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def _fetch_url_with_retries(current_url, current_log_extra):
        request_headers = _get_randomized_headers(current_url)
        resp = requests.get(current_url, headers=request_headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp

    try:
        resp = _fetch_url_with_retries(url, log_extra)
        status_code, content_type, content_length = resp.status_code, resp.headers.get("Content-Type", "unknown").lower(), len(resp.content)
        canonical_url = resp.url # Capture the final URL after redirects
        logger.info(f"Fetched {url} (Canonical: {canonical_url}) | Status: {status_code}, Content-Type: {content_type}, Length: {content_length} bytes", extra=log_extra)

        # Advanced Content-Type Handling
        if not content_type.startswith("text/html"):
            raise ExtractionError(f"Unsupported content type: '{content_type}'. Expected HTML.")
        if content_length < 2048:
            logger.warning(f"Response body for {url} is unusually short ({content_length} bytes).", extra=log_extra)

        html_content = resp.text
        last_modified_header, etag_header = resp.headers.get("Last-Modified", ""), resp.headers.get("ETag", "")
        step_status["fetch"] = "success"

        # Pre-extraction HTML Cleaning
        cleaned_html_content = _clean_html(html_content)
        logger.info(f"HTML cleaned. Original size: {len(html_content)} bytes, Cleaned size: {len(cleaned_html_content)} bytes", extra=log_extra)
        html_content = cleaned_html_content # Use cleaned content for extraction

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching {url}: {e}", exc_info=True, extra=log_extra)
        raise ExtractionError(f"Could not connect to the website. Please check the link.") from e
    except Exception as e:
        logger.error(f"Failed to fetch/validate {url}: {e}", exc_info=True, extra=log_extra)
        if isinstance(e, ExtractionError): raise
        return { "url": url, "title": "", "author": "", "text": "", "structured_text": [], "publish_date": "", "source": "fetch_error", "error": f"fetch_error: {e}", "last_modified": "", "etag": "", "extract_status": step_status, "used_rule_id": None, "canonical_url": url }

    soup = BeautifulSoup(html_content, "html.parser")
    title = get_meta_content(soup, prop="og:title") or (soup.title.string if soup.title else "")
    author = get_meta_content(soup, name="author") or get_meta_content(soup, prop="article:author")
    date_str_meta = get_meta_content(soup, prop="article:published_time") or get_meta_content(soup, name="publish_date") or get_meta_content(soup, name="datePublished")
    publish_date = ""
    if date_str_meta:
        try:
            publish_date = date_parser.isoparse(date_str_meta).isoformat()
        except (date_parser.ParserError, TypeError) as e:
            logger.warning(f"Could not parse date string '{date_str_meta}': {e}", extra=log_extra)
    
    icon_tag = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon_href = icon_tag["href"] if icon_tag and icon_tag.has_attr("href") else ""
    favicon_url = urljoin(url, raw_icon_href) if raw_icon_href else ""
    publisher = get_meta_content(soup, prop="og:site_name") or domain
    section = get_meta_content(soup, prop="article:section")
    description = get_meta_content(soup, name="description") or get_meta_content(soup, prop="og:description")
    image_url = get_meta_content(soup, prop="og:image") or get_meta_content(soup, name="twitter:image")

    rules = _get_extraction_rules()
    matching_rule = _find_matching_rule(url, domain, rules)
    
    extraction_methods_to_run = extraction_methods
    if matching_rule:
        used_rule_id = matching_rule["id"]
        preferred = matching_rule["preferred_extractor"]
        logger.info(f"Found matching rule {used_rule_id}: Forcing use of '{preferred}' for {url}.")
        preferred_method = next((m for m in extraction_methods if m[0] == preferred), None)
        if preferred_method:
            extraction_methods_to_run = [preferred_method]
        else:
            logger.warning(f"Rule {used_rule_id} specified an unknown extractor '{preferred}'. Falling back.")

    successful_extractions = []
    for name, func in extraction_methods_to_run:
        logger.debug(f"Attempting extraction with {name} for {url}")
        try:
            extracted_data = func(html_content, url)
            validated_text = _validate_and_log_text(extracted_data.get("text", ""), url, MIN_EXTRACTED_TEXT_LENGTH)
            extracted_data["text"] = validated_text
            extracted_data["source_lib"] = name
            successful_extractions.append(extracted_data)
            step_status[name] = "success"
            logger.info(f"Successfully extracted content with {name} for {url}.", extra=log_extra)
        except Exception as e:
            logger.warning(f"{name} extraction failed for {url}: {e}", extra=log_extra)
            step_status[name] = f"failed: {e}"

    best_extraction = _choose_best_extraction(successful_extractions)
    
    if not best_extraction:
        error_context = "all_extractors_failed"
        logger.error(f"Extraction failed for {url} after all methods.", extra=log_extra)
        text, structured_text, source_lib = "", [], "unknown"
    else:
        text = best_extraction.get("text", "")
        structured_text = best_extraction.get("structured_text", [])
        source_lib = best_extraction.get("source_lib", "unknown")
        if best_extraction.get("title"): title = best_extraction["title"]
        if best_extraction.get("author"): author = best_extraction["author"]

    word_count = len(text.split()) if text else 0
    reading_time_min = max(1, word_count // 200) if word_count > 0 else 0

    return {
        "url": url, "title": title.strip() if title else "Untitled", "author": author.strip() if author else "",
        "text": text.strip() if text else "", "structured_text": structured_text,
        "publish_date": publish_date.strip() if publish_date else "", "favicon_url": favicon_url,
        "domain": domain, "publisher": publisher, "section": section, "word_count": word_count,
        "reading_time_min": reading_time_min, "source": source_lib, "last_modified": last_modified_header,
        "etag": etag_header, "error": error_context, "extract_status": step_status, "used_rule_id": used_rule_id,
        "canonical_url": canonical_url,
        "description": description.strip() if description else "",
        "image_url": image_url.strip() if image_url else ""
    }