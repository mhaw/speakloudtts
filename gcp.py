# gcp.py
import os
import logging
import json
from google.cloud import firestore, storage, tasks_v2
from google.auth.exceptions import DefaultCredentialsError
from config import config
from exceptions import GCPInitializationError

logger = logging.getLogger(__name__)

db = None
storage_client = None
bucket = None
tasks_client = None

def init_gcp_clients():
    """
    Initializes and returns the GCP clients (Firestore, Storage, Tasks).
    """
    global db, storage_client, bucket, tasks_client

    if config.ENV_MODE == "dev":
        logger.info("Running in DEV mode. Skipping Google Cloud client initialization.")
        db = None
        storage_client = None
        bucket = None
        tasks_client = None
        return db, storage_client, bucket, tasks_client

    try:
        db = firestore.Client()
        storage_client = storage.Client()
        bucket = storage_client.bucket(config.GCS_BUCKET_NAME)
        
        if all([config.GCP_PROJECT_ID, config.GCP_LOCATION_ID, config.TTS_TASK_QUEUE_ID]):
            tasks_client = tasks_v2.CloudTasksClient()
            logger.info("Successfully initialized Firestore, Storage, and Cloud Tasks clients.")
        else:
            tasks_client = None
            logger.warning("Cloud Tasks client not initialized due to missing configuration. Running in inline processing mode.")
        
        return db, storage_client, bucket, tasks_client

    except DefaultCredentialsError as e:
        logger.critical(f"GCP Default Credentials Error: {e}. The application will not work correctly.", exc_info=True)
        raise GCPInitializationError(f"GCP Default Credentials Error: {e}") from e
    except Exception as e:
        logger.critical(f"Failed to initialize one or more Google Cloud clients: {e}", exc_info=True)
        raise GCPInitializationError(f"Failed to initialize GCP clients: {e}") from e

def create_processing_task(item_id: str, log_extra: dict = None):
    """Creates a new task in the TTS processing queue."""
    if config.ENV_MODE == "dev":
        logging.info(f"DEV mode: Skipping Cloud Task creation for item {item_id}.", extra=log_extra)
        return None
    if not tasks_client:
        logging.warning("Task client not available. Skipping task creation.", extra=log_extra)
        return None
        
    task_payload = json.dumps({"item_id": item_id}).encode('utf-8')
    task = {
        "http_request": {
            "http_method": 'POST',
            "url": config.TTS_TASK_HANDLER_URL,
            "headers": {"Content-Type": "application/json"},
            "body": task_payload,
            "oidc_token": {"service_account_email": config.TTS_TASK_SERVICE_ACCOUNT_EMAIL},
        }
    }
    parent = tasks_client.queue_path(config.GCP_PROJECT_ID, config.GCP_LOCATION_ID, config.TTS_TASK_QUEUE_ID)
    try:
        response = tasks_client.create_task(parent=parent, task=task)
        logging.info(f"Created task: {response.name}")
        return response
    except Exception as e:
        logging.error(f"Error creating task for item {item_id}: {e}", exc_info=True)
        return None

# Initialize on import
init_gcp_clients()
