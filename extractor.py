# extractor.py
import logging
import requests
import trafilatura
from trafilatura.settings import use_config
from newspaper import Article
from readability import Document # from readability-lxml
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Use a full Chrome UA + Accept-Language + Referer to improve pay-walled extraction
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

# Helper to grab <meta name=...> or <meta property=...> content.
def gm(soup, name=None, prop=None): #
    attrs = {}
    if name: attrs["name"] = name #
    if prop: attrs["property"] = prop #
    tag = soup.find("meta", attrs=attrs) #
    return tag["content"].strip() if tag and tag.has_attr("content") else "" #


def extract_article(url: str) -> dict:
    logger.info(f"Attempting to extract article from URL: {url}")
    
    # Configure Trafilatura to be less aggressive initially (as per original logic)
    new_config = use_config()
    new_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "1000") # Original was 2000
    new_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "500")    # Original was 1000

    text = ""
    title = ""
    author = ""
    publish_date = "" # Standardize to ISO format string if possible
    source_lib = "unknown"
    
    html_content = ""
    last_modified_header = ""
    etag_header = ""

    try:
        logger.debug(f"Fetching URL: {url} with headers: {FETCH_HEADERS}")
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=20) # Increased timeout slightly
        resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        html_content = resp.text
        last_modified_header = resp.headers.get("Last-Modified", "") #
        etag_header = resp.headers.get("ETag", "") #
        logger.info(f"Successfully fetched URL: {url}. Status: {resp.status_code}. Content length: {len(html_content)}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch URL {url}: {e}", exc_info=True)
        # Return a dictionary with an error or raise the exception,
        # depending on how the calling code should handle fetch failures.
        return {
            "url": url, "title": "", "author": "", "text": "", "publish_date": "",
            "source": "fetch_error", "error": str(e), 
            "last_modified": "", "etag": ""
        }

    # 1) Try Trafilatura
    logger.debug(f"Attempting extraction with Trafilatura for URL: {url}")
    # The `include_comments=False, include_tables=False` are common defaults for cleaner text.
    # `deduplicate=True` can help remove boilerplate repeated text.
    text_trafilatura = trafilatura.extract(
        html_content, config=new_config, include_comments=False, 
        include_tables=False, deduplicate=True
    ) #
    if text_trafilatura and len(text_trafilatura) > 300: # Check for some minimal reasonable length
        text = text_trafilatura
        source_lib = "trafilatura"
        logger.info(f"Successfully extracted text with Trafilatura for URL: {url}. Length: {len(text)}")
    else:
        logger.warning(f"Trafilatura extracted insufficient text (length: {len(text_trafilatura or '')}) for URL: {url}. Falling back.")

        # 2) Fallback to Newspaper3k if Trafilatura fails
        logger.debug(f"Attempting extraction with Newspaper3k for URL: {url}")
        try:
            art = Article(url, fetch_images=False, request_timeout=15) #
            art.download(input_html=html_content) #
            art.parse() #
            if art.text and len(art.text) > 200:
                text = art.text
                title = art.title
                # Newspaper3k often gets authors if available
                if art.authors: author = ", ".join(art.authors)
                # Newspaper3k can also get publish date
                if art.publish_date: # This is a datetime object
                    try:
                        publish_date = art.publish_date.isoformat()
                    except AttributeError: # if art.publish_date is not a datetime object
                        logger.warning(f"Newspaper3k publish_date for {url} is not a datetime object: {art.publish_date}")
                        publish_date = str(art.publish_date) if art.publish_date else ""

                source_lib = "newspaper3k"
                logger.info(f"Successfully extracted text with Newspaper3k for URL: {url}. Length: {len(text)}")
            else:
                logger.warning(f"Newspaper3k extracted insufficient text (length: {len(art.text or '')}) for URL: {url}. Falling back.")
        except Exception as e_np3k:
            logger.error(f"Newspaper3k failed for URL {url}: {e_np3k}", exc_info=True)

        # 3) Final fallback: Readability if Newspaper3k also fails
        if not text:
            logger.debug(f"Attempting extraction with Readability-LXML for URL: {url}")
            try:
                doc = Document(html_content) #
                summary_html = doc.summary() #
                # Use BeautifulSoup to get clean text from readability's HTML summary
                text_readability = BeautifulSoup(summary_html, "html.parser").get_text(separator="\n\n", strip=True) #
                if text_readability and len(text_readability) > 100:
                    text = text_readability
                    if not title: title = doc.short_title() # Readability provides a title
                    source_lib = "readability"
                    logger.info(f"Successfully extracted text with Readability-LXML for URL: {url}. Length: {len(text)}")
                else:
                    logger.warning(f"Readability-LXML extracted insufficient text (length: {len(text_readability or '')}) for URL: {url}.")
            except Exception as e_read:
                logger.error(f"Readability-LXML failed for URL {url}: {e_read}", exc_info=True)

    # If still no text after all attempts, log it.
    if not text:
        logger.error(f"All extraction methods failed to yield substantial text for URL: {url}")
        # It might be useful to store the raw HTML for later analysis in such cases.
        # For now, text remains empty.

    # Metadata extraction using BeautifulSoup (can supplement or override previous)
    logger.debug(f"Parsing HTML with BeautifulSoup for metadata for URL: {url}")
    soup = BeautifulSoup(html_content, "html.parser") #

    # Attempt to get title if not already found by Newspaper3k or Readability
    if not title:
        title = gm(soup, prop="og:title") or (soup.title.string if soup.title else "") #
        if title: logger.debug(f"Title found via meta/title tag: '{title}'")
        else: logger.warning(f"Could not determine title for URL: {url}")
    
    # Attempt to get author if not already found
    if not author:
        author = gm(soup, name="author") or gm(soup, prop="article:author") #
        if author: logger.debug(f"Author found via meta tag: '{author}'")

    # Attempt to get publish date if not already found
    # Standardize to ISO format string (YYYY-MM-DDTHH:MM:SSZ or similar)
    if not publish_date:
        date_str_meta = gm(soup, prop="article:published_time") or \
                        gm(soup, name="publish_date") or \
                        gm(soup, name="datePublished") # Common in JSON-LD via meta
        if date_str_meta:
            try:
                # Use dateutil for robust parsing
                from dateutil import parser as date_parser
                dt_obj = date_parser.isoparse(date_str_meta) # Stricter ISO parsing
                # If it might not have timezone, assume UTC or make it aware
                if dt_obj.tzinfo is None:
                     # from dateutil.tz import tzutc
                     # dt_obj = dt_obj.replace(tzinfo=tzutc())
                     logger.debug(f"Parsed date '{date_str_meta}' as naive datetime. Consider timezone handling.")
                publish_date = dt_obj.isoformat()
                logger.debug(f"Publish date found via meta tag: '{publish_date}' from '{date_str_meta}'")
            except ValueError:
                logger.warning(f"Could not parse date string '{date_str_meta}' from meta tags for URL: {url}")
        else: # Try JSON-LD parsing more thoroughly
            logger.debug(f"No standard date meta tags, trying JSON-LD script tags for URL: {url}")
            for script_tag in soup.find_all("script", type="application/ld+json"):
                try:
                    ld_data = json.loads(script_tag.string or "{}") #
                    entries = ld_data if isinstance(ld_data, list) else [ld_data] #
                    for entry in entries:
                        if entry.get("@type") in ["Article", "NewsArticle", "BlogPosting"]:
                            if not title and entry.get("headline"): title = entry.get("headline") #
                            if not author and entry.get("author"):
                                ld_author_obj = entry.get("author") #
                                if isinstance(ld_author_obj, dict) and ld_author_obj.get("name"):
                                    author = ld_author_obj.get("name") #
                                elif isinstance(ld_author_obj, list) and ld_author_obj:
                                     author = ", ".join(a.get("name", "") for a in ld_author_obj if a.get("name")) #
                                elif isinstance(ld_author_obj, str):
                                     author = ld_author_obj
                            if not publish_date and entry.get("datePublished"): #
                                ld_date_str = entry.get("datePublished")
                                try:
                                    from dateutil import parser as date_parser
                                    dt_obj = date_parser.isoparse(ld_date_str)
                                    if dt_obj.tzinfo is None: logger.debug(f"Parsed JSON-LD date '{ld_date_str}' as naive.")
                                    publish_date = dt_obj.isoformat()
                                    logger.debug(f"Publish date found via JSON-LD: '{publish_date}'")
                                    break # Found date, stop searching this entry
                                except ValueError:
                                     logger.warning(f"Could not parse date string '{ld_date_str}' from JSON-LD for URL: {url}")
                        if publish_date: break # Found date in some entry, stop searching scripts
                    if publish_date: break
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse JSON-LD content for URL: {url}", exc_info=False) # Keep log cleaner
                except Exception as e_jsonld:
                    logger.warning(f"Error processing JSON-LD for URL {url}: {e_jsonld}", exc_info=False)


    # Favicon
    icon_tag = soup.find("link", rel=lambda x: x and "icon" in x.lower()) #
    raw_icon_href = icon_tag["href"] if icon_tag and icon_tag.has_attr("href") else "" #
    favicon_url = urljoin(url, raw_icon_href) if raw_icon_href else "" #
    if favicon_url: logger.debug(f"Favicon URL determined: {favicon_url}")

    parsed_url = urlparse(url) #
    domain = parsed_url.netloc #
    
    # Publisher (from <meta property="og:site_name"> or domain as fallback)
    publisher = gm(soup, prop="og:site_name") or domain 
    if publisher: logger.debug(f"Publisher determined: {publisher}")

    # Section
    section = gm(soup, prop="article:section")
    if section: logger.debug(f"Section determined: {section}")

    word_count = len(text.split()) if text else 0 #
    reading_time_min = max(1, word_count // 200) if word_count > 0 else 0 #
    logger.debug(f"Word count: {word_count}, Estimated reading time: {reading_time_min} min for URL: {url}")

    result = {
        "url": url,
        "title": title.strip() if title else "Untitled",
        "author": author.strip() if author else "",
        "text": text.strip() if text else "",
        "publish_date": publish_date.strip() if publish_date else "", # ISO format string
        "favicon_url": favicon_url,
        "domain": domain,
        "publisher": publisher,
        "section": section,
        "word_count": word_count,
        "reading_time_min": reading_time_min,
        "source": source_lib, # Which library successfully extracted main text
        "last_modified": last_modified_header,
        "etag": etag_header,
        "error": None # Explicitly None if no fetch error
    }
    logger.info(f"Extraction completed for URL: {url}. Final source: '{source_lib}', Title: '{result['title']}'.")
    return result