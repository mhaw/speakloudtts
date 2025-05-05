import os, json, tempfile, subprocess, logging
from urllib.parse import urljoin
from datetime import datetime

import requests
import trafilatura
from flask import (
    Flask, request, jsonify, render_template, Response, abort
)
from bs4 import BeautifulSoup
from newspaper import Article
from readability import Document
from dateutil import parser as dateparser
from google.cloud import texttospeech, storage, firestore
from feedgen.feed import FeedGenerator

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("speakloudtts")

# ─── Configuration ───────────────────────────────────────────────────
GCS_BUCKET    = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
MAX_TTS_CHARS = 4500
USER_AGENT    = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/112.0.0.0 Safari/537.36")
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── GCP Clients ──────────────────────────────────────────────────────
db             = firestore.Client()
tts_client     = texttospeech.TextToSpeechClient()
storage_client = storage.Client()
bucket         = storage_client.bucket(GCS_BUCKET)

VOICE_PARAMS = texttospeech.VoiceSelectionParams(
    language_code="en-US",
    name="en-US-Wavenet-D",
    ssml_gender=texttospeech.SsmlVoiceGender.MALE
)
AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3
)

# ─── Extract Article ────────────────────────────────────────────────────
def extract_article(url: str) -> dict:
    sess = requests.Session()
    sess.headers.update(FETCH_HEADERS)
    resp = sess.get(url, timeout=10)
    resp.raise_for_status()
    html = resp.text

    last_mod = resp.headers.get("Last-Modified", "")
    etag     = resp.headers.get("ETag", "")

    # 1) Trafilatura
    text = trafilatura.extract(html) or ""
    source = "trafilatura"

    # 2) newspaper fallback
    if not text or len(text) < 200:
        logger.info("Trafilatura fail → newspaper3k")
        art = Article(url, browser_user_agent=USER_AGENT)
        art.download(); art.parse()
        text = art.text or ""
        source = "newspaper3k"

    # 3) readability fallback
    if not text or len(text) < 200:
        logger.info("newspaper3k fail → readability")
        doc = Document(html)
        summary_html = doc.summary()
        text = BeautifulSoup(summary_html, "html.parser").get_text()
        source = "readability"

    soup = BeautifulSoup(html, "html.parser")

    # JSON-LD first
    ld_title = ld_author = ld_date = ""
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
            arr  = data if isinstance(data, list) else [data]
            for e in arr:
                if e.get("@type") in ("NewsArticle","Article"):
                    ld_title = e.get("headline","") or ld_title
                    a = e.get("author","")
                    if isinstance(a, dict):
                        ld_author = a.get("name","")
                    elif isinstance(a, list):
                        ld_author = ", ".join(x.get("name","") for x in a)
                    ld_date   = e.get("datePublished","") or ld_date
        except Exception:
            continue

    def gm(name=None, prop=None):
        sel = {"property": prop} if prop else {"name": name}
        tag = soup.find("meta", attrs=sel)
        return tag["content"] if tag and tag.has_attr("content") else ""

    title = (ld_title
             or gm(prop="og:title")
             or (soup.title.string if soup.title else ""))
    author      = ld_author or gm(name="author")
    pubdate     = ld_date or gm(prop="article:published_time") or gm(name="publish_date")
    keywords    = gm(name="keywords")
    tags        = [t.strip() for t in keywords.split(",")] if keywords else []

    icon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
    raw_icon = icon["href"] if icon and icon.has_attr("href") else ""
    favicon = urljoin(url, raw_icon) if raw_icon else ""

    wc = len(text.split())
    rt = max(1, wc // 200)

    logger.info(
        "Extractor=%s | Title=%r | Author=%r | Words=%d",
        source, title, author, wc
    )
    return {
        "text": text,
        "url": url,
        "title": title,
        "author": author,
        "publish_date": pubdate,
        "tags": tags,
        "favicon_url": favicon,
        "word_count": wc,
        "reading_time_min": rt,
        "last_modified": last_mod,
        "etag": etag,
    }

# ─── Synthesize & Upload ─────────────────────────────────────────────────────
def synthesize_long_text(text: str, title: str, author: str, item_id: str) -> str:
    intro = f"Title: {title}. By {author}. "
    full  = intro + text
    tmp   = tempfile.gettempdir()
    segs  = []

    for i in range(0, len(full), MAX_TTS_CHARS):
        chunk = full[i : i + MAX_TTS_CHARS]
        resp = tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=chunk),
            voice=VOICE_PARAMS,
            audio_config=AUDIO_CONFIG
        )
        fn = os.path.join(tmp, f"{item_id}_{i}.mp3")
        with open(fn, "wb") as f:
            f.write(resp.audio_content)
        segs.append(fn)

    list_txt = os.path.join(tmp, f"{item_id}_list.txt")
    with open(list_txt, "w") as f:
        for p in segs:
            f.write(f"file '{p}'\n")

    merged = os.path.join(tmp, f"{item_id}_full.mp3")
    subprocess.run(
        ["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0",
         "-i",list_txt,"-c","copy",merged],
        check=True
    )

    blob = bucket.blob(f"{item_id}.mp3")
    blob.upload_from_filename(merged, content_type="audio/mpeg")
    uri = f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3"
    logger.info("Uploaded MP3 to %s", uri)
    return uri

# ─── Flask App & Routes ───────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/submit", methods=["GET","POST"])
def submit_url():
    if request.method == "GET":
        return render_template("submit.html")

    payload = request.get_json(silent=True) or {}
    url     = payload.get("url") or request.form.get("url")
    if not url:
        return jsonify({"error":"url is required"}), 400

    logger.info("New submission: %s", url)
    try:
        meta = extract_article(url)
    except Exception as e:
        logger.exception("Extraction failed")
        return jsonify({"error":"extraction failed","detail":str(e)}), 500

    # Save initial record
    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    record = {**meta, "status":"pending", "created_at":firestore.SERVER_TIMESTAMP}
    doc_ref.set(record)
    logger.info("Saved record %s", item_id)

    # TTS + upload
    try:
        tts_uri = synthesize_long_text(
            meta["text"], meta["title"], meta["author"], item_id
        )
        doc_ref.update({"status":"done","tts_uri":tts_uri})
    except Exception as e:
        logger.exception("TTS error")
        doc_ref.update({"status":"error","error":str(e)})
        return jsonify({"error":"tts failed","detail":str(e)}), 500

    return jsonify({"item_id":item_id,"tts_uri":tts_uri}), 202

@app.route("/api/recent", methods=["GET"])
def api_recent():
    docs = (
        db.collection("items")
          .where("status","==","done")
          .order_by("created_at", firestore.Query.DESCENDING)
          .limit(5)
          .stream()
    )
    out = [{"id":d.id,
            "title": d.to_dict().get("title") or d.to_dict().get("url"),
            "url":   d.to_dict().get("url")}
           for d in docs]
    return jsonify(out), 200

@app.route("/api/items/<item_id>/tags", methods=["PUT"])
def update_tags(item_id):
    payload = request.get_json(silent=True)
    if not payload or "tags" not in payload or not isinstance(payload["tags"], list):
        return jsonify({"error":"Request must be JSON {tags:[...]}"},), 400

    doc_ref = db.collection("items").document(item_id)
    if not doc_ref.get().exists:
        return jsonify({"error":"Item not found"}), 404

    doc_ref.update({"tags": payload["tags"]})
    return jsonify({"id": item_id, "tags": payload["tags"]}), 200

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
            "id":           d.id,
            "title":        data.get("title",""),
            "author":       data.get("author",""),
            "date":         data.get("publish_date",""),
            "word_count":   data.get("word_count",0),
            "reading_time": data.get("reading_time_min",0),
            "favicon_url":  data.get("favicon_url",""),
            "audio_url":    f"https://storage.googleapis.com/{GCS_BUCKET}/{d.id}.mp3",
            "tags":         data.get("tags", []),
        })
    return render_template("items.html", items=items)

@app.route("/items/<item_id>", methods=["GET"])
def item_detail(item_id):
    doc = db.collection("items").document(item_id).get()
    if not doc.exists:
        abort(404)

    data = doc.to_dict()
    # human‐friendly date
    raw = data.get("publish_date")
    try:
        dt = dateparser.isoparse(raw)
        fmt_date = dt.strftime("%B %d, %Y")
    except Exception:
        fmt_date = raw or ""

    return render_template("detail.html",
        item={
          **data,
          "id": item_id,
          "audio_url": f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3",
          "publish_date_fmt": fmt_date
        }
    )

@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    fg = FeedGenerator()
    fg.title("SpeakLoudTTS Podcast")
    fg.link(href=request.url_root+"feed.xml", rel="self")
    fg.description("Audio renditions of saved articles")

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
        fe.title(data.get("title",""))
        fe.pubDate(data.get("created_at"))
        fe.enclosure(f"https://storage.googleapis.com/{GCS_BUCKET}/{d.id}.mp3", 0, "audio/mpeg")

    return Response(fg.rss_str(pretty=True), mimetype="application/rss+xml")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"}), 200

if __name__ == "__main__":
    logger.info("Starting server on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)