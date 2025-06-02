# rss.py
import logging
import os
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator #
from google.cloud import firestore
from google.cloud import storage
from dateutil import parser as date_parser # For robust date parsing

logger = logging.getLogger(__name__) #

# Ensure clients are initialized (similar to tts.py, ideally passed or from app context)
DB_CLIENT_INSTANCE = None
STORAGE_CLIENT_INSTANCE = None

def _get_db_client():
    global DB_CLIENT_INSTANCE
    if DB_CLIENT_INSTANCE is None:
        try:
            DB_CLIENT_INSTANCE = firestore.Client()
            logger.info("Initialized FirestoreClient in rss.py")
        except Exception as e:
            logger.critical(f"rss.py: Failed to initialize FirestoreClient: {e}", exc_info=True)
            raise
    return DB_CLIENT_INSTANCE

def _get_storage_client():
    global STORAGE_CLIENT_INSTANCE
    if STORAGE_CLIENT_INSTANCE is None:
        try:
            STORAGE_CLIENT_INSTANCE = storage.Client()
            logger.info("Initialized StorageClient in rss.py")
        except Exception as e:
            logger.critical(f"rss.py: Failed to initialize StorageClient: {e}", exc_info=True)
            raise
    return STORAGE_CLIENT_INSTANCE


def generate_feed(app_url_root: str, bucket_name: str = None) -> str: # name changed from request_url_root for clarity
    logger.info(f"Attempting to generate RSS feed. App base URL: {app_url_root}")

    try:
        db = _get_db_client()
        storage_client = _get_storage_client()
    except Exception as e:
        logger.error(f"RSS: Cannot generate feed due to GCP client initialization failure: {str(e)}")
        # Fallback to a simple error feed or raise
        fg_error = FeedGenerator()
        fg_error.title("Feed Generation Error")
        fg_error.link(href=app_url_root, rel="alternate")
        fg_error.description(f"Could not generate feed: {str(e)}")
        return fg_error.rss_str(pretty=True)

    if not bucket_name:
        bucket_name = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files") #
    
    if not bucket_name:
        logger.error("RSS: GCS_BUCKET_NAME not configured. Cannot determine audio URLs accurately.")
        # Decide on behavior: error feed or proceed with potentially broken links
        return "<error>GCS Bucket Name not configured</error>"
        
    logger.debug(f"RSS: Using GCS bucket: {bucket_name}")
    bucket = storage_client.bucket(bucket_name) #

    # 1) Fetch all 'done' items, ordered by publish_date (most recent first)
    # Ensure publish_date is consistently stored in a parsable format (ISO string recommended)
    logger.info("RSS: Fetching 'done' items from Firestore for feed.")
    docs_query = db.collection("items") \
        .where("status", "==", "done") \
        .where("audio_url", "!=", None) \
        .order_by("publish_date", direction=firestore.Query.DESCENDING) \
        .limit(100)  # Sensible limit for a feed

    items_for_feed = []
    raw_items_count = 0
    parse_errors_count = 0

    for doc in docs_query.stream():
        raw_items_count += 1
        data = doc.to_dict() #
        item_id = data.get("id", f"unknown_item_{raw_items_count}")
        logger.debug(f"RSS: Processing item '{item_id}' (Title: '{data.get('title', 'N/A')}') for feed inclusion.")

        raw_date_str = data.get("publish_date", "") #
        publish_datetime_utc = None

        if isinstance(raw_date_str, datetime): # Already a datetime object
            publish_datetime_utc = raw_date_str
            if publish_datetime_utc.tzinfo is None: # If naive, assume UTC
                publish_datetime_utc = publish_datetime_utc.replace(tzinfo=timezone.utc)
        elif isinstance(raw_date_str, str) and raw_date_str:
            try:
                # Use dateutil.parser for robust parsing of various date string formats
                parsed_dt = date_parser.parse(raw_date_str) #
                if parsed_dt.tzinfo is None: # If naive, assume UTC
                    publish_datetime_utc = parsed_dt.replace(tzinfo=timezone.utc) #
                else: # Convert to UTC if it has timezone info
                    publish_datetime_utc = parsed_dt.astimezone(timezone.utc)
                logger.debug(f"RSS: Parsed publish_date '{raw_date_str}' to '{publish_datetime_utc}' for item {item_id}.")
            except (ValueError, TypeError) as e_date:
                logger.warning(f"RSS: Could not parse publish_date '{raw_date_str}' for item '{item_id}': {e_date}. Using current time as fallback.")
                publish_datetime_utc = datetime.now(timezone.utc) #
                parse_errors_count += 1
        else:
            logger.warning(f"RSS: Missing or invalid publish_date for item '{item_id}'. Using current time as fallback.")
            publish_datetime_utc = datetime.now(timezone.utc)
            parse_errors_count += 1
        
        data["publish_datetime_utc"] = publish_datetime_utc # Store the datetime object
        items_for_feed.append(data)

    logger.info(f"RSS: Retrieved {raw_items_count} raw items. Prepared {len(items_for_feed)} items for feed. Date parsing issues for {parse_errors_count} items.")

    # Items are already sorted by Firestore query (publish_date descending)

    # 4) Build the feed
    fg = FeedGenerator() #
    fg.title("SpeakLoudTTS Audio Articles")
    # Use app_url_root for links. Ensure it ends with a '/' if needed by urljoin.
    feed_link = app_url_root.rstrip('/') + '/'
    fg.link(href=feed_link, rel="alternate")
    fg.description("Listen to web articles converted to audio by SpeakLoudTTS.")
    fg.language("en") # Assuming English, make configurable if needed
    # fg.logo(f"{feed_link}static/logo.png") # Optional: if you have a logo

    for item_data in items_for_feed:
        item_id = item_data.get("id", "unknown")
        logger.debug(f"RSS: Adding item '{item_id}' (Title: '{item_data.get('title')}') to feed.")
        fe = fg.add_entry() #
        fe.id(f"{feed_link}items/{item_id}") # Unique ID for the entry
        fe.title(item_data.get("title", "Untitled Audio Article"))
        fe.link(href=f"{feed_link}items/{item_id}", rel="alternate") # Link to item detail page
        
        description = f"Audio version of the article: {item_data.get('title', '')}. "
        if item_data.get("author"): description += f"By {item_data.get('author')}. "
        if item_data.get("url"): description += f"Original article: {item_data.get('url')}"
        fe.description(description)
        
        fe.pubDate(item_data["publish_datetime_utc"]) # Expects a timezone-aware datetime
        if item_data.get("author"): fe.author(name=item_data.get("author"))

        audio_url = item_data.get("audio_url")
        if audio_url:
            # Look up the real MP3 size in bytes so length is accurate
            gcs_path = item_data.get("gcs_path", f"{item_id}.mp3") # Use gcs_path if stored
            blob = bucket.get_blob(gcs_path) #
            length_bytes = "0"
            if blob and blob.size is not None: #
                length_bytes = str(blob.size) #
                logger.debug(f"RSS: Found blob size {length_bytes} bytes for item '{item_id}' (gs://{bucket_name}/{gcs_path}).")
            else:
                logger.warning(f"RSS: Could not get blob or size for item '{item_id}' (gs://{bucket_name}/{gcs_path}). Using length 0.")
            
            # Proper enclosure() call sets url, length & MIME type
            fe.enclosure(url=audio_url, length=length_bytes, type="audio/mpeg")
        else:
            logger.warning(f"RSS: Item '{item_id}' is 'done' but has no audio_url. Skipping enclosure.")

    # 5) Return clean UTF-8 string
    rss_xml_string = fg.rss_str(pretty=True) #
    logger.info(f"RSS feed generated successfully. Final XML length: {len(rss_xml_string)} bytes.")
    return rss_xml_string