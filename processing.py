import logging
import re
from bs4 import BeautifulSoup
from google.cloud import firestore
from extractor import extract_article
from tts import synthesize_long_text
from gcp import db
from exceptions import ExtractionError, TTSError, ProcessingError

logger = logging.getLogger(__name__)

def _log_failure(item_id, user_id, url, error_message, stage):
    """Logs a processing failure to the 'processing_failures' collection."""
    try:
        failure_ref = db.collection("processing_failures").document()
        failure_ref.set({
            "item_id": item_id,
            "user_id": user_id,
            "url": url,
            "error_message": str(error_message),
            "stage": stage,
            "failed_at": firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Logged processing failure for item {item_id} at stage {stage}.")
    except Exception as e:
        logger.error(f"Failed to log processing failure for item {item_id}: {e}", exc_info=True)

def sanitize_content(structured_text: list) -> tuple[str, list]:
    """
    Cleans structured content to remove common cruft using CSS selectors.
    Returns a tuple of (sanitized_plain_text, sanitized_structured_text).
    """
    if not structured_text:
        return "", []

    # Convert structured text to a single HTML string to be parsed
    html_string = ""
    for block in structured_text:
        if block['type'] == 'p':
            html_string += f"<p>{block['text']}</p>"
        elif block['type'].startswith('h'):
            html_string += f"<{block['type']}>{block['text']}</{block['type']}>"
        elif block['type'] == 'ul':
            html_string += "<ul>" + "".join(f"<li>{item}</li>" for item in block['items']) + "</ul>"
        elif block['type'] == 'ol':
            html_string += "<ol>" + "".join(f"<li>{item}</li>" for item in block['items']) + "</ol>"
        elif block['type'] == 'blockquote':
            html_string += f"<blockquote>{block['text']}</blockquote>"

    soup = BeautifulSoup(html_string, 'html.parser')

    # Selectors for elements to remove
    cruft_selectors = [
        ".ad", ".advertisement", ".banner", ".comments", ".cookie-banner", ".footer",
        ".header", ".nav", ".navbar", ".newsletter-signup", ".related-articles",
        ".share-buttons", ".sidebar", ".social-links", "aside", "footer", "header", "nav"
    ]
    
    for selector in cruft_selectors:
        for element in soup.select(selector):
            element.decompose()

    # Rebuild the structured text from the cleaned soup
    sanitized_structured_text = []
    for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote']):
        if tag.name == 'p':
            text = tag.get_text(strip=True)
            if text: sanitized_structured_text.append({"type": "p", "text": text})
        elif tag.name.startswith('h'):
            text = tag.get_text(strip=True)
            if text: sanitized_structured_text.append({"type": tag.name, "text": text})
        elif tag.name in ['ul', 'ol']:
            items = [li.get_text(strip=True) for li in tag.find_all('li') if li.get_text(strip=True)]
            if items: sanitized_structured_text.append({"type": tag.name, "items": items})
        elif tag.name == 'blockquote':
            text = tag.get_text(strip=True)
            if text: sanitized_structured_text.append({"type": "blockquote", "text": text})

    # Generate clean plain text from the sanitized structured text
    plain_text_parts = []
    for item in sanitized_structured_text:
        if 'text' in item:
            plain_text_parts.append(item['text'])
        elif 'items' in item:
            plain_text_parts.extend(item['items'])
    
    sanitized_plain_text = "\n\n".join(plain_text_parts)
    
    logger.info(f"Sanitization complete. New text length: {len(sanitized_plain_text)}.")
    return sanitized_plain_text, sanitized_structured_text


def process_article_submission(doc_ref, url, voice):
    """
    Extracts article, synthesizes audio, and updates Firestore doc.
    Handles failure logging and raises exceptions.
    """
    item_id = doc_ref.id
    item_data = doc_ref.get().to_dict()
    user_id = item_data.get("user_id")
    log_extra = {"item_id": item_id, "user_id": user_id, "url": url}
    logger.info(f"Processing article for item_id: {item_id}, url: {url}", extra=log_extra)

    try:
        # 1. Extract article content
        meta = extract_article(url, log_extra=log_extra)
        
        # 1a. Sanitize the extracted content
        text, structured_text = sanitize_content(meta.get("structured_text", []))
        
        update_data = {
            "title": meta.get("title", "Untitled"),
            "author": meta.get("author", "Unknown"),
            "text": text,
            "structured_text": structured_text,
            "text_preview": text[:200],
            "word_count": len(text.split()),
            "reading_time_min": max(1, len(text.split()) // 200),
            "publish_date": meta.get("publish_date", None),
            "favicon_url": meta.get("favicon_url", ""),
            "publisher": meta.get("publisher", ""),
            "section": meta.get("section", ""),
            "domain": meta.get("domain", ""),
            "extract_status": meta.get("extract_status", None),
            "error_message": meta.get("error", None),
            "used_rule_id": meta.get("used_rule_id", None),
            "canonical_url": meta.get("canonical_url", url), # Store the canonical URL
            "description": meta.get("description", ""),
            "image_url": meta.get("image_url", "")
        }
        doc_ref.update(update_data)

        if not text or meta.get("error"):
            error_msg = meta.get('error', 'No text found after sanitization.')
            raise ExtractionError(f"Article extraction failed: {error_msg}")

        # 2. Synthesize audio
        tts_result = synthesize_long_text(
            meta.get("title"), meta.get("author"), text, item_id, voice, log_extra=log_extra
        )
        if tts_result.get("error"):
            raise TTSError(f"TTS synthesis failed: {tts_result['error']}")

        # 3. Finalize document
        gcs_path = tts_result.get("gcs_path")
        doc_ref.update({
            "status": "done",
            "gcs_path": gcs_path,
            "processed_at": firestore.SERVER_TIMESTAMP,
            "error_message": None  # Clear previous errors
        })
        logger.info(f"Successfully processed item {item_id}")

    except ExtractionError as e:
        logger.error(f"Extraction failed for {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "extraction")
        raise ProcessingError(f"Extraction failed: {e}") from e
    except TTSError as e:
        logger.error(f"TTS failed for {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "tts")
        raise ProcessingError(f"TTS failed: {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred processing {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "unknown")
        raise ProcessingError(f"An unexpected error occurred: {e}") from e

