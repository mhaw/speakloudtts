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
    using each item's original publish_date as <pubDate>.
    """
    # allow override via env, but default to same bucket you use for TTS
    if bucket_name is None:
        bucket_name = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")

    db = firestore.Client()

    fg = FeedGenerator()
    fg.id(request_url_root)
    fg.title("SpeakLoudTTS Podcast")
    fg.link(href=request_url_root,              rel="alternate")
    fg.link(href=request_url_root + "feed.xml", rel="self")
    fg.description("Audio renditions of your saved articles")
    fg.language("en")
    fg.updated(datetime.now(timezone.utc))

    # fetch all completed items, sorted by publish_date descending
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("publish_date", direction=firestore.Query.DESCENDING)
          .stream()
    )

    for d in docs:
        data = d.to_dict()
        # build enclosure URL
        audio_url = f"https://storage.googleapis.com/{bucket_name}/{d.id}.mp3"
        # title fallback
        title = data.get("title") or data.get("url")
        # parse original publish date
        raw = data.get("publish_date", "")
        try:
            dt = dateparser.isoparse(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        entry = fg.add_entry()
        entry.id(d.id)
        entry.title(title)
        entry.link(href=audio_url, rel="enclosure")
        entry.pubDate(dt)

    return fg.rss_str(pretty=True)