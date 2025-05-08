import os
import tempfile
import subprocess
from typing import List
from google.cloud import texttospeech, storage

# ─── Configuration ──────────────────────────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
MAX_BYTES  = 4500  # headroom under the 5000-byte SSML limit

# ─── GCP Clients ─────────────────────────────────────────────────────────────────
tts_client     = texttospeech.TextToSpeechClient()
storage_client = storage.Client()
bucket         = storage_client.bucket(GCS_BUCKET)

# ─── Audio Config: MP3 + 10% faster speaking rate ───────────────────────────────
AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3,
    speaking_rate=1.1
)

def _build_ssml(title: str, author: str, paragraphs: List[str]) -> List[str]:
    """
    Wrap paragraphs in SSML and chunk so each payload (with tags) stays under MAX_BYTES.
    """
    prefix = (
        "<speak>"
        f"<p><emphasis level='moderate'>Title:</emphasis> {title}. "
        f"<emphasis level='moderate'>By {author}</emphasis>.</p>"
    )
    suffix = "</speak>"

    chunks = []
    current = prefix

    for p in paragraphs:
        block = f"<p>{p}</p><break time='300ms'/>"
        # if adding this block would exceed MAX_BYTES once encoded, close & start new
        if len((current + block + suffix).encode("utf-8")) > MAX_BYTES:
            chunks.append(current + suffix)
            current = prefix + block
        else:
            current += block

    # finish last chunk
    chunks.append(current + suffix)
    return chunks


def synthesize_long_text(
    title: str,
    author: str,
    full_text: str,
    item_id: str,
    voice_name: str
) -> dict:
    """
    Produces a single MP3 in GCS by:
      1) Splitting text into paragraphs
      2) Building SSML chunks under the byte limit
      3) Calling Google TTS on each chunk
      4) Merging via ffmpeg
      5) Uploading to GCS

    Returns a dict with:
      - uri:            public URL of the MP3
      - duration_secs:  audio length in seconds (if ffprobe available)
      - char_count:     number of characters synthesized
    """
    # 1) Paragraph split
    paras = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    if len(paras) <= 1:
        paras = [p for p in full_text.splitlines() if p.strip()]

    # 2) Build SSML‐safe chunks
    ssml_chunks = _build_ssml(title, author, paras)

    # 3) Synthesize each chunk to a temp file
    tmpdir    = tempfile.gettempdir()
    seg_paths = []
    for idx, ssml in enumerate(ssml_chunks):
        resp = tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=voice_name
            ),
            audio_config=AUDIO_CONFIG,
        )
        path = os.path.join(tmpdir, f"{item_id}_{idx}.mp3")
        with open(path, "wb") as f:
            f.write(resp.audio_content)
        seg_paths.append(path)

    # 4) Concatenate via ffmpeg
    list_file = os.path.join(tmpdir, f"{item_id}_list.txt")
    with open(list_file, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")

    merged = os.path.join(tmpdir, f"{item_id}_full.mp3")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy", merged
    ], check=True)

    # 5) (Optional) probe for duration
    try:
        result = subprocess.run(
            [
                "ffprobe","-v","error",
                "-show_entries","format=duration",
                "-of","default=noprint_wrappers=1:nokey=1",
                merged
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        duration_secs = float(result.stdout.strip())
    except Exception:
        duration_secs = None

    # 6) Upload to GCS
    blob = bucket.blob(f"{item_id}.mp3")
    blob.upload_from_filename(merged, content_type="audio/mpeg")
    uri = f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3"

    return {
        "uri":           uri,
        "duration_secs": duration_secs,
        "char_count":    len(full_text),
    }