import os
import logging
from datetime import datetime
from collections import Counter

from flask import (
    Flask, request, jsonify, render_template,
    Response, abort, send_from_directory
)
from dateutil import parser as dateparser

from google.cloud import firestore, storage
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
    "en-US-Wavenet-A", "en-US-Wavenet-B", "en-US-Wavenet-C",
    "en-US-Wavenet-D", "en-US-Wavenet-E", "en-US-Wavenet-F",
    "en-GB-Wavenet-A", "en-GB-Wavenet-D", "en-AU-Wavenet-C",
    "en-US-Neural2-A", "en-US-Neural2-B",
]
DEFAULT_VOICE  = ALLOWED_VOICES[0]

# ─── Clients & App Setup ─────────────────────────────────────────────
db             = firestore.Client()
storage_client = storage.Client()
bucket         = storage_client.bucket(GCS_BUCKET)
app            = Flask(__name__, static_folder="static", static_url_path="/static")


# ─── Home & Static Assets ────────────────────────────────────────────
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

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js")


# ─── Submit Route ────────────────────────────────────────────────────
@app.route("/submit", methods=["GET", "POST"])
def submit_url():
    if request.method == "GET":
        return render_template("submit.html",
                               voices=ALLOWED_VOICES,
                               default_voice=DEFAULT_VOICE)

    payload = request.get_json(silent=True) or {}
    url      = payload.get("url") or request.form.get("url", "")
    voice    = (payload.get("voice_name")
                or payload.get("voice")
                or request.form.get("voice")
                or DEFAULT_VOICE)
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
        "url":           url,
        "voice":         voice,
        "status":        "pending",
        "submitted_at":  datetime.utcnow().isoformat(),
        "submitted_ip":  request.remote_addr,
        "created_at":    firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set(record)

    # Kick off TTS + upload + record size
    try:
        result = synthesize_long_text(
            meta["title"], meta["author"], meta["text"], item_id, voice
        )
        tts_uri = result["uri"]

        # get the MP3 size in bytes
        blob = bucket.get_blob(f"{item_id}.mp3")
        size = blob.size if blob else None

        doc_ref.update({
            "status":         "done",
            "tts_uri":        tts_uri,
            "processed_at":   firestore.SERVER_TIMESTAMP,
            "storage_bytes":  size,
        })
    except Exception as e:
        logger.exception("TTS/upload error")
        doc_ref.update({"status": "error", "error": str(e)})
        return jsonify({"error": "tts failed", "detail": str(e)}), 500

    return jsonify({"item_id": item_id, "tts_uri": tts_uri}), 202


# ─── List & Detail Pages ─────────────────────────────────────────────
@app.route("/items", methods=["GET"])
def list_items():
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .stream()
    )
    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id":            d.id,
            "title":         data.get("title", ""),
            "author":        data.get("author", ""),
            "date":          data.get("publish_date", ""),
            "word_count":    data.get("word_count", 0),
            "reading_time":  data.get("reading_time_min", 0),
            "voice":         data.get("voice", DEFAULT_VOICE),
            "audio_url":     f"https://storage.googleapis.com/{GCS_BUCKET}/{d.id}.mp3",
            "tags":          data.get("tags", []),
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
        dt        = dateparser.isoparse(raw)
        date_fmt  = dt.strftime("%B %d, %Y")
    except Exception:
        date_fmt = raw or ""

    return render_template("detail.html", item={
        **data,
        "id":                item_id,
        "audio_url":         f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3",
        "publish_date_fmt":  date_fmt,
    })


# ─── Errors Page ─────────────────────────────────────────────────────
@app.route("/errors", methods=["GET"])
def list_errors():
    docs = db.collection("items").where("status", "==", "error").stream()
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


# ─── RSS Feed ─────────────────────────────────────────────────────────
@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    xml = rss.generate_feed(request.url_root, bucket_name=GCS_BUCKET)
    return Response(xml, mimetype="application/rss+xml")


# ─── JSON API: Recent ─────────────────────────────────────────────────
@app.route("/api/recent", methods=["GET"])
def api_recent():
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .limit(5)
          .stream()
    )
    return jsonify([
        {
            "id":    d.id,
            "title": d.to_dict().get("title") or d.to_dict().get("url"),
            "url":   d.to_dict().get("url")
        }
        for d in docs
    ]), 200


# ─── JSON API: Admin Items (paginated) ────────────────────────────────
@app.route("/api/admin/items", methods=["GET"])
def api_admin_items():
    try:
        page      = max(1, int(request.args.get("page", 1)))
        page_size = max(1, int(request.args.get("page_size", 20)))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters"}), 400

    offset = (page - 1) * page_size
    query  = (
        db.collection("items")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .offset(offset)
          .limit(page_size)
    )
    try:
        docs = query.stream()
    except Exception as e:
        return jsonify({"error": f"Firestore query failed: {e}"}), 500

    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id":             d.id,
            "title":          data.get("title") or data.get("url", ""),
            "status":         data.get("status", ""),
            "voice":          data.get("voice", ""),
            "publish_date":   data.get("publish_date", ""),
            "submitted_ip":   data.get("submitted_ip", ""),
            "processed_at":   data.get("processed_at", ""),
            "word_count":     data.get("word_count", 0),
            "storage_bytes":  data.get("storage_bytes", None),
            "tags":           data.get("tags", []),
        })

    return jsonify({
        "page":       page,
        "page_size":  page_size,
        "items":      items
    }), 200


# ─── JSON API: Update Tags ────────────────────────────────────────────
@app.route("/api/items/<item_id>/tags", methods=["PUT"])
def update_tags(item_id):
    payload = request.get_json(silent=True) or {}
    tags    = payload.get("tags")
    if not isinstance(tags, list):
        return jsonify({"error": "JSON body must include tags:[]"}), 400

    ref = db.collection("items").document(item_id)
    if not ref.get().exists:
        return jsonify({"error": "Item not found"}), 404

    ref.update({"tags": tags})
    return jsonify({"id": item_id, "tags": tags}), 200


# ─── JSON API: Retry Item ─────────────────────────────────────────────
@app.route("/api/items/<item_id>/retry", methods=["POST"])
def retry_item(item_id):
    ref = db.collection("items").document(item_id)
    if not ref.get().exists:
        return jsonify({"error": "Not found"}), 404

    # reset and rerun
    ref.update({
        "status":     "pending",
        "error":      firestore.DELETE_FIELD,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    rec = ref.get().to_dict()

    try:
        res = synthesize_long_text(
            rec["title"], rec["author"], rec["text"],
            item_id, rec.get("voice", DEFAULT_VOICE)
        )
        tts_uri = res["uri"]
        # re-fetch size
        blob = bucket.get_blob(f"{item_id}.mp3")
        size = blob.size if blob else None

        ref.update({
            "status":         "done",
            "tts_uri":        tts_uri,
            "processed_at":   firestore.SERVER_TIMESTAMP,
            "storage_bytes":  size,
        })
    except Exception as e:
        ref.update({"status": "error", "error": str(e)})
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "requeued"}), 202


# ─── JSON API: Admin Stats ────────────────────────────────────────────
@app.route("/api/admin/stats", methods=["GET"])
def api_admin_stats():
    docs = db.collection("items").stream()
    counts = Counter()
    tags   = Counter()
    for d in docs:
        data = d.to_dict()
        counts[data.get("status","unknown")] += 1
        for t in data.get("tags", []):
            tags[t] += 1

    return jsonify({
        "total":   sum(counts.values()),
        "done":    counts["done"],
        "pending": counts["pending"],
        "error":   counts["error"],
        "by_tag":  dict(tags)
    }), 200


# ─── JSON API: Update Arbitrary Fields ────────────────────────────────
@app.route("/api/items/<item_id>", methods=["PUT"])
def api_update_item(item_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"title", "author", "publish_date", "tags", "voice"}
    up = {k: v for k, v in payload.items() if k in allowed}
    if not up:
        return jsonify({"error": "No editable fields provided"}), 400

    ref = db.collection("items").document(item_id)
    if not ref.get().exists:
        return jsonify({"error": "Not found"}), 404

    ref.update(up)
    return jsonify({"id": item_id, **up}), 200


# ─── Admin Dashboard ─────────────────────────────────────────────────
@app.route("/admin", methods=["GET"])
def admin_dashboard():
    return render_template("admin.html")


# ─── Health Check ─────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ─── Main ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting server on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)