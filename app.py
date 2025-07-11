import logging
import json
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, flash, Response, Blueprint, current_app
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from flask_talisman import Talisman
from flask_caching import Cache
from google.api_core.exceptions import FailedPrecondition
from google.cloud import firestore

# --- Local Imports ---
from config import config
from gcp import db, storage_client, bucket, create_processing_task
from your_user_module import User
from processing import process_article_submission
from rss import generate_feed

# --- Blueprints ---
main_bp = Blueprint('main', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- Login Setup ---
login_manager = LoginManager()
login_manager.login_view = "main.login"
login_manager.login_message_category = "error"

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- Helpers & Decorators ---
def _doc_to_dict(doc):
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    submitted_at = d.get("submitted_at")
    if hasattr(submitted_at, "to_datetime"):
        d["submitted_at_fmt"] = submitted_at.to_datetime().strftime("%Y-%m-%d %H:%M")
    elif isinstance(submitted_at, datetime):
        d["submitted_at_fmt"] = submitted_at.strftime("%Y-%m-%d %H:%M")
    else:
        d["submitted_at_fmt"] = "—"
    publish_date = d.get("publish_date")
    if isinstance(publish_date, datetime):
        d["publish_date_fmt"] = publish_date.strftime("%Y-%m-%d")
    else:
        d["publish_date_fmt"] = "N/A"
    return d

def api_success(data=None, message="", code=200):
    response = {"success": True}
    if data is not None:
        response["data"] = data
    if message:
        response["message"] = message
    return jsonify(response), code

def api_error(message, code=400):
    logging.error(f"API Error ({code}): {message}")
    return jsonify({"success": False, "error": {"message": message}}), code

def _generate_signed_url(blob_name):
    if not bucket or not blob_name:
        return None
    try:
        blob = bucket.blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=60),
            method="GET"
        )
    except Exception as e:
        logging.error(f"Error generating signed URL for {blob_name}: {e}", exc_info=True)
        return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            if request.path.startswith('/admin/'):
                return api_error("Admin access required.", 403)
            flash("Admin access required.", "error")
            return redirect(url_for("main.home"))
        return f(*args, **kwargs)
    return decorated_function

def get_item_or_abort(f):
    @wraps(f)
    def decorated_function(item_id, *args, **kwargs):
        doc_ref = db.collection("items").document(item_id)
        doc = doc_ref.get()
        if not doc.exists:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return api_error("Item not found", 404)
            return render_template("404.html"), 404
        
        item_user_id = doc.to_dict().get("user_id")
        is_admin = getattr(current_user, "is_admin", False)
        if not is_admin and item_user_id != current_user.id:
             if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return api_error("Forbidden", 403)
             return render_template("403.html"), 403

        kwargs['doc_ref'] = doc_ref
        kwargs['doc'] = doc
        return f(item_id, *args, **kwargs)
    return decorated_function

# --- Main Routes ---
@main_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.submit_url"))
    return render_template("index.html")

@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.submit_url"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.authenticate(username, password)
        if user:
            login_user(user)
            logging.info(f"User {user.id} logged in successfully.")
            flash("Login successful.", "success")
            return redirect(request.args.get("next") or url_for("main.submit_url"))
        else:
            logging.warning(f"Failed login attempt for username: {username}")
            flash("Invalid login.", "error")
    return render_template("login.html")

@main_bp.route("/logout")
@login_required
def logout():
    logging.info(f"User {current_user.id} logged out.")
    logout_user()
    flash("You have been successfully logged out.", "success")
    return redirect(url_for("main.home"))

@main_bp.route("/submit", methods=["GET", "POST"])
@login_required
def submit_url():
    if request.method == "GET":
        return render_template("submit.html", voices=current_app.config["ALLOWED_VOICES"], default_voice=current_app.config["DEFAULT_VOICE"])

    # POST request handling
    data = request.get_json()
    if not data:
        return api_error("Invalid JSON payload.", 400)
        
    url = data.get("url", "").strip()
    if not url:
        return api_error("URL is required.")
    
    voice = data.get("voice", current_app.config["DEFAULT_VOICE"])
    tags = [t.strip() for t in data.get("tags", "").split(",") if t.strip()]
    
    doc_ref = db.collection("items").document()
    item_id = doc_ref.id
    
    try:
        doc_ref.set({
            "id": item_id, "user_id": current_user.id, "url": url,
            "title": "Pending Extraction...", "status": "queued", "voice": voice,
            "tags": tags, "submitted_at": datetime.now(timezone.utc),
            "submitted_ip": request.remote_addr
        })
        
        logging.info(f"New article submitted by {current_user.id}: {url}")

        if not create_processing_task(item_id):
            logging.warning(f"Task creation failed for {item_id}. Falling back to synchronous processing.")
            process_article_submission(doc_ref, url, voice)
            
        return api_success(
            data={"redirect": url_for("main.list_items")},
            message="Your article has been successfully submitted!"
        )
    except Exception as e:
        logging.error(f"Error in submit_url: {e}", exc_info=True)
        doc_ref.update({"status": "error", "error_message": str(e)})
        return api_error(str(e), 500)

@main_bp.route("/items")
@login_required
def list_items():
    items_ref = db.collection("items").where("user_id", "==", current_user.id).order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(50)
    result = [_doc_to_dict(doc) for doc in items_ref.stream()]
    return render_template("items.html", items=result)

@main_bp.route("/item/<item_id>")
@login_required
@get_item_or_abort
def item_detail(item_id, doc_ref, doc):
    item = doc.to_dict()
    item['id'] = item_id
    if gcs_path := item.get("gcs_path"):
        item["audio_url"] = _generate_signed_url(gcs_path)
    
    full_text = item.get('text', '')
    paragraphs = [p.strip() for p in full_text.split('\n\n') if p.strip()]
    return render_template("item_detail.html", item=item, paragraphs=paragraphs)

@main_bp.route("/feed.xml")
@login_required
def podcast_feed():
    app_config = {"APP_URL_ROOT": request.url_root, "GCS_BUCKET_NAME": current_app.config["GCS_BUCKET_NAME"]}
    feed_xml = generate_feed(db, storage_client, app_config)
    return Response(feed_xml, mimetype='application/rss+xml')

@main_bp.route("/item/<item_id>/tags", methods=["POST"])
@login_required
@get_item_or_abort
def update_tags(item_id, doc_ref, doc):
    try:
        tags_str = request.form.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        doc_ref.update({"tags": tags})
        flash("Tags updated.", "success")
    except Exception as e:
        logging.error(f"Error updating tags for item {item_id}: {e}", exc_info=True)
        flash("Failed to update tags.", "error")
    return redirect(url_for("main.item_detail", item_id=item_id))

# --- Admin Routes ---
@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    page_size = 25
    try:
        page = int(request.args.get("page", 1))
        if page < 1: page = 1
    except ValueError:
        page = 1

    items = []
    next_page = None
    try:
        offset = (page - 1) * page_size
        query = db.collection("items").order_by("submitted_at", direction=firestore.Query.DESCENDING)
        paged_query = query.limit(page_size + 1).offset(offset)
        items = [_doc_to_dict(doc) for doc in paged_query.stream()]

        if len(items) > page_size:
            next_page = page + 1
            items = items[:page_size]

        for item in items:
            item["storage_bytes"] = item.get("storage_bytes", "—")
            item["error_message"] = item.get("error_message", None)
            item["extract_status"] = item.get("extract_status", None)

    except FailedPrecondition as e:
        logging.error(f"Firestore index missing or permission error in admin_dashboard: {e}", exc_info=True)
        flash(f"Database query failed, likely due to a missing Firestore index. Please check the application logs for an index creation link. Error: {e}", "error")
    except Exception as e:
        logging.error(f"Error fetching admin dashboard data: {e}", exc_info=True)
        flash("Error fetching articles. Please try again later.", "error")

    prev_page = page - 1 if page > 1 else None

    return render_template(
        "admin.html",
        items=items,
        page=page,
        prev_page=prev_page,
        next_page=next_page,
        page_size=page_size
    )

@admin_bp.route("/reprocess/<item_id>", methods=["POST"])
@login_required
@admin_required
@get_item_or_abort
def reprocess_item(item_id, doc_ref, doc):
    logging.info(f"Admin {current_user.id} triggered reprocess for item: {item_id}")
    try:
        item = doc.to_dict()
        url = item.get("url")
        voice = item.get("voice", current_app.config["DEFAULT_VOICE"])
        doc_ref.update({"status": "reprocessing", "error_message": None})
        process_article_submission(doc_ref, url, voice)
        return api_success(message=f"Item {item_id} is being reprocessed.")
    except Exception as e:
        error_message = f"Reprocess failed for item {item_id}: {e}"
        logging.error(error_message, exc_info=True)
        try:
            doc_ref.update({"status": "error", "error_message": str(e)})
        except Exception as update_err:
            logging.error(f"Error updating doc after reprocess failure: {update_err}")
        return api_error(str(e), 500)

@admin_bp.route("/delete/<item_id>", methods=["POST"])
@login_required
@admin_required
@get_item_or_abort
def delete_item(item_id, doc_ref, doc):
    logging.info(f"Admin {current_user.id} triggered delete for item: {item_id}")
    try:
        gcs_path = doc.to_dict().get("gcs_path")
        if gcs_path:
            blob = bucket.blob(gcs_path)
            if blob.exists():
                blob.delete()
                logging.info(f"Deleted GCS file: {gcs_path}")

        doc_ref.delete()
        logging.info(f"Deleted Firestore document: {item_id}")
        
        return api_success(message=f"Item {item_id} and associated file deleted.")
    except Exception as e:
        error_message = f"Delete failed for item {item_id}: {e}"
        logging.error(error_message, exc_info=True)
        return api_error(str(e), 500)

@admin_bp.route("/retry/<item_id>", methods=["POST"])
@login_required
@admin_required
def retry_item(item_id):
    # This is identical to reprocess, so we can just call that function
    return reprocess_item(item_id)

@admin_bp.route("/bulk", methods=["POST"])
@login_required
@admin_required
def bulk_action():
    data = request.get_json()
    action = data.get("action")
    ids = data.get("ids")

    if not action or not ids:
        return api_error("Missing 'action' or 'ids' in request.", 400)

    logging.info(f"Admin {current_user.id} triggered bulk action '{action}' for items: {', '.join(ids)}")
    results = {}
    for item_id in ids:
        try:
            doc_ref = db.collection("items").document(item_id)
            doc = doc_ref.get()
            if not doc.exists:
                results[item_id] = "Failed: Not Found"
                continue

            if action == "delete":
                gcs_path = doc.to_dict().get("gcs_path")
                if gcs_path:
                    blob = bucket.blob(gcs_path)
                    if blob.exists():
                        blob.delete()
                doc_ref.delete()
                results[item_id] = "Success"
            elif action == "retry":
                item = doc.to_dict()
                url = item.get("url")
                voice = item.get("voice", current_app.config["DEFAULT_VOICE"])
                doc_ref.update({"status": "reprocessing", "error_message": None})
                process_article_submission(doc_ref, url, voice)
                results[item_id] = "Success"
            else:
                return api_error(f"Unknown bulk action: {action}", 400)
        except Exception as e:
            results[item_id] = f"Failed: {str(e)}"
            logging.error(f"Bulk action '{action}' failed for item {item_id}: {e}", exc_info=True)
            
    return api_success(data={"results": results})

@admin_bp.route("/retry-stuck", methods=["POST"])
@login_required
@admin_required
def retry_stuck_items():
    try:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        stuck_items_query = db.collection("items").where("status", "==", "processing").where("submitted_at", "<=", one_hour_ago).order_by("submitted_at", direction=firestore.Query.ASCENDING)
        
        stuck_items = stuck_items_query.stream()
        
        count = 0
        for item_doc in stuck_items:
            item_id = item_doc.id
            doc_ref = item_doc.reference
            item = item_doc.to_dict()
            logging.info(f"Retrying stuck item: {item_id}")
            
            try:
                url = item.get("url")
                voice = item.get("voice", current_app.config["DEFAULT_VOICE"])
                doc_ref.update({"status": "reprocessing", "error_message": None})
                process_article_submission(doc_ref, url, voice)
                count += 1
            except Exception as e:
                logging.error(f"Failed to retry item {item_id} during stuck-item-retry: {e}", exc_info=True)

        return api_success(message=f"Attempted to retry {count} stuck item(s).")
    except Exception as e:
        logging.error(f"Failed to query for stuck items: {e}", exc_info=True)
        return api_error(str(e), 500)

@admin_bp.route("/failed-articles")
@login_required
@admin_required
def failed_articles():
    try:
        items_ref = db.collection("items").where("status", "==", "error").order_by("submitted_at", direction=firestore.Query.DESCENDING)
        errors = [_doc_to_dict(doc) for doc in items_ref.stream()]
        return render_template("failed_articles.html", errors=errors)
    except FailedPrecondition as e:
        logging.error(f"Firestore index missing or permission error in failed_articles: {e}", exc_info=True)
        flash(f"Database query failed, likely due to a missing Firestore index. Please check the application logs for an index creation link. Error: {e}", "error")
        return redirect(url_for("admin.dashboard"))
    except Exception as e:
        logging.error(f"Error fetching failed articles: {e}", exc_info=True)
        flash("Could not fetch failed articles.", "error")
        return redirect(url_for("admin.dashboard"))



# --- Task Handler ---
@main_bp.route("/task-handler", methods=["POST"])
def task_handler():
    data = request.get_json()
    if not data or not (item_id := data.get("item_id")):
        return api_error("item_id is required", 400)
    
    doc_ref = db.collection("items").document(item_id)
    doc = doc_ref.get()
    if not doc.exists:
        # Acknowledge the task by returning 200 even if item is not found,
        # to prevent Cloud Tasks from retrying a non-existent item.
        logging.warning(f"Task handler received non-existent item_id: {item_id}. Task will be acknowledged.")
        return api_success(message=f"Item {item_id} not found, task acknowledged.", code=200)

    item = doc.to_dict()
    try:
        doc_ref.update({"status": "processing"})
        process_article_submission(doc_ref, item.get("url"), item.get("voice", current_app.config["DEFAULT_VOICE"]))
        return api_success(message=f"Successfully processed item {item_id}.")
    except Exception as e:
        logging.error(f"Task handler failed for item {item_id}: {e}", exc_info=True)
        doc_ref.update({"status": "error", "error_message": str(e)})
        # Return 500 to signal Cloud Tasks to retry the task.
        return api_error(str(e), 500)

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config)
    
    # --- Logging ---
    logging.basicConfig(level=app.config["LOG_LEVEL"], format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

    # --- Security ---
    if not app.config["DEBUG"]:
        Talisman(app, content_security_policy=None)

    # --- Caching ---
    Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
    
    # --- Login Manager ---
    login_manager.init_app(app)
    
    # --- Register Blueprints ---
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    return app