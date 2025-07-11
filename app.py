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
from flask_talisman import Talisman
from flask_caching import Cache

from google.cloud import firestore, storage, tasks_v2
from google.auth.exceptions import DefaultCredentialsError
from google.api_core.exceptions import FailedPrecondition

from your_user_module import User
from extractor import extract_article
from tts import synthesize_long_text
from flask import Response
from rss import generate_feed  # make sure this import is correct!

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

# --- Security & Caching ---
csp = {
    'default-src': "'self'",
    'style-src': [
        "'self'",
        'https://fonts.googleapis.com',
        'https://cdn.jsdelivr.net' # Required for DaisyUI from CDN if not local
    ],
    'font-src': [
        "'self'",
        'https://fonts.gstatic.com'
    ],
    'script-src': [
        "'self'",
        'https://cdn.tailwindcss.com' # Required for Tailwind JIT from CDN
    ]
}
if os.getenv("FLASK_ENV") != "development":
    talisman = Talisman(app, content_security_policy=csp)
else:
    app.config["TALISMAN_ENABLED"] = False
    talisman = Talisman(app, content_security_policy=None)

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

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

# --- Helpers & Decorators ---
def _doc_to_dict(doc):
    """Converts a Firestore doc to a dict, adding id and formatted dates."""
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    
    # Format submitted_at
    submitted_at = d.get("submitted_at")
    if hasattr(submitted_at, "to_datetime"):
        d["submitted_at_fmt"] = submitted_at.to_datetime().strftime("%Y-%m-%d %H:%M")
    elif isinstance(submitted_at, datetime):
        d["submitted_at_fmt"] = submitted_at.strftime("%Y-%m-%d %H:%M")
    else:
        d["submitted_at_fmt"] = "—"
        
    # Format publish_date
    publish_date = d.get("publish_date")
    if isinstance(publish_date, datetime):
        d["publish_date_fmt"] = publish_date.strftime("%Y-%m-%d")
    else:
        d["publish_date_fmt"] = "N/A"
        
    return d

from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            if request.path.startswith('/api/') or request.is_json:
                 return jsonify({"error": "Admin access required."}), 403
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function


def _api_error(message, code=400):
    """Returns a standardized JSON error response."""
    logger.error(f"API Error ({code}): {message}")
    return jsonify({"success": False, "error": message}), code


# --- Task Handler ---
@app.route("/task-handler", methods=["POST"])
def task_handler():
    """
    This endpoint is called by Cloud Tasks to process an article.
    It's protected by OIDC authentication from Cloud Tasks.
    """
    if db is None:
        return _api_error("Database not initialized", 500)

    try:
        # Get item_id from request body
        data = request.get_json()
        item_id = data.get("item_id")
        if not item_id:
            return _api_error("item_id is required in task payload", 400)

        logger.info(f"[Task Handler] Received task for item_id: {item_id}")

        # Fetch the document
        doc_ref = db.collection("items").document(item_id)
        doc = doc_ref.get()
        if not doc.exists:
            return _api_error(f"Item with id {item_id} not found.", 404)

        item = doc.to_dict()
        url = item.get("url")
        voice = item.get("voice", DEFAULT_VOICE)

        # Mark as processing
        doc_ref.update({"status": "processing"})

        # Process the article
        _process_article_submission(doc_ref, url, voice)

        logger.info(f"[Task Handler] Successfully processed item_id: {item_id}")
        return jsonify({"success": True}), 200

    except Exception as e:
        error_message = f"[Task Handler] Processing failed for item_id {item_id}: {e}"
        logger.error(error_message, exc_info=True)
        
        # Try to update the doc with the error, but handle failure gracefully
        if 'item_id' in locals() and item_id:
            try:
                db.collection("items").document(item_id).update({
                    "status": "error",
                    "error_message": str(e)
                })
            except Exception as update_err:
                logger.error(f"Failed to update error status for item_id {item_id}: {update_err}")
        
        # Return a 500 to signal Cloud Tasks to potentially retry
        return _api_error(str(e), 500)


def _process_article_submission(doc_ref, url, voice):
    """
    Extracts article, synthesizes audio, and updates Firestore doc.
    Raises exceptions on failure.
    """
    item_id = doc_ref.id
    logger.info(f"Processing article for item_id: {item_id}, url: {url}")

    # 1. Extract article content
    meta = extract_article(url)
    text = meta.get("text", "")
    
    update_data = {
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
        "extract_status": meta.get("extract_status", None),
        "error_message": meta.get("error", None)
    }
    doc_ref.update(update_data)

    if not text or meta.get("error"):
        raise ValueError(f"Article extraction failed: {meta.get('error', 'No text found.')}")

    # 2. Synthesize audio
    tts_result = synthesize_long_text(
        meta.get("title"), meta.get("author"), text, item_id, voice
    )
    if tts_result.get("error"):
        raise RuntimeError(f"TTS synthesis failed: {tts_result['error']}")

    # 3. Finalize document
    audio_uri = tts_result.get("uri")
    doc_ref.update({
        "status": "done",
        "audio_url": audio_uri,
        "processed_at": firestore.SERVER_TIMESTAMP,
        "error_message": None  # Clear previous errors
    })
    logger.info(f"Successfully processed item {item_id}")


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

# --- Admin Page: All Articles ---
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    page_size = 25
    try:
        page = int(request.args.get("page", 1))
        if page < 1: page = 1
    except ValueError:
        page = 1

    try:
        # Base query
        query = db.collection("items").order_by("submitted_at", direction=firestore.Query.DESCENDING)

        # Get total count efficiently
        aggregation_query = query.count()
        count_result = aggregation_query.get()
        total_count = count_result[0][0].value

        # Paginate the query
        offset = (page - 1) * page_size
        paged_query = query.limit(page_size).offset(offset)
        
        items = [_doc_to_dict(doc) for doc in paged_query.stream()]
        
        # Enhance items with admin-specific fields
        for item in items:
            item["storage_bytes"] = item.get("storage_bytes", "—")
            item["error_message"] = item.get("error_message", None)
            item["extract_status"] = item.get("extract_status", None)

    except FailedPrecondition as e:
        logger.error(f"Firestore index missing or permission error in admin_dashboard: {e}", exc_info=True)
        items = []
        total_count = 0
        flash(f"Database query failed, likely due to a missing Firestore index. Please check the application logs for an index creation link. Error: {e}", "error")
    except Exception as e:
        logger.error(f"Error fetching admin dashboard data: {e}", exc_info=True)
        items = []
        total_count = 0
        flash("Error fetching articles. Please try again later.", "error")

    prev_page = page - 1 if page > 1 else None
    next_page = page + 1 if (page * page_size) < total_count else None

    return render_template(
        "admin.html",
        items=items,
        total_count=total_count,
        page=page,
        prev_page=prev_page,
        next_page=next_page,
        page_size=page_size,
        error=None # Already handled by flash
    )


# --- Admin Action: Retry Extraction/Processing ---
@app.route("/admin/reprocess/<item_id>", methods=["POST"])
@login_required
@admin_required
def admin_reprocess_item(item_id):
    doc_ref = db.collection("items").document(item_id)
    try:
        doc = doc_ref.get()
        if not doc.exists:
            return _api_error("Item not found", 404)

        d = doc.to_dict()
        url = d.get("url")
        voice = d.get("voice", DEFAULT_VOICE)

        logger.info(f"[ADMIN] Reprocessing item {item_id} (url: {url})")
        doc_ref.update({"status": "processing", "error_message": None})

        _process_article_submission(doc_ref, url, voice)

        return jsonify({"success": True})
    except Exception as e:
        error_message = f"Reprocess failed for item {item_id}: {e}"
        logger.error(error_message, exc_info=True)
        try:
            doc_ref.update({"status": "error", "error_message": str(e)})
        except Exception as update_err:
            logger.error(f"Error updating doc after reprocess failure: {update_err}")
        return _api_error(str(e), 500)


# --- API for Admin DataTable (JS/AJAX) ---
@app.route("/api/admin/items")
@login_required
@admin_required
def api_admin_items():
    try:
        items_ref = db.collection("items").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(500)
        result = [_doc_to_dict(doc) for doc in items_ref.stream()]
        return jsonify({"items": result})
    except Exception as e:
        logger.error(f"Error in api_admin_items: {e}", exc_info=True)
        return _api_error(str(e), 500)

@app.route('/feed.xml')
@cache.cached(timeout=300)  # Cache this view for 5 minutes
def podcast_feed():
    app_config = {
        "APP_URL_ROOT": request.url_root,
        "GCS_BUCKET_NAME": GCS_BUCKET_NAME
    }
    feed_xml = generate_feed(db, storage_client, app_config)
    return Response(feed_xml, mimetype='application/rss+xml')

# --- Submit route ---
@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit_url():
    if db is None:
        return _api_error("Database not initialized", 500)

    if request.method == "GET":
        return render_template("submit.html", voices=ALLOWED_VOICES, default_voice=DEFAULT_VOICE)

    # POST request
    data = request.get_json()
    if not data:
        return _api_error("Invalid request.", 400)

    url = data.get("url", "").strip()
    if not url:
        return _api_error("URL is required.", 400)

    voice = data.get("voice", DEFAULT_VOICE)
    tags_input = data.get("tags", "")
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    logger.info(f"Submission received for URL: {url} by user: {current_user.id}")

    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    try:
        # Create initial document
        doc_ref.set({
            "id": item_id, "user_id": current_user.id, "url": url,
            "title": "Pending Extraction...", "status": "queued", "voice": voice,
            "tags": tags, "submitted_at": firestore.SERVER_TIMESTAMP,
            "submitted_ip": request.remote_addr, "error_message": None
        })

        # If Cloud Tasks is configured, create a task. Otherwise, process inline.
        if tasks_client:
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": TTS_TASK_HANDLER_URL,
                    "headers": {"Content-Type": "application/json"},
                    "body": jsonify({"item_id": item_id}).data,
                    "oidc_token": {
                        "service_account_email": TTS_TASK_SERVICE_ACCOUNT_EMAIL,
                    },
                }
            }
            parent = tasks_client.queue_path(GCP_PROJECT_ID, GCP_LOCATION_ID, TTS_TASK_QUEUE_ID)
            tasks_client.create_task(parent=parent, task=task)
            logger.info(f"Created Cloud Task for item_id: {item_id}")
        else:
            # Fallback to inline processing if Cloud Tasks is not set up
            logger.warning(f"Processing item inline (no Cloud Tasks): {item_id}")
            _process_article_submission(doc_ref, url, voice)

        return jsonify({"success": True, "redirect": url_for("list_items")})

    except Exception as e:
        error_message = f"Processing failed for {url}: {e}"
        logger.error(error_message, exc_info=True)
        try:
            doc_ref.update({"status": "error", "error_message": str(e)})
        except Exception as update_err:
            logger.error(f"Error updating doc with failure status: {update_err}")
        
        return _api_error(str(e), 500)

# --- List items ---
@app.route("/items")
@login_required
def list_items():
    try:
        items_ref = db.collection("items")             .where("user_id", "==", current_user.id)             .order_by("submitted_at", direction=firestore.Query.DESCENDING)             .limit(50)
        
        result = [_doc_to_dict(doc) for doc in items_ref.stream()]

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
    is_authenticated = current_user.is_authenticated if hasattr(current_user, "is_authenticated") else False
    return render_template(
        "item_detail.html",
        item=item,
        paragraphs=paragraphs,
        tags=tags,
        is_authenticated=is_authenticated
    )

# --- Health check ---
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "db": bool(db),
        "tasks": bool(tasks_client)
    })

# This is a new route to display articles that failed processing
@app.route("/failed-articles")
@login_required
@admin_required
def failed_articles():
    try:
        items_ref = db.collection("items").where("status", "==", "error").order_by("submitted_at", direction=firestore.Query.DESCENDING)
        errors = [_doc_to_dict(doc) for doc in items_ref.stream()]
        return render_template("failed_articles.html", errors=errors)
    except FailedPrecondition as e:
        logger.error(f"Firestore index missing or permission error in failed_articles: {e}", exc_info=True)
        flash(f"Database query failed, likely due to a missing Firestore index. Please check the application logs for an index creation link. Error: {e}", "error")
        return redirect(url_for("admin_dashboard"))
    except Exception as e:
        logger.error(f"Error fetching failed articles: {e}", exc_info=True)
        flash("Could not fetch failed articles.", "error")
        return redirect(url_for("admin_dashboard"))

# --- Error Handlers ---
@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 Not Found: {request.path}")
    return render_template("404.html"), 404


@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    if request.path.startswith('/api/') or request.is_json:
        return _api_error("An internal error occurred.", 500)
    return render_template("generic_error.html", error_message=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)