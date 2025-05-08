# rss.py

import os
import logging
from datetime import datetime, timezone
from dateutil import parser as dateparser

from feedgen.feed import FeedGenerator
from google.cloud import firestore, storage

logger = logging.getLogger("rss")

def generate_feed(request_url_root: str, bucket_name: str = None) -> str:
    """
    Builds an RSS 2.0 feed of all 'done' items in Firestore,
    sorted by their original publish_date, and returns it as a UTF-8 string.
    """
    # allow override via env
    if bucket_name is None:
        bucket_name = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")

    # Firestore + Storage clients
    db = firestore.Client()
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # 1) Fetch all 'done' items
    docs = db.collection("items") \
             .where("status", "==", "done") \
             .stream()

    # 2) Parse dates and collect
    items = []
    for d in docs:
        data = d.to_dict()
        raw  = data.get("publish_date", "")
        try:
            dt = dateparser.isoparse(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        items.append({
            "id":        d.id,
            "title":     data.get("title") or data.get("url", ""),
            "pubdate":   dt,
        })

    # 3) Sort newest first
    items.sort(key=lambda x: x["pubdate"], reverse=True)

    # 4) Build the feed
    fg = FeedGenerator()
    fg.id(request_url_root)
    fg.title("SpeakLoudTTS Podcast")
    fg.link(href=request_url_root,              rel="alternate")
    fg.link(href=request_url_root + "feed.xml", rel="self")
    fg.description("Audio renditions of your saved articles")
    fg.language("en")
    fg.updated(datetime.now(timezone.utc))

    for it in items:
        fe = fg.add_entry()
        fe.id(it["id"])
        fe.title(it["title"])

        # look up the real MP3 size in bytes so length is accurate
        blob = bucket.get_blob(f"{it['id']}.mp3")
        length = str(blob.size) if blob and blob.size is not None else "0"

        # proper enclosure() call sets url, length & MIME type
        fe.enclosure(
            url=f"https://storage.googleapis.com/{bucket_name}/{it['id']}.mp3",
            length=length,
            type="audio/mpeg"
        )

        fe.pubDate(it["pubdate"])

    # 5) Return clean UTF-8 string
    rss_bytes = fg.rss_str(pretty=True)
    if isinstance(rss_bytes, (bytes, bytearray)):
        try:
            return rss_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return rss_bytes.decode("utf-8", errors="ignore")
    return str(rss_bytes)