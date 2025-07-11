# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "a_default_secret_key")
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
    GCP_LOCATION_ID = os.getenv("GCP_LOCATION_ID")
    TTS_TASK_QUEUE_ID = os.getenv("TTS_TASK_QUEUE_ID")
    TTS_TASK_HANDLER_URL = os.getenv("TTS_TASK_HANDLER_URL")
    TTS_TASK_SERVICE_ACCOUNT_EMAIL = os.getenv("TTS_TASK_SERVICE_ACCOUNT_EMAIL")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    FLASK_ENV = os.getenv("FLASK_ENV", "production")

    ALLOWED_VOICES = [
        "en-US-Standard-C", "en-US-Standard-D", "en-GB-Standard-A",
        "en-AU-Standard-B", "en-US-Wavenet-D", "en-US-Wavenet-F",
    ]
    DEFAULT_VOICE = ALLOWED_VOICES[0]

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    FLASK_ENV = "development"

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

def get_config():
    return DevelopmentConfig() if os.getenv("FLASK_ENV") == "development" else ProductionConfig()

config = get_config()
