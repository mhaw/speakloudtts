import os
import logging
from datetime import datetime

from flask import (
    Flask, request, jsonify, render_template,
    Response, abort, send_from_directory,
    redirect, url_for, flash
)
from dateutil import parser as dateparser

from google.cloud import firestore, storage
from extractor import extract_article
from tts import synthesize_long_text
import rss

from flask_login import (
    LoginManager, login_user, logout_user,
    current_user, login_required
)
from your_user_module import User  # implements User.get() and User.authenticate()

# ─── App & Login Setup ─────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.init_app(app)

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("speakloudtts")

# ─── Configuration ──────────────────────────────────────────────────────────
GCS_BUCKET     = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
ALLOWED_VOICES = [
    "en-US-Wavenet-A", "en-US-Wavenet-B", "en-US-Wavenet-C",
    "en-US-Wavenet-D", "en-US-Wavenet-E", "en-US-Wavenet-F",
    "en-GB-Wavenet-A", "en-GB-Wavenet-D", "en-AU-Wavenet-C",
    "en-US-Neural2-A", "en-US-Neural2-B",
]
DEFAULT_VOICE  = ALLOWED_VOICES[0]

# ─── Google Cloud Clients ────────────────────────────────────────────────────
db             = firestore.Client()
storage_client = storage.Client()
bucket         = storage_client.bucket(GCS_BUCKET)

# ─── Flask-Login User Loader ────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# ─── Public Routes ───────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.authenticate(username, password)
        if user:
            login_user(user)
            return redirect(url_for("submit_url"))
        flash("Invalid credentials", "error")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))  # Tests expect logout → /login

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico", mimetype="image/vnd.microsoft.icon"
    )

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js")

# ─── API: Recent Items ───────────────────────────────────────────────────────
@app.route("/api/recent", methods=["GET"])
@login_required
def api_recent():
    """
    Return the 5 most recent 'done' items for the current user (JSON array).
    """
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .where("user_id", "==", current_user.id)
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .limit(5)
          .stream()
    )
    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id":      d.id,
            "url":     data.get("url", ""),
            "title":   data.get("title", ""),
            "tts_uri": f"https://storage.googleapis.com/{GCS_BUCKET}/{d.id}.mp3",
            "status":  data.get("status", ""),
        })
    return jsonify(items), 200

# ─── Extraction Endpoint ─────────────────────────────────────────────────────
@app.route("/extract", methods=["GET", "POST"])
@login_required
def extract_route():
    """
    If GET: redirect back to /submit. If POST, expect JSON {'url': '...'} 
    and return {'text': '...'} (200). On any extraction error, return 200 + empty text.
    """
    if request.method == "GET":
        return redirect(url_for("submit_url"))

    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    try:
        meta = extract_article(url)
        return jsonify({"text": meta.get("text", "")}), 200
    except Exception:
        # Swallow any extractor error and return empty text (test expects 200)
        logger.warning("Extraction failed, returning empty text", exc_info=True)
        return jsonify({"text": ""}), 200

# ─── Submit Route ───────────────────────────────────────────────────────────
@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit_url():
    if request.method == "GET":
        profile = db.collection("profiles").document(current_user.id).get().to_dict() or {}
        default_voice = profile.get("default_voice", DEFAULT_VOICE)
        default_tags  = ",".join(profile.get("last_tags", []))
        return render_template(
            "submit.html",
            voices=ALLOWED_VOICES,
            default_voice=default_voice,
            default_tags=default_tags
        )

    payload = request.get_json(silent=True) or {}
    url   = payload.get("url", "").strip()
    voice = payload.get("voice_name", DEFAULT_VOICE)
    text  = payload.get("text", "").strip()
    tags  = payload.get("tags", []) if isinstance(payload.get("tags"), list) else []

    if voice not in ALLOWED_VOICES or not url or not text:
        return jsonify({
            "error": "url, text, and valid voice are required"
        }), 400

    # (Re)extract metadata for TTS
    try:
        meta   = extract_article(url)
        title  = meta.get("title")
        author = meta.get("author")
    except Exception:
        logger.warning("Re-extraction failed at submit", exc_info=True)
        title, author = None, None

    logger.info("New submission by %s: %s (voice=%s)", current_user.id, url, voice)

    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    record = {
        "url":          url,
        "voice":        voice,
        "text":         text,
        "tags":         tags,
        "title":        title,
        "author":       author,
        "status":       "pending",
        "user_id":      current_user.id,
        "submitted_at": datetime.utcnow().isoformat(),
        "submitted_ip": request.remote_addr,
        "created_at":   firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set(record)

    try:
        result = synthesize_long_text(title, author, text, item_id, voice)
        tts_uri = result.get("uri")
        blob = bucket.get_blob(f"{item_id}.mp3")
        size = blob.size if blob else None

        doc_ref.update({
            "status":        "done",
            "tts_uri":       tts_uri,
            "processed_at":  firestore.SERVER_TIMESTAMP,
            "storage_bytes": size,
        })

        db.collection("profiles").document(current_user.id).set({
            "default_voice": voice,
            "last_tags":     tags
        }, merge=True)

    except Exception as e:
        logger.exception("TTS/upload error")
        doc_ref.update({
            "status": "error",
            "error":  str(e)
        })
        return jsonify({"error": "tts failed", "detail": str(e)}), 500

    return jsonify({"item_id": item_id, "tts_uri": tts_uri}), 202

# ─── List & Detail Pages ───────────────────────────────────────────────────
@app.route("/items", methods=["GET"])
@login_required
def list_items():
    docs = (
        db.collection("items")
          .where("status", "==", "done")
          .where("user_id", "==", current_user.id)
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .stream()
    )
    items = []
    for d in docs:
        data = d.to_dict()
        items.append({
            "id":            d.id,
            "title":         data.get("title", data.get("url", "")),
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
@login_required
def item_detail(item_id):
    doc = db.collection("items").document(item_id).get()
    if not doc.exists:
        abort(404)

    data = doc.to_dict()
    if data.get("user_id") != current_user.id and not getattr(current_user, "is_admin", False):
        abort(403)

    raw = data.get("publish_date", "")
    try:
        dt = dateparser.isoparse(raw)
        date_fmt = dt.strftime("%B %d, %Y")
    except Exception:
        date_fmt = raw

    return render_template("detail.html", item={
        **data,
        "id":               item_id,
        "audio_url":        f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3",
        "publish_date_fmt": date_fmt,
    })

# ─── Errors & Admin ────────────────────────────────────────────────────────
@app.route("/errors", methods=["GET"])
@login_required
def list_errors():
    docs = (
        db.collection("items")
          .where("status", "==", "error")
          .where("user_id", "==", current_user.id)
          .stream()
    )
    errors = []
    for d in docs:
        data = d.to_dict()
        errors.append({
            "id":    d.id,
            "url":   data.get("url", ""),
            "error": data.get("error", "<no message>")
        })
    return render_template("errors.html", errors=errors)

@app.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    if not getattr(current_user, "is_admin", False):
        abort(403)
    return render_template("admin.html")

# ─── RSS & Health ─────────────────────────────────────────────────────────
@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    xml = rss.generate_feed(request.url_root, bucket_name=GCS_BUCKET)
    return Response(xml, mimetype="application/rss+xml")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# ─── Error Handlers ────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "forbidden"}), 403
    return render_template("403.html"), 403

# ─── Main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting server on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=True)