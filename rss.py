# rss.py
import os
import logging
from datetime import datetime, timezone
from dateutil import parser as dateparser

from feedgen.feed import FeedGenerator
from google.cloud import firestore

logger = logging.getLogger("rss")

def generate_feed(request_url_root: str, bucket_name: str = None) -> str:
    """
    Builds an RSS 2.0 feed of all 'done' items in Firestore,
    sorted by the original publish_date, and returns it as a
    UTF-8 string.
    """
    if bucket_name is None:
        bucket_name = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")

    db = firestore.Client()

    # 1) Grab all done items (no ordering index required)
    docs = db.collection("items") \
             .where("status", "==", "done") \
             .stream()

    # 2) Assemble and parse dates
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
            "audio_url": f"https://storage.googleapis.com/{bucket_name}/{d.id}.mp3",
            "pubdate":   dt,
        })

    # 3) Sort descending by publish_date
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
        fe.link(href=it["audio_url"], rel="enclosure")
        fe.pubDate(it["pubdate"])

    # 5) Ensure we return a unicode string
    rss_bytes = fg.rss_str(pretty=True)
    if isinstance(rss_bytes, (bytes, bytearray)):
        try:
            rss_txt = rss_bytes.decode("utf-8")
        except Exception:
            rss_txt = rss_bytes.decode("utf-8", errors="ignore")
    else:
        rss_txt = str(rss_bytes)

    return rss_txt