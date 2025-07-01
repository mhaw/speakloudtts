import logging
import os
import sys
from datetime import datetime

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, flash
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)

from google.cloud import firestore, storage, tasks_v2
from google.auth.exceptions import DefaultCredentialsError

from your_user_module import User
from extractor import extract_article
from tts import synthesize_long_text

# --- Logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- Flask Setup ---
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "your_default_secret_key_here")

# --- Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "error"

# --- Constants ---
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
ALLOWED_VOICES = [
    "en-US-Standard-C", "en-US-Standard-D", "en-GB-Standard-A",
    "en-AU-Standard-B", "en-US-Wavenet-D", "en-US-Wavenet-F",
]
DEFAULT_VOICE = ALLOWED_VOICES[0]

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION_ID = os.getenv("GCP_LOCATION_ID")
TTS_TASK_QUEUE_ID = os.getenv("TTS_TASK_QUEUE_ID")
TTS_TASK_HANDLER_URL = os.getenv("TTS_TASK_HANDLER_URL")
TTS_TASK_SERVICE_ACCOUNT_EMAIL = os.getenv("TTS_TASK_SERVICE_ACCOUNT_EMAIL")

def get_build_id():
    try:
        with open("/app/BUILD_INFO") as f:
            return f.read().strip()
    except Exception:
        return "unknown"

logging.info(f"SpeakLoudTTS Starting (build: {get_build_id()})")

@app.context_processor
def inject_build_id():
    return {"build_id": get_build_id()}

# --- GCP Setup ---
try:
    db = firestore.Client()
    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    tasks_client = (
        tasks_v2.CloudTasksClient()
        if GCP_PROJECT_ID and GCP_LOCATION_ID and TTS_TASK_QUEUE_ID
        else None
    )
    if not tasks_client:
        logger.warning("Cloud Tasks client not initialized. Running in inline processing mode.")
except DefaultCredentialsError as e:
    logger.error(f"GCP credentials error: {e}")
    db = storage_client = bucket = tasks_client = None
except Exception as e:
    logger.error(f"Failed to initialize Google Cloud clients: {e}", exc_info=True)
    db = storage_client = bucket = tasks_client = None

# --- Login loader ---
@login_manager.user_loader
def load_user(user_id):
    logger.debug(f"Loading user: {user_id}")
    return User.get(user_id)

# --- Auth routes ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("submit_url"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.authenticate(username, password)
        if user:
            login_user(user)
            return redirect(request.args.get("next") or url_for("submit_url"))
        else:
            logger.warning(f"Failed login attempt for user: {username}")
            flash("Invalid login.", "error")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
def home():
    return render_template("index.html")

# --- Submit route ---
@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit_url():
    if db is None:
        logger.error("Database client is not initialized.")
        return jsonify({"error": "Database not initialized"}), 500

    if request.method == "GET":
        return render_template("submit.html", voices=ALLOWED_VOICES, default_voice=DEFAULT_VOICE)

    url = request.form.get("url", "").strip()
    voice = request.form.get("voice", DEFAULT_VOICE)
    tags_input = request.form.get("tags", "")
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    if not url:
        logger.error("URL missing in form submission.")
        return jsonify({"error": "URL is required."}), 400

    logger.info(f"Inline processing triggered for URL: {url} by user: {current_user.id}")

    try:
        doc_ref = db.collection("items").document()
        item_id = doc_ref.id

        doc_ref.set({
            "id": item_id, "user_id": current_user.id, "url": url,
            "title": "Pending Extraction...", "status": "processing", "voice": voice,
            "tags": tags, "submitted_at": firestore.SERVER_TIMESTAMP,
            "submitted_ip": request.remote_addr, "error_message": None
        })

        meta = extract_article(url)
        text = meta.get("text", "")
        if not text:
            raise ValueError("No article text extracted.")

        doc_ref.update({
            "title": meta.get("title", "Untitled"),
            "author": meta.get("author", "Unknown"),
            "text": text,
            "text_preview": text[:200],
            "word_count": len(text.split()),
            "reading_time_min": max(1, len(text.split()) // 200),
            "publish_date": meta.get("publish_date", None),
            "favicon_url": meta.get("favicon_url", ""),
            "publisher": meta.get("publisher", ""),
            "section": meta.get("section", ""),
            "domain": meta.get("domain", ""),
        })

        tts_result = synthesize_long_text(
            meta.get("title"), meta.get("author"), text, item_id, voice
        )

        if tts_result.get("error"):
            raise RuntimeError(tts_result["error"])

        audio_uri = tts_result.get("uri")
        doc_ref.update({
            "status": "done",
            "audio_url": audio_uri,
            "processed_at": firestore.SERVER_TIMESTAMP
        })

        return redirect(url_for("list_items"))

    except Exception as e:
        logger.error(f"Inline processing failed: {e}", exc_info=True)
        if 'item_id' in locals():
            try:
                doc_ref.update({"status": "error", "error_message": str(e)})
            except Exception as update_err:
                logger.error(f"Error updating doc with failure status: {update_err}")
        return jsonify({"error": str(e)}), 500

# --- List items ---
@app.route("/items")
@login_required
def list_items():
    try:
        items = db.collection("items") \
            .where("user_id", "==", current_user.id) \
            .order_by("submitted_at", direction=firestore.Query.DESCENDING) \
            .limit(50)
        result = []
        for doc in items.stream():
            d = doc.to_dict()
            d["id"] = doc.id
            submitted_at = d.get("submitted_at")
            if hasattr(submitted_at, "to_datetime"):
                d["submitted_at_fmt"] = submitted_at.to_datetime().strftime("%Y-%m-%d %H:%M")
            elif isinstance(submitted_at, datetime):
                d["submitted_at_fmt"] = submitted_at.strftime("%Y-%m-%d %H:%M")
            elif isinstance(submitted_at, str):
                d["submitted_at_fmt"] = submitted_at[:16]
            else:
                d["submitted_at_fmt"] = "—"
            result.append(d)
        return render_template("items.html", items=result)
    except Exception as e:
        logger.error(f"Error listing items: {e}", exc_info=True)
        return jsonify({"error": "Could not fetch items"}), 500

# --- Tag edit (form POST) ---
@app.route("/item/<item_id>/tags", methods=["POST"])
@login_required
def update_tags(item_id):
    try:
        doc_ref = db.collection("items").document(item_id)
        tags_str = request.form.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        doc_ref.update({"tags": tags})
        flash("Tags updated.", "success")
    except Exception as e:
        logger.error(f"Error updating tags for item {item_id}: {e}", exc_info=True)
        flash("Failed to update tags.", "error")
    return redirect(url_for("item_detail", item_id=item_id))

# --- Item detail (render text as paragraphs, handle tags) ---
@app.route("/item/<item_id>")
@login_required
def item_detail(item_id):
    doc = db.collection("items").document(item_id).get()
    if not doc.exists:
        return "Not found", 404
    item = doc.to_dict()
    item['id'] = item_id
    full_text = item.get('text') or item.get('text_preview') or ""
    paragraphs = [p.strip() for p in full_text.split('\n\n') if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in full_text.splitlines() if p.strip()]
    tags = item.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return render_template("item_detail.html", item=item, paragraphs=paragraphs, tags=tags)

# --- Health check ---
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "db": bool(db),
        "tasks": bool(tasks_client)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)