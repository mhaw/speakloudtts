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
    ENV_MODE = os.getenv("ENV_MODE", "prod")

    ALLOWED_VOICES = [
        {"code": "en-US-Wavenet-D", "name": "Deep Voice Dave (US Male)"},
        {"code": "en-US-Wavenet-F", "name": "News Anchor Nancy (US Female)"},
        {"code": "en-GB-Wavenet-B", "name": "British Ben (UK Male)"},
        {"code": "en-GB-Wavenet-F", "name": "London Lily (UK Female)"},
        {"code": "en-AU-Neural2-C", "name": "Aussie Ava (AU Female)"},
        {"code": "en-AU-Neural2-B", "name": "Outback Ollie (AU Male)"},
    ]
    DEFAULT_VOICE = "en-US-Wavenet-D"

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
