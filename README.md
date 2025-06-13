# SpeakLoudTTS

> Convert any web-article into a podcast-ready MP3 using Google Text-to-Speech, with a Flask UI, Firestore metadata store, and Cloud Storage hosting.

---

## 🌟 Features

- **One-click URL → Audio**  
  Submit any article URL; we extract the text (Trafilatura → Newspaper → Readability fallbacks), generate SSML, chunk it, synthesize with TTS, merge via FFmpeg, and upload to GCS.

- **Voice selection**  
  Choose from a mid-tier set of natural Wavenet voices (US Male, US Female, UK Female, AU Male) on the submission form.

- **Rich web UI**  
  - Responsive layout (mobile-friendly)  
  - Dark/light mode toggle  
  - Real-time highlighting of narrated paragraphs  
  - Speed controls, jump ±15/30 sec buttons, keyboard shortcuts  
  - Download link, share buttons, font-size toggles  
  - “Errors” page listing any failed submissions with retry capability

- **RSS Feed**  
  Automatic `/feed.xml` podcast feed (no iTunes-specific tags) sorted by original publish date.

- **Firestore + Cloud Storage**  
  Metadata in Firestore (status, tags, voice choice, timestamps, IPs) + MP3s in a GCS bucket.

---

## 🚀 Quickstart

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/speakloudtts.git
cd speakloudtts
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg   # macOS (or apt-get install ffmpeg)

2. Configure GCP credentials
	1.	Create a GCP service account with these roles:
	•	Text-to-Speech Admin
	•	Firestore User
	•	Storage Object Admin
	2.	Download its JSON key and save as credentials.json in project root.
	3.	Export environment variables:

export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/credentials.json"
export GCS_BUCKET_NAME="your-gcs-bucket-name"



3. Run locally

# Flask development server
flask run --port=5001
# or
python app.py

Visit http://localhost:5001/submit to try it out.

⸻

🐋 Docker
	1.	Build image

docker build -t speakloudtts .


	2.	Run container

docker run --rm -it \
  -p 5001:5001 \
  -e GCS_BUCKET_NAME=your-bucket-name \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json \
  -v "$(pwd)/credentials.json":/app/credentials.json:ro \
  speakloudtts


	3.	Browse to http://localhost:5001.

⸻

☁️ Deploy to Cloud Run

# Build & push
gcloud builds submit \
  --tag gcr.io/$(gcloud config get-value project)/speakloudtts

# Deploy
gcloud run deploy speakloudtts \
  --image gcr.io/$(gcloud config get-value project)/speakloudtts \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET_NAME=your-gcs-bucket-name

  ## ☁️ Google Cloud Tasks Setup (for Asynchronous TTS Processing)

To handle Text-to-Speech (TTS) synthesis asynchronously, this application uses Google Cloud Tasks. This prevents HTTP timeouts for long articles and improves user experience. You'll need to configure a Cloud Tasks queue and set the appropriate IAM permissions.

### 1. Enable Cloud Tasks API

Ensure the Cloud Tasks API is enabled for your Google Cloud Project. You can do this via the Google Cloud Console or using the gcloud CLI:
```bash
gcloud services enable cloudtasks.googleapis.com


⸻

🔧 Configuration

Variable	Description
GOOGLE_APPLICATION_CREDENTIALS	Path to your GCP service-account JSON key
GCS_BUCKET_NAME	Name of your Google Cloud Storage bucket
ALLOWED_VOICES	List of TTS voice names exposed on the submission UI
DEFAULT_VOICE	Fallback voice if none is selected or invalid


⸻

🔗 Endpoints
	•	Web UI
	•	GET /submit → submission page
	•	GET /items → list of processed articles
	•	GET /items/<id> → detail & player
	•	GET /errors → list & retry failures
	•	JSON API
	•	POST /submit → { url, voice_name } → { item_id, tts_uri }
	•	GET  /api/recent → latest 5 done items
	•	GET  /api/items → paginated, filterable list
	•	PUT  /api/items/<id>/tags → update tags
	•	POST /api/items/<id>/retry → re-enqueue a failed item
	•	GET  /feed.xml → RSS 2.0 feed of done items

⸻

🤝 Contributions
	1.	Fork the repo
	2.	Create a feature branch (git checkout -b feat/XYZ)
	3.	Commit & push
	4.	Open a pull request

⸻

📜 License

MIT © Mike H

