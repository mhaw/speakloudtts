import logging
import os
import sys
import json # For Cloud Tasks payload
from datetime import datetime, timezone # Ensure timezone for datetime objects

from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from google.cloud import firestore
from google.cloud import storage
from google.cloud import tasks_v2  # Added for Cloud Tasks
from google.protobuf import duration_pb2, timestamp_pb2  # For Cloud Tasks scheduling
from dateutil import parser as dateparser

# Assuming these custom modules are in the same directory or accessible via PYTHONPATH
from your_user_module import User # implements User.get() and User.authenticate()
from extractor import extract_article #
from tts import synthesize_long_text #
import rss as rss_generator #

# ─── Logging Configuration (from Phase 1) ─────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ─── App & Login Setup ─────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static") #
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "your_default_secret_key_here")

login_manager = LoginManager() #
login_manager.init_app(app) #
login_manager.login_view = "login" #
login_manager.login_message_category = "error"


# ─── Configuration ──────────────────────────────────────────────────────────
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files") #
ALLOWED_VOICES = [ #
    "en-US-Standard-C", "en-US-Standard-D", "en-GB-Standard-A",
    "en-AU-Standard-B", "en-US-Wavenet-D",  "en-US-Wavenet-F",
]
DEFAULT_VOICE = ALLOWED_VOICES[0] #

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION_ID = os.getenv("GCP_LOCATION_ID")
TTS_TASK_QUEUE_ID = os.getenv("TTS_TASK_QUEUE_ID")
TTS_TASK_HANDLER_URL = os.getenv("TTS_TASK_HANDLER_URL")
TTS_TASK_SERVICE_ACCOUNT_EMAIL = os.getenv("TTS_TASK_SERVICE_ACCOUNT_EMAIL")


# ─── Google Cloud Clients ────────────────────────────────────────────────────
try:
    db = firestore.Client() #
    storage_client = storage.Client() #
    bucket = storage_client.bucket(GCS_BUCKET_NAME) #
    tasks_client = tasks_v2.CloudTasksClient() if GCP_PROJECT_ID and GCP_LOCATION_ID and TTS_TASK_QUEUE_ID else None
    if not tasks_client:
        logger.warning("Cloud Tasks client not initialized. Ensure GCP_PROJECT_ID, GCP_LOCATION_ID, and TTS_TASK_QUEUE_ID are set.")
except Exception as e:
    logger.error(f"Failed to initialize Google Cloud clients: {e}", exc_info=True)
    db = None
    storage_client = None
    bucket = None
    tasks_client = None

# ─── Flask-Login User Loader ────────────────────────────────────────────────
@login_manager.user_loader #
def load_user(user_id): #
    logger.debug(f"Attempting to load user with ID: {user_id}")
    user = User.get(user_id) #
    if user:
        logger.debug(f"User {user_id} loaded successfully: {user.username}")
    else:
        logger.warning(f"User {user_id} not found during load_user.")
    return user

# ─── Public Routes ───────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"]) #
def login(): #
    if current_user.is_authenticated:
        logger.debug(f"User {current_user.username} already authenticated, redirecting from login page.")
        return redirect(url_for("submit_url"))
    if request.method == "POST":
        username = request.form.get("username", "").strip() #
        password = request.form.get("password", "") #
        logger.info(f"Login attempt for username: {username}")
        user = User.authenticate(username, password) #
        if user:
            login_user(user)
            logger.info(f"User '{username}' logged in successfully. ID: {user.id}")
            next_page = request.args.get("next")
            logger.debug(f"Redirecting to next_page: '{next_page}' or default 'submit_url' after login.")
            return redirect(next_page or url_for("submit_url"))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
    return render_template("login.html")

@app.route("/logout") #
@login_required #
def logout(): #
    user_id = current_user.id
    username = current_user.username # Store before logout
    logout_user() #
    logger.info(f"User '{username}' (ID: {user_id}) logged out successfully.")
    return redirect(url_for("login")) #

@app.route("/", methods=["GET"]) #
def home(): #
    logger.debug(f"Home page requested by user: {current_user.id if current_user.is_authenticated else 'Anonymous'}")
    return render_template("index.html") #

@app.route("/favicon.ico") #
def favicon(): #
    return app.send_static_file("favicon.ico")

@app.route("/service-worker.js") #
def service_worker(): #
    logger.debug("Service worker requested.")
    return app.send_static_file("service-worker.js")

# ─── Extraction Endpoint ─────────────────────────────────────────────────────
@app.route("/extract", methods=["GET", "POST"]) #
@login_required #
def extract_route(): #
    if request.method == "GET": #
        logger.debug(f"GET request to /extract by {current_user.id}, redirecting to submit_url.")
        return redirect(url_for("submit_url")) #

    data = request.get_json(silent=True) or {} #
    url = data.get("url", "").strip() #
    if not url:
        logger.warning(f"Extraction attempt by {current_user.id} with no URL provided.")
        return jsonify({"error": "URL is required."}), 400

    logger.info(f"Extraction requested for URL: '{url}' by user: {current_user.id}")
    try:
        meta = extract_article(url) #
        logger.info(f"Extraction successful for URL: '{url}'. Source: {meta.get('source', 'unknown')}, Title: '{meta.get('title', '')}'")
        return jsonify({ #
            "title": meta.get("title", ""),"author": meta.get("author", ""),
            "text": meta.get("text", ""),"publish_date": meta.get("publish_date", ""),
            "source": meta.get("source", "unknown")
        }), 200
    except Exception as e:
        logger.error(f"Extraction failed for URL: '{url}'. Error: {e}", exc_info=True)
        return jsonify({"title": "", "author": "", "text": "", "publish_date": "", "source": "error", "error": str(e)}), 200


# ─── Submit Route (Asynchronous) ───────────────────────────────────────
@app.route("/submit", methods=["GET", "POST"]) #
@login_required #
def submit_url(): #
    if request.method == "GET":
        logger.debug(f"Submit page (GET) requested by user: {current_user.id}")
        return render_template("submit.html", voices=ALLOWED_VOICES, default_voice=DEFAULT_VOICE)

    if not tasks_client:
        logger.error("Cloud Tasks client not available. Cannot process submission. Ensure GCP_PROJECT_ID, GCP_LOCATION_ID, TTS_TASK_QUEUE_ID are set.")
        return jsonify({"error": "Processing service temporarily unavailable. Please try again later."}), 503
    if not TTS_TASK_HANDLER_URL:
        logger.error("TTS Task Handler URL not configured (TTS_TASK_HANDLER_URL env var). Cannot process submission.")
        return jsonify({"error": "Processing service misconfigured. Please contact support."}), 500

    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "").strip() #
    voice = payload.get("voice_name", DEFAULT_VOICE) #
    text_from_payload = payload.get("text", "").strip()
    tags_input = payload.get("tags", []) #
    tags = [t.strip() for t in str(tags_input).split(',') if t.strip()] if isinstance(tags_input, str) else \
           [str(t).strip() for t in tags_input if str(t).strip()]
    
    logger.info(f"Submit POST request for URL: '{url}' by user: {current_user.id}. Voice: {voice}. Tags: {tags}. Payload keys: {list(payload.keys())}")


    if not url:
        logger.warning(f"Submit attempt by {current_user.id} with no URL.")
        return jsonify({"error": "Article URL is required"}), 400
    
    if voice not in ALLOWED_VOICES:
        logger.warning(f"Invalid voice '{voice}' submitted by {current_user.id}. Using default: {DEFAULT_VOICE}.")
        voice = DEFAULT_VOICE
    
    try:
        if not db:
            logger.critical("Submit: Firestore client 'db' not available.")
            raise ConnectionError("Firestore client not available.")

        doc_ref = db.collection("items").document() #
        item_id = doc_ref.id #

        initial_record = {
            "id": item_id, "user_id": current_user.id, "url": url,
            "title": "Pending Extraction...", "status": "pending", "voice": voice,
            "tags": tags, "submitted_at": firestore.SERVER_TIMESTAMP,
            "submitted_ip": request.remote_addr, "error_message": None,
            "text_source": "payload" if text_from_payload else "extractor",
        }
        doc_ref.set(initial_record)
        logger.info(f"Item {item_id} created with 'pending' status for URL: {url}")

        task_payload_dict = {
            "item_id": item_id, "url": url, "voice_name": voice,
            "text_from_payload": text_from_payload, "tags": tags,
            "user_id": current_user.id
        }

        parent = tasks_client.queue_path(GCP_PROJECT_ID, GCP_LOCATION_ID, TTS_TASK_QUEUE_ID)
        
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST, "url": TTS_TASK_HANDLER_URL,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(task_payload_dict).encode(),
            }
        }
        if TTS_TASK_SERVICE_ACCOUNT_EMAIL:
            task["http_request"]["oidc_token"] = {"service_account_email": TTS_TASK_SERVICE_ACCOUNT_EMAIL}
        
        task_response = tasks_client.create_task(request={"parent": parent, "task": task})
        logger.info(f"Created Cloud Task {task_response.name} for item {item_id}.")

        return jsonify({"message": "Article submitted for processing.", "item_id": item_id}), 202

    except Exception as e:
        logger.error(f"Error enqueuing TTS task for URL '{url}': {e}", exc_info=True)
        if 'item_id' in locals() and item_id and db: # Check db again
             db.collection("items").document(item_id).update({
                "status": "error", "error_message": f"Failed to enqueue task: {str(e)}",
                "processed_at": firestore.SERVER_TIMESTAMP,
            })
        return jsonify({"error": "Failed to submit article for processing. Please try again."}), 500


# ─── TTS Task Handler Route ──────────────────────────────────────────────────
@app.route("/tasks/process-tts", methods=["POST"])
def process_tts_task():
    logger.info("Received TTS processing task.")
    logger.debug(f"Task Handler: Request headers: {request.headers}") # Added detailed header logging

    if not db:
        logger.critical("Task Handler: Firestore client 'db' not available. Cannot process task.")
        return "Service Unavailable: Firestore client not initialized", 503

    try:
        task_payload_bytes = request.get_data()
        if not task_payload_bytes:
            logger.error("Task Handler: Received empty payload.")
            return "Bad Request: Empty payload", 400
        
        task_payload = json.loads(task_payload_bytes.decode())
        logger.info(f"Task Handler: Processing payload for item_id: {task_payload.get('item_id')}")
        logger.debug(f"Task Handler: Full payload: {task_payload}")


        item_id = task_payload.get("item_id")
        url = task_payload.get("url")
        voice = task_payload.get("voice_name")
        text_from_payload = task_payload.get("text_from_payload")

        if not all([item_id, url, voice]): # Simpler check
            logger.error(f"Task Handler: Missing required fields in payload. item_id: {item_id}, url: {url}, voice: {voice}")
            return "Bad Request: Missing required fields in task payload", 400

        item_ref = db.collection("items").document(item_id)
        item_doc = item_ref.get()

        if not item_doc.exists:
            logger.error(f"Task Handler: Item {item_id} not found in Firestore. Task may be orphaned.")
            return "OK: Item not found, task acknowledged", 200

        logger.info(f"Task Handler: Starting processing for item {item_id}, URL: {url}")
        item_ref.update({"status": "processing", "processed_at": firestore.SERVER_TIMESTAMP})

        extracted_meta = extract_article(url) #
        
        final_text = text_from_payload
        if not final_text and extracted_meta.get("text"):
            final_text = extracted_meta["text"]
        
        if not final_text:
            error_msg = f"Could not retrieve article text for URL: {url}"
            logger.error(f"Task Handler: {error_msg} for item {item_id}")
            item_ref.update({
                "status": "error", "error_message": error_msg,
                "processed_at": firestore.SERVER_TIMESTAMP,
                "title": extracted_meta.get("title", item_doc.to_dict().get("title", "Extraction Failed")),
            })
            return "OK: Processed with extraction error", 200

        title = extracted_meta.get("title", "Untitled Article")
        author = extracted_meta.get("author", "Unknown Author")
        
        update_data = {
            "title": title, "author": author,
            "text_preview": final_text[:200] + "..." if len(final_text) > 200 else final_text,
            "word_count": len(final_text.split()),
            "reading_time_min": max(1, len(final_text.split()) // 200),
        }
        if extracted_meta.get("publish_date"):
             update_data["publish_date"] = extracted_meta.get("publish_date")
        item_ref.update(update_data)
        logger.info(f"Task Handler: Metadata extracted for item {item_id}. Title: {title}")

        logger.info(f"Task Handler: Starting TTS synthesis for item {item_id}")
        tts_result = synthesize_long_text(title, author, final_text, item_id, voice) #

        if tts_result.get("error"):
            error_msg = f"TTS synthesis failed: {tts_result['error']}"
            logger.error(f"Task Handler: {error_msg} for item {item_id}")
            item_ref.update({
                "status": "error", "error_message": error_msg,
                "processed_at": firestore.SERVER_TIMESTAMP,
            })
            return "OK: Processed with TTS error", 200
        
        audio_uri = tts_result.get("uri")
        duration = tts_result.get("duration_seconds")
        gcs_path_val = tts_result.get("gcs_path")
        
        blob_size = None
        if gcs_path_val and GCS_BUCKET_NAME and bucket: # Check bucket
            try:
                blob = bucket.get_blob(gcs_path_val)
                if blob: blob_size = blob.size
                else: logger.warning(f"Task Handler: Blob {gcs_path_val} not found in bucket {GCS_BUCKET_NAME} for item {item_id}.")
            except Exception as e:
                logger.warning(f"Task Handler: Could not get blob size for {gcs_path_val} of item {item_id}: {e}", exc_info=True)

        item_ref.update({
            "status": "done", "audio_url": audio_uri, "duration_seconds": duration,
            "storage_bytes": blob_size, "gcs_bucket": GCS_BUCKET_NAME,
            "gcs_path": gcs_path_val, "processed_at": firestore.SERVER_TIMESTAMP,
            "error_message": None,
        })
        logger.info(f"Task Handler: Item processing successful for item {item_id}. Audio URL: {audio_uri}")
        return "OK: Task processed successfully", 200

    except Exception as e:
        # This is a catch-all for unexpected errors within the task handler logic
        logger.critical(f"Task Handler: Critical unhandled error processing task: {e}", exc_info=True)
        item_id_from_payload = task_payload.get("item_id") if 'task_payload' in locals() and isinstance(task_payload, dict) else None
        
        if item_id_from_payload and db: # Check db
            try:
                db.collection("items").document(item_id_from_payload).update({
                    "status": "error", "error_message": f"Critical task processing error: {str(e)}",
                    "processed_at": firestore.SERVER_TIMESTAMP,
                })
            except Exception as dbe:
                 logger.error(f"Task Handler: Failed to update Firestore for item {item_id_from_payload} on critical error: {dbe}", exc_info=True)
        return "Internal Server Error: Task processing failed unexpectedly", 500


# ─── List & Detail Pages ───────────────────────────────────────────────────
@app.route("/items", methods=["GET"]) #
@login_required #
def list_items(): #
    user_id = current_user.id
    logger.info(f"User {user_id} requested /items list.")
    if not db:
        logger.error("Firestore client not available for /items")
        return "Error loading items: Database unavailable", 503 # Changed to 503
        
    items_query = db.collection("items") \
                    .where("user_id", "==", user_id) \
                    .where("status", "in", ["done", "error", "pending", "processing"]) \
                    .order_by("submitted_at", direction=firestore.Query.DESCENDING) \
                    .limit(50)
    
    results = []
    for doc in items_query.stream():
        item = doc.to_dict()
        if isinstance(item.get("submitted_at"), datetime):
             item["submitted_at_fmt"] = item["submitted_at"].strftime("%Y-%m-%d %H:%M")
        
        # Format publish_date if it exists and is a string
        raw_publish_date = item.get("publish_date")
        if isinstance(raw_publish_date, str) and raw_publish_date:
            try:
                # Handle potential timezone info (Z, +HH:MM, -HH:MM) robustly
                if raw_publish_date.endswith("Z"):
                    dt_obj = datetime.fromisoformat(raw_publish_date[:-1] + "+00:00")
                elif "+" in raw_publish_date[10:] or "-" in raw_publish_date[10:]: # Check after date part
                    dt_obj = datetime.fromisoformat(raw_publish_date)
                else: # Assume naive, or needs a default timezone
                    dt_obj = datetime.fromisoformat(raw_publish_date)
                    logger.debug(f"Publish date {raw_publish_date} for item {item.get('id')} parsed as naive, assuming UTC or local.")
                item["publish_date_fmt"] = dt_obj.strftime("%B %d, %Y")
            except ValueError:
                logger.warning(f"Could not parse publish_date string '{raw_publish_date}' for item {item.get('id')}. Using raw value.")
                item["publish_date_fmt"] = raw_publish_date 
        elif isinstance(raw_publish_date, datetime): # If already a datetime object
             item["publish_date_fmt"] = raw_publish_date.strftime("%B %d, %Y")
        else:
             item["publish_date_fmt"] = "N/A"
        results.append(item)
    logger.debug(f"Rendering items page for user {user_id} with {len(results)} items.")
    return render_template("items.html", items=results)


@app.route("/items/<item_id>", methods=["GET"]) #
@login_required #
def item_detail(item_id): #
    user_id = current_user.id
    logger.info(f"User {user_id} requested details for item {item_id}.")
    if not db:
        logger.error(f"Firestore client not available for /items/{item_id}")
        return "Error loading item details: Database unavailable", 503 # Changed to 503

    doc_ref = db.collection("items").document(item_id)
    doc = doc_ref.get() #

    if not doc.exists:
        logger.warning(f"Item {item_id} not found (requested by user {user_id}).")
        return render_template("404.html"), 404

    item = doc.to_dict() #

    if item.get("user_id") != user_id: # Add admin check later if current_user.is_admin
        logger.warning(f"User {user_id} attempted to access unauthorized item {item_id} (owner: {item.get('user_id')}).")
        return render_template("403.html"), 403

    # Format publish_date (similar logic as in list_items for consistency)
    raw_publish_date = item.get("publish_date")
    if isinstance(raw_publish_date, str) and raw_publish_date:
        try:
            if raw_publish_date.endswith("Z"): dt_obj = datetime.fromisoformat(raw_publish_date[:-1] + "+00:00")
            elif "+" in raw_publish_date[10:] or "-" in raw_publish_date[10:]: dt_obj = datetime.fromisoformat(raw_publish_date)
            else: dt_obj = datetime.fromisoformat(raw_publish_date)
            item["publish_date_fmt"] = dt_obj.strftime("%B %d, %Y")
        except ValueError:
            logger.warning(f"Detail: Could not parse publish_date '{raw_publish_date}' for item {item_id}.")
            item["publish_date_fmt"] = raw_publish_date
    elif isinstance(raw_publish_date, datetime):
         item["publish_date_fmt"] = raw_publish_date.strftime("%B %d, %Y")
    else:
        item["publish_date_fmt"] = "N/A"
    
    logger.debug(f"Rendering detail page for item {item_id} (User: {user_id}). Status: {item.get('status')}")
    return render_template("detail.html", item=item)


# ─── API Routes ───────────────────────────────────────────────────────────────
@app.route("/api/items/<item_id>", methods=["GET"])
@login_required
def api_get_item(item_id):
    user_id = current_user.id
    logger.debug(f"API request for item {item_id} by user {user_id}")
    if not db: return jsonify({"error": "Database not available"}), 503
    doc_ref = db.collection("items").document(item_id)
    doc = doc_ref.get()
    if not doc.exists:
        logger.warning(f"API: Item {item_id} not found for GET request by user {user_id}.")
        return jsonify({"error": "Item not found"}), 404
    
    item = doc.to_dict()
    if item.get("user_id") != user_id: # Add admin check later
        logger.warning(f"API: User {user_id} forbidden to GET item {item_id} (owner: {item.get('user_id')}).")
        return jsonify({"error": "Forbidden"}), 403
    
    logger.debug(f"API: Returning item {item_id} data for user {user_id}")
    return jsonify(item), 200


@app.route("/api/items/<item_id>/tags", methods=["PUT"]) # Added for tag editing
@login_required
def api_update_item_tags(item_id):
    user_id = current_user.id
    logger.info(f"API: Tag update requested for item {item_id} by user {user_id}.")
    if not db: return jsonify({"error": "Database not available"}), 503

    payload = request.get_json(silent=True) or {}
    new_tags = payload.get("tags")

    if not isinstance(new_tags, list):
        logger.warning(f"API: Invalid tags payload for item {item_id} by user {user_id}. Expected list, got {type(new_tags)}")
        return jsonify({"error": "Invalid payload: tags must be a list."}), 400
    
    # Sanitize tags
    new_tags = [str(tag).strip() for tag in new_tags if str(tag).strip()]
    logger.debug(f"API: Sanitized tags for item {item_id}: {new_tags}")

    doc_ref = db.collection("items").document(item_id)
    doc = doc_ref.get()

    if not doc.exists:
        logger.warning(f"API: Item {item_id} not found for tag update by user {user_id}.")
        return jsonify({"error": "Item not found"}), 404
    
    item_data = doc.to_dict()
    if item_data.get("user_id") != user_id: # Add admin check later
        logger.warning(f"API: User {user_id} forbidden to update tags for item {item_id} (owner: {item_data.get('user_id')}).")
        return jsonify({"error": "Forbidden"}), 403
    
    try:
        doc_ref.update({"tags": new_tags, "updated_at": firestore.SERVER_TIMESTAMP})
        logger.info(f"API: Tags updated successfully for item {item_id} by user {user_id} to: {new_tags}")
        return jsonify({"message": "Tags updated successfully", "item_id": item_id, "tags": new_tags}), 200
    except Exception as e:
        logger.error(f"API: Error updating tags for item {item_id} by user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to update tags"}), 500


@app.route("/api/items/<item_id>/retry", methods=["POST"])
@login_required
def api_retry_item(item_id):
    user_id = current_user.id
    logger.info(f"API: Retry requested for item {item_id} by user {user_id}")
    if not tasks_client or not db:
        logger.error(f"API Retry: Service unavailable (Tasks client: {bool(tasks_client)}, DB client: {bool(db)}) for item {item_id}.")
        return jsonify({"error": "Service unavailable for retry"}), 503

    item_ref = db.collection("items").document(item_id)
    item_doc = item_ref.get()
    if not item_doc.exists:
        logger.warning(f"API Retry: Item {item_id} not found for user {user_id}.")
        return jsonify({"error": "Item not found"}), 404
    
    item_data = item_doc.to_dict()
    if item_data.get("user_id") != user_id: # Add admin check later
        logger.warning(f"API Retry: User {user_id} forbidden to retry item {item_id} (owner: {item_data.get('user_id')}).")
        return jsonify({"error": "Forbidden"}), 403
    
    if item_data.get("status") != "error":
        logger.warning(f"API Retry: Item {item_id} is not in 'error' state (current: {item_data.get('status')}). No action taken.")
        return jsonify({"error": "Item is not in an error state"}), 400
    
    logger.info(f"API Retry: Proceeding to re-queue item {item_id} for user {user_id}.")
    
    item_ref.update({
        "status": "pending", "error_message": None, "processed_at": None,
        "submitted_at": firestore.SERVER_TIMESTAMP # Consider a "retried_at" field too
    })

    task_payload_dict = {
        "item_id": item_id, "url": item_data.get("url"), "voice_name": item_data.get("voice"),
        "text_from_payload": "", "tags": item_data.get("tags", []), "user_id": user_id
    }
    parent = tasks_client.queue_path(GCP_PROJECT_ID, GCP_LOCATION_ID, TTS_TASK_QUEUE_ID)
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST, "url": TTS_TASK_HANDLER_URL,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(task_payload_dict).encode(),
        }
    }
    if TTS_TASK_SERVICE_ACCOUNT_EMAIL:
        task["http_request"]["oidc_token"] = {"service_account_email": TTS_TASK_SERVICE_ACCOUNT_EMAIL}
    
    try:
        task_response = tasks_client.create_task(request={"parent": parent, "task": task})
        logger.info(f"API Retry: Task {task_response.name} created for item {item_id}.")
        return jsonify({"message": "Item re-queued for processing.", "item_id": item_id}), 202
    except Exception as e:
        logger.error(f"API Retry: Error re-enqueuing task for item {item_id}: {e}", exc_info=True)
        item_ref.update({"status": "error", "error_message": f"Failed to re-enqueue task: {str(e)}"})
        return jsonify({"error": "Failed to re-submit item for processing."}), 500


# ─── Errors & Admin ─────────────────────────────────────────────────────────
@app.route("/errors", methods=["GET"]) #
@login_required #
def list_errors(): #
    user_id = current_user.id
    logger.info(f"User {user_id} requested /errors page.")
    if not db: 
        logger.error("Errors Page: Firestore client not available.")
        return "Error loading errors: Database unavailable", 503
    docs = (
        db.collection("items")
        .where("user_id", "==", user_id)
        .where("status", "==", "error")
        .stream()
    )

    errors = []
    for d in docs:
        data = d.to_dict()
        errors.append(
            {
                "id": d.id,
                "url": data.get("url", ""),
                "title": data.get("title", "<no title>"),
                "failed_at": data.get("submitted_at"),
                "error": data.get("error_message", "<no message>"),
            }
        )

    errors.sort(key=lambda e: e.get("failed_at") or "", reverse=True)

    for e in errors:
        try:
            ts = e["failed_at"]
            if isinstance(ts, datetime):
                dt = ts
            else:
                dt = dateparser.isoparse(str(ts)) if ts else None
            e["failed_at_fmt"] = dt.strftime("%b %d %Y %H:%M") if dt else "—"
        except Exception:
            e["failed_at_fmt"] = e.get("failed_at") or "—"

    logger.debug(
        f"Rendering errors page for user {user_id} with {len(errors)} error items."
    )
    return render_template("errors.html", errors=errors)

@app.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    user_id = current_user.id
    logger.info(f"User {user_id} ({current_user.username}) accessed /admin dashboard.")
    
    if not db:
        logger.error("Admin Dashboard: Firestore client not available.")
        return "Error loading admin dashboard: Database unavailable", 503

    try:
        items_query = db.collection("items").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(100)
        all_items = []
        for doc in items_query.stream():
            item = doc.to_dict()
            if isinstance(item.get("submitted_at"), datetime):
                item["submitted_at_fmt"] = item["submitted_at"].strftime("%Y-%m-%d %H:%M")
            all_items.append(item)
        
        return render_template("admin.html", items=all_items)
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}", exc_info=True)
        return "Error loading admin dashboard", 500
    
# ─── RSS & Health ─────────────────────────────────────────────────────────
@app.route("/feed.xml", methods=["GET"]) #
def rss_feed(): #
    logger.info(f"RSS feed requested from IP: {request.remote_addr}")
    try:
        xml_feed = rss_generator.generate_feed(request.url_root, bucket_name=GCS_BUCKET_NAME) #
        logger.debug(f"RSS feed generated successfully, length: {len(xml_feed)} bytes.")
        return Response(xml_feed, mimetype="application/rss+xml") #
    except Exception as e:
        logger.error(f"Error generating RSS feed: {e}", exc_info=True) #
        return "Error generating RSS feed", 500

@app.route("/health", methods=["GET"]) #
def health(): #
    logger.debug(f"Health check requested from IP: {request.remote_addr}")
    # Basic health check, can be expanded (e.g., check DB, Task queue connection)
    # For now, just check if essential clients were initialized
    db_status = "healthy" if db else "unavailable"
    tasks_status = "healthy" if tasks_client else "unavailable"
    
    if db and tasks_client:
        overall_status = "healthy"
        http_status = 200
    else:
        overall_status = "degraded"
        http_status = 503 # Service Unavailable
        logger.warning(f"Health check: DB status: {db_status}, Tasks client status: {tasks_status}")

    return jsonify({
        "status": overall_status, 
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "firestore": db_status,
            "cloud_tasks": tasks_status
        }
    }), http_status

# ─── Error Handlers ────────────────────────────────────────────────────────
@app.errorhandler(404) #
def not_found_error(error):
    user_info = current_user.id if current_user.is_authenticated else 'Anonymous'
    logger.warning(f"404 Not Found error at {request.url} for user: {user_info}")
    if request.path.startswith("/api/"):
        return jsonify(error="Not Found", path=request.path), 404 #
    return render_template("404.html"), 404 #

@app.errorhandler(403) #
def forbidden_error(error):
    user_info = current_user.id if current_user.is_authenticated else 'Anonymous'
    logger.warning(f"403 Forbidden error at {request.url} for user: {user_info}")
    if request.path.startswith("/api/"):
        return jsonify(error="Forbidden", path=request.path), 403
    return render_template("403.html"), 403 #

@app.errorhandler(500)
def internal_server_error(error):
    user_info = current_user.id if current_user.is_authenticated else 'Anonymous'
    logger.error(f"500 Internal Server Error at {request.url} for user: {user_info}. Error: {error}", exc_info=True)
    if request.path.startswith("/api/"):
        return jsonify(error="Internal Server Error", message=str(error)), 500
    # For 500, it's often better not to expose error details directly in production HTML
    return render_template("errors.html", error_message_500="An unexpected server error occurred. The issue has been logged."), 500


# ─── Main (for local development) ──────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting Flask development server for SpeakLoudTTS...")
    # Ensure environment variables are set for local development:
    # GOOGLE_APPLICATION_CREDENTIALS, FLASK_SECRET_KEY, GCS_BUCKET_NAME,
    # GCP_PROJECT_ID, GCP_LOCATION_ID, TTS_TASK_QUEUE_ID, TTS_TASK_HANDLER_URL
    # (TTS_TASK_HANDLER_URL for local dev could be an ngrok URL if testing with actual Cloud Tasks)
    
    required_env_vars = [
        "FLASK_SECRET_KEY", "GCS_BUCKET_NAME", "GCP_PROJECT_ID", 
        "GCP_LOCATION_ID", "TTS_TASK_QUEUE_ID", "TTS_TASK_HANDLER_URL"
    ]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.warning(f"Missing one or more critical environment variables: {', '.join(missing_vars)}. Application may not function correctly, especially Cloud Tasks.")
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS environment variable not set. GCP client authentication may fail.")

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True) #