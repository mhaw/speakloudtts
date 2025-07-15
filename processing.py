# processing.py
import logging
from google.cloud import firestore
from extractor import extract_article
from tts import synthesize_long_text

logger = logging.getLogger(__name__)

def process_article_submission(doc_ref, url, voice):
    """
    Extracts article, synthesizes audio, and updates Firestore doc.
    Raises exceptions on failure.
    """
    item_id = doc_ref.id
    logger.info(f"Processing article for item_id: {item_id}, url: {url}")

    # 1. Extract article content
    meta = extract_article(url)
    text = meta.get("text", "")
    
    update_data = {
        "title": meta.get("title", "Untitled"),
        "author": meta.get("author", "Unknown"),
        "text": text,
        "structured_text": meta.get("structured_text", []),
        "text_preview": text[:200],
        "word_count": len(text.split()),
        "reading_time_min": max(1, len(text.split()) // 200),
        "publish_date": meta.get("publish_date", None),
        "favicon_url": meta.get("favicon_url", ""),
        "publisher": meta.get("publisher", ""),
        "section": meta.get("section", ""),
        "domain": meta.get("domain", ""),
        "extract_status": meta.get("extract_status", None),
        "error_message": meta.get("error", None)
    }
    doc_ref.update(update_data)

    if not text or meta.get("error"):
        raise ValueError(f"Article extraction failed: {meta.get('error', 'No text found.')}")

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
