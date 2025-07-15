import logging
import uuid
from flask import request

class RequestIdFilter(logging.Filter):
    """Injects a unique request ID into each log record."""
    def filter(self, record):
        record.request_id = getattr(request, 'request_id', 'outside-request-context')
        return True

class JsonFormatter(logging.Formatter):
    """Formats log records as JSON."""
    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
            "request_id": getattr(record, 'request_id', 'none'),
            "user_id": getattr(record, 'user_id', 'anonymous'),
            "remote_addr": getattr(record, 'remote_addr', 'none'),
            "url": getattr(record, 'url', 'none'),
        }
        if record.exc_info:
            log_object['exc_info'] = self.formatException(record.exc_info)
        return str(log_object)

def setup_logging(app):
    """Configures structured JSON logging for the Flask app."""
    # Remove default handlers
    for handler in app.logger.handlers[:]:
        app.logger.removeHandler(handler)
    
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    
    app.logger.addHandler(handler)
    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))

    @app.before_request
    def before_request_logging():
        request.request_id = str(uuid.uuid4())
