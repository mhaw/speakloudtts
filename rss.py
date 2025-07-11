# rss.py
import logging
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

def generate_feed(db_client, storage_client, app_config: dict) -> str:
    """
    Generates an RSS feed from 'done' items in Firestore.

    Args:
        db_client: An initialized Firestore client instance.
        storage_client: An initialized Cloud Storage client instance.
        app_config (dict): A dictionary containing application configuration.
                           Expected keys: 'APP_URL_ROOT', 'GCS_BUCKET_NAME'.

    Returns:
        A string containing the RSS feed in XML format.
    """
    app_url_root = app_config.get("APP_URL_ROOT")
    bucket_name = app_config.get("GCS_BUCKET_NAME")

    logger.info(f"Attempting to generate RSS feed. App base URL: {app_url_root}")

    fg_error = FeedGenerator()
    fg_error.title("Feed Generation Error")
    fg_error.link(href=app_url_root or "#", rel="alternate")

    if not all([db_client, storage_client, app_url_root, bucket_name]):
        error_msg = "RSS feed generation is misconfigured (missing clients or config)."
        logger.critical(error_msg)
        fg_error.description(error_msg)
        return fg_error.rss_str(pretty=True)

    try:
        bucket = storage_client.bucket(bucket_name)
    except Exception as e:
        logger.error(f"RSS: Failed to access GCS bucket '{bucket_name}': {e}", exc_info=True)
        fg_error.description(f"Could not access GCS bucket: {e}")
        return fg_error.rss_str(pretty=True)

    logger.debug(f"RSS: Using GCS bucket: {bucket_name}")

    # Fetch 'done' items from Firestore, ordered by publish_date
    logger.info("RSS: Fetching 'done' items from Firestore for feed.")
    docs_query = db_client.collection("items") \
        .where("status", "==", "done") \
        .where("audio_url", "!=", None) \
        .order_by("publish_date", direction="DESCENDING") \
        .limit(100)

    items_for_feed = []
    raw_items_count = 0
    parse_errors_count = 0

    for doc in docs_query.stream():
        raw_items_count += 1
        data = doc.to_dict()
        item_id = data.get("id", f"unknown_item_{raw_items_count}")
        logger.debug(f"RSS: Processing item '{item_id}' (Title: '{data.get('title', 'N/A')}') for feed inclusion.")

        raw_date_str = data.get("publish_date", "")
        publish_datetime_utc = None

        if isinstance(raw_date_str, datetime):
            publish_datetime_utc = raw_date_str
            if publish_datetime_utc.tzinfo is None:
                publish_datetime_utc = publish_datetime_utc.replace(tzinfo=timezone.utc)
        elif isinstance(raw_date_str, str) and raw_date_str:
            try:
                parsed_dt = date_parser.parse(raw_date_str)
                if parsed_dt.tzinfo is None:
                    publish_datetime_utc = parsed_dt.replace(tzinfo=timezone.utc)
                else:
                    publish_datetime_utc = parsed_dt.astimezone(timezone.utc)
                logger.debug(f"RSS: Parsed publish_date '{raw_date_str}' to '{publish_datetime_utc}' for item {item_id}.")
            except (ValueError, TypeError) as e_date:
                logger.warning(f"RSS: Could not parse publish_date '{raw_date_str}' for item '{item_id}': {e_date}. Using current time as fallback.")
                publish_datetime_utc = datetime.now(timezone.utc)
                parse_errors_count += 1
        else:
            logger.warning(f"RSS: Missing or invalid publish_date for item '{item_id}'. Using current time as fallback.")
            publish_datetime_utc = datetime.now(timezone.utc)
            parse_errors_count += 1
        
        data["publish_datetime_utc"] = publish_datetime_utc
        items_for_feed.append(data)

    logger.info(f"RSS: Retrieved {raw_items_count} raw items. Prepared {len(items_for_feed)} items for feed. Date parsing issues for {parse_errors_count} items.")

    # Build the feed
    fg = FeedGenerator()
    fg.title("SpeakLoudTTS Audio Articles")
    feed_link = app_url_root.rstrip('/') + '/'
    fg.link(href=feed_link, rel="alternate")
    fg.description("Listen to web articles converted to audio by SpeakLoudTTS.")
    fg.language("en")

    for item_data in items_for_feed:
        item_id = item_data.get("id", "unknown")
        logger.debug(f"RSS: Adding item '{item_id}' (Title: '{item_data.get('title')}') to feed.")
        fe = fg.add_entry()
        fe.id(f"{feed_link}items/{item_id}")
        fe.title(item_data.get("title", "Untitled Audio Article"))
        fe.link(href=f"{feed_link}items/{item_id}", rel="alternate")
        
        description = f"Audio version of the article: {item_data.get('title', '')}. "
        if item_data.get("author"): description += f"By {item_data.get('author')}. "
        if item_data.get("url"): description += f"Original article: {item_data.get('url')}"
        fe.description(description)
        
        fe.pubDate(item_data["publish_datetime_utc"])
        if item_data.get("author"): fe.author(name=item_data.get("author"))

        audio_url = item_data.get("audio_url")
        if audio_url:
            length_bytes = "0"
            # PERFORMANCE: Prioritize reading size from Firestore field to avoid GCS call
            if "audio_size_bytes" in item_data:
                length_bytes = str(item_data["audio_size_bytes"])
                logger.debug(f"RSS: Found pre-saved blob size {length_bytes} bytes for item '{item_id}'.")
            else:
                # Fallback for older items: get size from GCS and log a warning
                gcs_path = item_data.get("gcs_path", f"{item_id}.mp3")
                blob = bucket.get_blob(gcs_path)
                if blob and blob.size is not None:
                    length_bytes = str(blob.size)
                    logger.warning(f"RSS: Fetched blob size {length_bytes} bytes via a live GCS call for item '{item_id}'. "
                                   f"Consider backfilling the 'audio_size_bytes' field in Firestore.")
                else:
                    logger.error(f"RSS: Could not get blob or size for item '{item_id}' (gs://{bucket_name}/{gcs_path}). Using length 0.")
            
            fe.enclosure(url=audio_url, length=length_bytes, type="audio/mpeg")
        else:
            logger.warning(f"RSS: Item '{item_id}' is 'done' but has no audio_url. Skipping enclosure.")

    rss_xml_string = fg.rss_str(pretty=True)
    logger.info(f"RSS feed generated successfully. Final XML length: {len(rss_xml_string)} bytes.")
    return rss_xml_string
