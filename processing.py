# processing.py
import logging
import re
from google.cloud import firestore
from extractor import extract_article
from tts import synthesize_long_text
from gcp import db # Import the db instance

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

def sanitize_content(text: str, structured_text: list) -> tuple[str, list]:
    """
    Cleans extracted text and structured content to remove common cruft.
    Returns a tuple of (sanitized_text, sanitized_structured_text).
    """
    if not text and not structured_text:
        return "", []

    # Patterns to remove (case-insensitive)
    cruft_patterns = [
        r"share this article",
        r"share on facebook",
        r"share on twitter",
        r"share on linkedin",
        r"share on pinterest",
        r"share on whatsapp",
        r"share on email",
        r"click to share",
        r"we use cookies",
        r"cookie policy",
        r"subscribe to our newsletter",
        r"sign up for our newsletter",
        r"related stories",
        r"related articles",
        r"read more",
        r"continue reading",
        r"advertisement",
        r"supported by",
        r"follow us on",
        r"all rights reserved",
        r"reprints & permissions",
    ]
    
    # Combine patterns into a single regex
    combined_pattern = re.compile(r'\b(' + '|'.join(cruft_patterns) + r')\b', re.IGNORECASE)

    # 1. Sanitize the plain text
    sanitized_text = combined_pattern.sub('', text)
    # Normalize whitespace: remove leading/trailing whitespace from lines and reduce multiple newlines to two
    sanitized_text = '\n'.join(line.strip() for line in sanitized_text.splitlines())
    sanitized_text = re.sub(r'\n{3,}', '\n\n', sanitized_text).strip()

    # 2. Sanitize the structured text
    sanitized_structured_text = []
    for block in structured_text:
        if 'text' in block and isinstance(block['text'], str):
            original_block_text = block['text']
            # Remove cruft from the block's text
            cleaned_block_text = combined_pattern.sub('', original_block_text).strip()
            
            # Only add the block if it still has content
            if cleaned_block_text:
                block['text'] = cleaned_block_text
                sanitized_structured_text.append(block)
        elif 'items' in block and isinstance(block['items'], list):
            # For lists (ul, ol), clean each item
            cleaned_items = []
            for item in block['items']:
                cleaned_item = combined_pattern.sub('', item).strip()
                if cleaned_item:
                    cleaned_items.append(cleaned_item)
            
            if cleaned_items:
                block['items'] = cleaned_items
                sanitized_structured_text.append(block)

    logger.info(f"Sanitization complete. Text length changed from {len(text)} to {len(sanitized_text)}.")
    return sanitized_text, sanitized_structured_text


def process_article_submission(doc_ref, url, voice):
    """
    Extracts article, synthesizes audio, and updates Firestore doc.
    Handles failure logging and raises exceptions.
    """
    item_id = doc_ref.id
    user_id = doc_ref.get().to_dict().get("user_id")
    logger.info(f"Processing article for item_id: {item_id}, url: {url}")

    try:
        # 1. Extract article content
        meta = extract_article(url)
        
        # 1a. Sanitize the extracted content
        text, structured_text = sanitize_content(meta.get("text", ""), meta.get("structured_text", []))
        
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
            "used_rule_id": meta.get("used_rule_id", None)
        }
        doc_ref.update(update_data)

        if not text or meta.get("error"):
            error_msg = meta.get('error', 'No text found after sanitization.')
            raise ValueError(f"Article extraction failed: {error_msg}")

        # 2. Synthesize audio
        tts_result = synthesize_long_text(
            meta.get("title"), meta.get("author"), text, item_id, voice
        )
        if tts_result.get("error"):
            raise RuntimeError(f"TTS synthesis failed: {tts_result['error']}")

        # 3. Finalize document
        gcs_path = tts_result.get("gcs_path")
        doc_ref.update({
            "status": "done",
            "gcs_path": gcs_path,
            "processed_at": firestore.SERVER_TIMESTAMP,
            "error_message": None  # Clear previous errors
        })
        logger.info(f"Successfully processed item {item_id}")

    except ValueError as e:
        logger.error(f"Extraction failed for {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "extraction")
        raise  # Re-raise to be caught by the task handler
    except RuntimeError as e:
        logger.error(f"TTS failed for {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "tts")
        raise  # Re-raise
    except Exception as e:
        logger.error(f"An unexpected error occurred processing {item_id}: {e}", exc_info=True)
        _log_failure(item_id, user_id, url, str(e), "unknown")
        raise # Re-raise

