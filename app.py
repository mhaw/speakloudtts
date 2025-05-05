import os
import json
import logging
from urllib.parse import urljoin

import requests
import trafilatura
from readability import Document
from bs4 import BeautifulSoup
from newspaper import Article

from flask import Flask, request, jsonify, render_template, abort, Response
from google.cloud import firestore
from feedgen.feed import FeedGenerator

from tts import synthesize_long_text

# ─── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("speakloudtts")

# ─── Configuration ──────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/112.0.0.0 Safari/537.36"
)
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

# ─── GCP Clients ────────────────────────────────────────────────────────────────
db = firestore.Client()

app = Flask(__name__)


def extract_article(url: str) -> dict:
    """
    Fetch & parse with Trafilatura → newspaper → readability.
    Extract metadata via JSON-LD / og: / meta tags.
    Returns a dict of title, author, text, publish_date, tags, favicon_url, word_count, reading_time_min, etc.
    """
    sess = requests.Session()
    sess.headers.update(FETCH_HEADERS)
    resp = sess.get(url, timeout=10)
    resp.raise_for_status()
    html = resp.text

    # basic text extraction
    text = trafilatura.extract(html) or ""
    source = "trafilatura"
    if not text or len(text) < 200:
        logger.info("Trafilatura too short → newspaper3k")
        art = Article(url, browser_user_agent=USER_AGENT)
        art.download(); art.parse()
        text = art.text or ""
        source = "newspaper3k"
    if not text or len(text) < 200:
        logger.info("newspaper3k too short → readability")
        doc = Document(html)
        text = BeautifulSoup(doc.summary(), "html.parser").get_text()
        source = "readability"

    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD first
    ld_title = ld_author = ld_date = ""
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
            arr = data if isinstance(data, list) else [data]
            for e in arr:
                if e.get("@type") in ("NewsArticle", "Article"):
                    ld_title = e.get("headline", ld_title)
                    auth = e.get("author", "")
                    if isinstance(auth, dict):
                        ld_author = auth.get("name", ld_author)
                    elif isinstance(auth, list):
                        ld_author = ", ".join(x.get("name", "") for x in auth)
                    ld_date = e.get("datePublished", ld_date)
        except Exception:
            continue

    def gm(name=None, prop=None):
        sel = {"property": prop} if prop else {"name": name}
        tag = soup.find("meta", attrs=sel)
        return tag["content"] if tag and tag.has_attr("content") else ""

    title = ld_title or gm(prop="og:title") or (soup.title.string if soup.title else "")
    author = ld_author or gm(name="author")
    pubdate = ld_date or gm(prop="article:published_time")
    kw = gm(name="keywords")
    tags = [t.strip() for t in kw.split(",")] if kw else []

    icon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    favicon = urljoin(url, icon["href"]) if icon and icon.has_attr("href") else ""

    words = text.split()
    wc = len(words)
    rt = max(1, wc // 200)

    logger.info(
        "Extractor=%s | Title=%r | Author=%r | Words=%d",
        source, title, author, wc
    )

    return {
        "text": text,
        "title": title,
        "author": author,
        "publish_date": pubdate,
        "tags": tags,
        "favicon_url": favicon,
        "word_count": wc,
        "reading_time_min": rt,
    }


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/submit", methods=["GET", "POST"])
def submit_url():
    if request.method == "GET":
        return render_template("submit.html")

    data = request.get_json(silent=True) or {}
    url  = data.get("url") or request.form.get("url")
    if not url:
        return jsonify({"error":"url is required"}), 400

    logger.info("New submission: %s", url)
    try:
        meta = extract_article(url)
    except Exception as e:
        logger.exception("Extraction failed")
        return jsonify({"error":"extraction failed","detail":str(e)}), 500

    # Save initial Firestore record
    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    record = {**meta, "url": url, "status": "pending", "created_at": firestore.SERVER_TIMESTAMP}
    doc_ref.set(record)
    logger.info("Saved record %s", item_id)

    # Kick off TTS
    try:
        tts_uri = synthesize_long_text(
            meta["title"],
            meta["author"],
            meta["text"],
            item_id
        )
        doc_ref.update({"status":"done","tts_uri":tts_uri})
    except Exception as e:
        logger.exception("TTS/upload error")
        doc_ref.update({"status":"error","error":str(e)})
        return jsonify({"error":"tts failed","detail":str(e)}), 500

    return jsonify({"item_id":item_id,"tts_uri":tts_uri}), 202


@app.route("/items", methods=["GET"])
def list_items():
    docs = (
        db.collection("items")
          .where("status","==","done")
          .order_by("created_at", firestore.Query.DESCENDING)
          .stream()
    )
    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id": d.id,
            "title": data.get("title",""),
            "author": data.get("author",""),
            "date": data.get("publish_date",""),
            "word_count": data.get("word_count",0),
            "reading_time": data.get("reading_time_min",0),
            "favicon_url": data.get("favicon_url",""),
            "audio_url": f"https://storage.googleapis.com/{os.getenv('GCS_BUCKET_NAME','speakloudtts-audio-files')}/{d.id}.mp3"
        })
    return render_template("items.html", items=items)


@app.route("/items/<item_id>", methods=["GET"])
def item_detail(item_id):
    doc = db.collection("items").document(item_id).get()
    if not doc.exists:
        abort(404)
    data = doc.to_dict()
    data["audio_url"] = f"https://storage.googleapis.com/{os.getenv('GCS_BUCKET_NAME','speakloudtts-audio-files')}/{item_id}.mp3"
    return render_template("detail.html", item=data)


@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    fg = FeedGenerator()
    fg.title("SpeakLoudTTS Podcast")
    fg.link(href=request.url_root+"feed.xml", rel="self")
    fg.description("Audio renditions of your saved articles")

    docs = (
        db.collection("items")
          .where("status","==","done")
          .order_by("created_at", firestore.Query.DESCENDING)
          .stream()
    )
    for d in docs:
        data = d.to_dict()
        fe = fg.add_entry()
        fe.id(d.id)
        fe.title(data["title"])
        fe.pubDate(data["created_at"])
        fe.enclosure(f"https://storage.googleapis.com/{os.getenv('GCS_BUCKET_NAME','speakloudtts-audio-files')}/{d.id}.mp3",0,"audio/mpeg")

    return Response(fg.rss_str(pretty=True), mimetype="application/rss+xml")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"}), 200

@app.route("/api/recent", methods=["GET"])
def api_recent():
    """
    Returns JSON list of up to 5 most-recently completed items:
    [{ id, title, url }, …]
    """
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .limit(5)
          .stream()
    )
    recent = []
    for d in docs:
        data = d.to_dict()
        recent.append({
            "id":    d.id,
            "title": data.get("title") or data.get("url"),
            "url":   data.get("url"),
        })
    return jsonify(recent)


if __name__ == "__main__":
    logger.info("Starting server on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)