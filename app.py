import os
import logging
from datetime import datetime

from flask import (
    Flask, request, jsonify, render_template, Response, abort
)
from dateutil import parser as dateparser
from google.cloud import firestore

from extractor import extract_article
from tts import synthesize_long_text
from rss import generate_feed

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("speakloudtts")

# ─── Configuration ───────────────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")

# ─── Firestore client ─────────────────────────────────────────────────
db = firestore.Client()

# ─── Flask app ───────────────────────────────────────────────────────
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
        return jsonify({"error": "url is required"}), 400

    logger.info("New submission: %s", url)
    try:
        meta = extract_article(url)
    except Exception as e:
        logger.exception("Extraction failed")
        return jsonify({"error": "extraction failed", "detail": str(e)}), 500

    # save pending record
    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    record  = {**meta, "status": "pending", "created_at": firestore.SERVER_TIMESTAMP}
    doc_ref.set(record)
    logger.info("Saved record %s", item_id)

    # synthesize TTS and upload
    try:
        tts_url = synthesize_long_text(
            meta["title"], meta["author"], meta["text"], item_id
        )
        doc_ref.update({"status": "done", "tts_uri": tts_url})
    except Exception as e:
        logger.exception("TTS/upload failed")
        doc_ref.update({"status": "error", "error": str(e)})
        return jsonify({"error": "tts failed", "detail": str(e)}), 500

    return jsonify({"item_id": item_id, "tts_uri": tts_url}), 202


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
            "url":   data.get("url")
        })
    return jsonify(out), 200


@app.route("/api/items/<item_id>/tags", methods=["PUT"])
def update_tags(item_id):
    payload = request.get_json(silent=True)
    if not payload or "tags" not in payload or not isinstance(payload["tags"], list):
        return jsonify({"error": "Expected JSON {tags: [...]}"}), 400

    doc_ref = db.collection("items").document(item_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Item not found"}), 404

    doc_ref.update({"tags": payload["tags"]})
    return jsonify({"id": item_id, "tags": payload["tags"]}), 200


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
            "id":           d.id,
            "title":        data.get("title", ""),
            "author":       data.get("author", ""),
            "date":         data.get("publish_date", ""),
            "word_count":   data.get("word_count", 0),
            "reading_time": data.get("reading_time_min", 0),
            "favicon_url":  data.get("favicon_url", ""),
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
    raw  = data.get("publish_date", "")
    try:
        dt  = dateparser.isoparse(raw)
        fmt = dt.strftime("%B %d, %Y")
    except Exception:
        fmt = raw

    return render_template("detail.html", item={
        **data,
        "id":               item_id,
        "audio_url":        f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3",
        "publish_date_fmt": fmt
    })


@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    xml = generate_feed(request.url_root, bucket_name=GCS_BUCKET)
    return Response(xml, mimetype="application/rss+xml")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    logger.info("Starting speakloudtts on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)