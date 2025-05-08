import os
import logging
from datetime import datetime

from flask import (
    Flask, request, jsonify, render_template,
    Response, abort, send_from_directory
)
from dateutil import parser as dateparser
from google.cloud import firestore

from extractor import extract_article
from tts import synthesize_long_text
import rss

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("speakloudtts")

# ─── Configuration ───────────────────────────────────────────────────
GCS_BUCKET     = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
ALLOWED_VOICES = [
    "en-US-Wavenet-D",
    "en-US-Wavenet-F",
    "en-GB-Wavenet-B",
    "en-AU-Wavenet-C",
]
DEFAULT_VOICE  = ALLOWED_VOICES[0]

# ─── Firestore & Flask Init ──────────────────────────────────────────
db  = firestore.Client()
app = Flask(__name__, static_folder="static", static_url_path="/static")


# ─── Home & Favicon ───────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon"
    )


# ─── Submit Route ─────────────────────────────────────────────────────
@app.route("/submit", methods=["GET", "POST"])
def submit_url():
    if request.method == "GET":
        return render_template(
            "submit.html",
            voices=ALLOWED_VOICES,
            default_voice=DEFAULT_VOICE
        )

    payload = request.get_json(silent=True) or {}
    url      = payload.get("url") or request.form.get("url", "")
    voice    = payload.get("voice_name") \
               or payload.get("voice") \
               or request.form.get("voice") \
               or DEFAULT_VOICE
    if voice not in ALLOWED_VOICES:
        voice = DEFAULT_VOICE

    if not url:
        return jsonify({"error": "url is required"}), 400

    logger.info("New submission: %s (voice=%s)", url, voice)
    try:
        meta = extract_article(url)
    except Exception as e:
        logger.exception("Extraction failed")
        return jsonify({"error": "extraction failed", "detail": str(e)}), 500

    # Save initial record
    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    record = {
        **meta,
        "url":            url,
        "voice":          voice,
        "status":         "pending",
        "submitted_at":   datetime.utcnow().isoformat(),
        "submitted_ip":   request.remote_addr,
        "created_at":     firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set(record)

    # Kick off TTS and upload
    try:
        result = synthesize_long_text(
            meta["title"],
            meta["author"],
            meta["text"],
            item_id,
            voice
        )
        tts_uri = result["uri"]
        doc_ref.update({"status": "done", "tts_uri": tts_uri})
    except Exception as e:
        logger.exception("TTS/upload error")
        doc_ref.update({"status": "error", "error": str(e)})
        return jsonify({"error": "tts failed", "detail": str(e)}), 500

    return jsonify({"item_id": item_id, "tts_uri": tts_uri}), 202


# ─── Recent Items API ─────────────────────────────────────────────────
@app.route("/api/recent", methods=["GET"])
def api_recent():
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("created_at", firestore.Query.DESCENDING)
          .limit(5)
          .stream()
    )
    out = []
    for d in docs:
        data = d.to_dict()
        out.append({
            "id":    d.id,
            "title": data.get("title") or data.get("url"),
            "url":   data.get("url"),
        })
    return jsonify(out), 200


# ─── Update Tags API ───────────────────────────────────────────────────
@app.route("/api/items/<item_id>/tags", methods=["PUT"])
def update_tags(item_id):
    payload = request.get_json(silent=True) or {}
    tags    = payload.get("tags")
    if not isinstance(tags, list):
        return jsonify({"error": "Request must be JSON {tags:[...]}"}), 400

    doc_ref = db.collection("items").document(item_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Item not found"}), 404

    doc_ref.update({"tags": tags})
    return jsonify({"id": item_id, "tags": tags}), 200


# ─── Errors List Page ─────────────────────────────────────────────────
@app.route("/errors", methods=["GET"])
def list_errors():
    # pull all items with status=error (no index required)
    docs = db.collection("items") \
             .where("status", "==", "error") \
             .stream()

    errors = []
    for d in docs:
        data = d.to_dict()
        errors.append({
            "id":           d.id,
            "url":          data.get("url", ""),
            "title":        data.get("title", "<no title>"),
            "submitted_at": data.get("submitted_at", ""),
            "error":        data.get("error", "<no message>"),
        })

    return render_template("errors.html", errors=errors)


@app.route("/api/items/<item_id>/retry", methods=["POST"])
def retry_item(item_id):
    doc_ref = db.collection("items").document(item_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Not found"}), 404

    # reset status
    doc_ref.update({
        "status":     "pending",
        "error":      firestore.DELETE_FIELD,
        "created_at": firestore.SERVER_TIMESTAMP
    })

    record = doc_ref.get().to_dict()
    try:
        result = synthesize_long_text(
            record["title"],
            record["author"],
            record["text"],
            item_id,
            record.get("voice", DEFAULT_VOICE)
        )
        tts_uri = result["uri"]
        doc_ref.update({"status": "done", "tts_uri": tts_uri})
    except Exception as e:
        doc_ref.update({"status": "error", "error": str(e)})
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "requeued"}), 202


# ─── Server-Rendered List & Detail ────────────────────────────────────
@app.route("/items", methods=["GET"])
def list_items():
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("created_at", firestore.Query.DESCENDING)
          .stream()
    )
    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id":             d.id,
            "title":          data.get("title", ""),
            "author":         data.get("author", ""),
            "date":           data.get("publish_date", ""),
            "word_count":     data.get("word_count", 0),
            "reading_time":   data.get("reading_time_min", 0),
            "voice":          data.get("voice", DEFAULT_VOICE),
            "audio_url":      f"https://storage.googleapis.com/{GCS_BUCKET}/{d.id}.mp3",
            "tags":           data.get("tags", []),
        })
    return render_template("items.html", items=items)


@app.route("/items/<item_id>", methods=["GET"])
def item_detail(item_id):
    doc = db.collection("items").document(item_id).get()
    if not doc.exists:
        abort(404)

    data = doc.to_dict()
    raw  = data.get("publish_date", "")
    try:
        dt       = dateparser.isoparse(raw)
        date_fmt = dt.strftime("%B %d, %Y")
    except Exception:
        date_fmt = raw or ""

    return render_template("detail.html", item={
        **data,
        "id":                item_id,
        "audio_url":         f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3",
        "publish_date_fmt":  date_fmt,
    })


# ─── RSS Feed ──────────────────────────────────────────────────────────
@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    xml = rss.generate_feed(request.url_root, bucket_name=GCS_BUCKET)
    return Response(xml, mimetype="application/rss+xml")


# ─── Health Check ─────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ─── Main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting server on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)