# tests/test_app.py

import os
import sys
import pytest
import json
from flask_login import FlaskLoginClient
from datetime import datetime

# ─── Make sure we can import "app" and "your_user_module" ─────────────────────
# Insert project root (one level up from this tests/ folder) onto sys.path.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app as _app          # your Flask application
from your_user_module import User    # same module used by app.py

# Tell Flask to use Flask-Login’s test client (so login_user() works)
_app.test_client_class = FlaskLoginClient

# ─── FIXTURE: Test client & monkey‐patch external calls ───────────────────────
@pytest.fixture(autouse=True)
def use_test_client(monkeypatch, tmp_path):
    """
    1) Configure Flask to use the test client that supports login_user().
    2) Monkey‐patch Firestore + Storage + TTS + RSS so we don’t call real GCP.
    """
    # ─── Dummy Firestore Classes ───────────────────────────────────────────────
    class DummyDocRef:
        def __init__(self):
            # Give a constant dummy ID for testing
            self.id = "dummy-item-id"
            # Mimic Firestore DocumentSnapshot.exists attribute
            self.exists = False

        def set(self, data):
            return None

        def update(self, data):
            return None

        def get(self):
            """Return self to mimic Firestore's document reference .get()."""
            return self

        def to_dict(self):
            return {}

    class DummyQuery:
        def order_by(self, *args, **kwargs):
            return self

        def stream(self):
            return iter([])

    class DummyCollection:
        def document(self, doc_id=None):
            return DummyDocRef()

        def where(self, *args, **kwargs):
            return DummyQuery()

        def stream(self):
            return iter([])

    class DummyFirestoreClient:
        def collection(self, name):
            return DummyCollection()

    # Monkey‐patch firestore.Client() to return our dummy client
    monkeypatch.setattr("app.firestore.Client", lambda: DummyFirestoreClient())
    monkeypatch.setattr("app.storage.Client", lambda: DummyFirestoreClient())

    # ─── Dummy TTS Synthesis ───────────────────────────────────────────────────
    def fake_synthesize_long_text(title, author, text, item_id, voice):
        return {"uri": f"https://dummy/{item_id}.mp3"}

    monkeypatch.setattr("app.synthesize_long_text", fake_synthesize_long_text)

    # ─── Dummy RSS Generator ───────────────────────────────────────────────────
    monkeypatch.setattr("app.rss.generate_feed", lambda root, bucket_name=None: "<rss></rss>")

    yield
    # (Nothing to clean up.)


# ─── FIXTURE: Create a fake “test” user ───────────────────────────────────────
@pytest.fixture()
def fake_user(monkeypatch):
    """
    Create a dummy “test” user for authentication.  This fake user has:
      - id = "test-user-id"
      - username = "test"
      - password_hash = arbitrary
      - is_admin = True
    """
    class FakeUserObj:
        def __init__(self):
            self.id = "test-user-id"
            self.username = "test"
            self.password_hash = "hashed-test"
            self.is_admin = True

        def get_id(self):
            return self.id

        @staticmethod
        def get(user_id):
            if user_id == "test-user-id":
                return FakeUserObj()
            return None

        @staticmethod
        def authenticate(username, password):
            if username == "test" and password == "test":
                return FakeUserObj()
            return None

        def is_active(self):
            return True

        def is_authenticated(self):
            return True

    # Monkey‐patch the User methods in your_user_module
    monkeypatch.setattr("your_user_module.User.get", FakeUserObj.get)
    monkeypatch.setattr("your_user_module.User.authenticate", FakeUserObj.authenticate)

    return FakeUserObj()


# ─── FIXTURE: Provide a “client” for our tests ────────────────────────────────
@pytest.fixture()
def client(use_test_client):
    """
    Return the Flask‐Login enabled test client. Because of `use_test_client(autouse=True)`,
    this client already has Firestore, Storage, TTS, and RSS monkey‐patched.
    """
    return _app.test_client()


# ─── TEST: 404 returns HTML ────────────────────────────────────────────────────
def test_404_returns_html(client):
    resp = client.get("/nonexistent-page")
    assert resp.status_code == 404
    assert b"404" in resp.data


# ─── TEST: API 404 returns JSON ────────────────────────────────────────────────
def test_api_404_returns_json(client):
    resp = client.get("/api/nonexistent")
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.json.get("error") == "not found"


# ─── TEST: Login and Logout ───────────────────────────────────────────────────
def test_login_and_logout(client, fake_user):
    # GET login page
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Log In" in resp.data

    # POST correct credentials → redirect to /submit
    resp = client.post("/login", data={"username": "test", "password": "test"})
    assert resp.status_code in (302, 303)
    assert "/submit" in resp.headers["Location"]

    # Now logout
    resp = client.get("/logout")
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["Location"]


# ─── TEST: Protected routes require login ──────────────────────────────────────
def test_protected_routes_require_login(client):
    for route in ["/submit", "/extract", "/items", "/errors"]:
        resp = client.get(route)
        assert resp.status_code in (302, 303)


# ─── TEST: Extract endpoint returns text ───────────────────────────────────────
def test_extract_endpoint_returns_text(client, fake_user):
    # first log in
    client.post("/login", data={"username": "test", "password": "test"})
    # Now POST to /extract
    payload = {"url": "https://example.com"}
    resp = client.post("/extract", json=payload)
    assert resp.status_code == 200
    assert resp.is_json
    assert "text" in resp.json


# ─── TEST: Submit endpoint minimum validation ─────────────────────────────────
def test_submit_endpoint_minimum_validation(client, fake_user):
    # log in
    client.post("/login", data={"username": "test", "password": "test"})

    # Missing required fields → 400
    resp = client.post("/submit", json={})
    assert resp.status_code == 400
    assert resp.is_json
    err_msg = resp.json.get("error", "")
    # our error string mentions url, text, and voice
    assert "url" in err_msg.lower()
    assert "text" in err_msg.lower()
    assert "voice" in err_msg.lower()

    # Valid JSON payload
    payload = {
        "url":        "https://example.com/foo",
        "text":       "some dummy extracted text",
        "voice_name": "en-US-Wavenet-A",
        "tags":       ["news"]
    }
    resp2 = client.post("/submit", json=payload)
    assert resp2.status_code == 202
    assert resp2.is_json
    data = resp2.json
    assert "item_id" in data
    assert data["tts_uri"].startswith("https://dummy/")


# ─── TEST: List items and detail routes ────────────────────────────────────────
def test_list_items_and_detail_routes(client, fake_user):
    # log in
    client.post("/login", data={"username": "test", "password": "test"})

    # GET /items (empty list is OK)
    resp = client.get("/items")
    assert resp.status_code == 200
    assert b"Processed Articles" in resp.data

    # GET /items/dummy-item-id → dummy Firestore is empty, so should 404
    resp2 = client.get("/items/dummy-item-id")
    assert resp2.status_code == 404


# ─── TEST: Error page/dashboard requires login and returns HTML ───────────────
def test_error_page_dashboard_requires_login_and_returns_html(client, fake_user):
    # /errors and /admin both protected
    resp = client.get("/errors")
    assert resp.status_code in (302, 303)

    # log in as test user
    client.post("/login", data={"username": "test", "password": "test"})

    # /errors should render HTML (empty table is fine)
    resp2 = client.get("/errors")
    assert resp2.status_code == 200
    assert b"Failed Articles" in resp2.data

    # /admin is only for admin users
    resp3 = client.get("/admin")
    assert resp3.status_code == 200
    assert b"Admin Dashboard" in resp3.data


# ─── TEST: RSS & Health endpoints ─────────────────────────────────────────────
def test_rss_and_health_endpoints(client):
    # RSS should return some XML
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert b"<rss" in resp.data

    # /health returns JSON
    resp2 = client.get("/health")
    assert resp2.status_code == 200
    assert resp2.is_json
    assert resp2.json.get("status") == "ok"