# tts.py
import os, tempfile, subprocess
from typing import List
from google.cloud import texttospeech, storage

# ─── Config & Clients ───────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")

tts_client     = texttospeech.TextToSpeechClient()
storage_client = storage.Client()
bucket         = storage_client.bucket(GCS_BUCKET)

VOICE_PARAMS = texttospeech.VoiceSelectionParams(
    language_code="en-US",
    name="en-US-Wavenet-F",              # try different WaveNet voices
    ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
)
AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3
)

# ─── Helpers ──────────────────────────────────────────────────────
def _build_ssml(title: str, author: str, paragraphs: List[str]) -> List[str]:
    """
    Wrap each paragraph in minimal SSML.
    Returns a list of SSML strings under the 5000-char limit.
    """
    ssml_chunks = []
    chunk = f"<speak><p><emphasis level='moderate'>Title:</emphasis> {title}. " \
            f"<emphasis level='moderate'>By {author}</emphasis>.</p>"
    for p in paragraphs:
        # close previous <speak>, start new if needed
        if len(chunk) + len(p) > 4500:
            chunk += "</speak>"
            ssml_chunks.append(chunk)
            chunk = "<speak>"
        chunk += f"<p>{p}</p><break time='300ms'/>"
    chunk += "</speak>"
    ssml_chunks.append(chunk)
    return ssml_chunks

def synthesize_long_text(title: str, author: str, full_text: str, item_id: str) -> str:
    """
    Break full_text into paragraphs, build SSML, call TTS for each chunk,
    concatenate with ffmpeg, upload to GCS, and return the public URL.
    """
    # Split on double-newlines, fallback to lines
    paras = [p for p in full_text.split("\n\n") if p.strip()]
    if len(paras) == 1:
        paras = full_text.splitlines()

    ssml_chunks = _build_ssml(title, author, paras)
    tmp = tempfile.gettempdir()
    seg_paths = []

    # Synthesize each chunk
    for idx, ssml in enumerate(ssml_chunks):
        resp = tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=VOICE_PARAMS,
            audio_config=AUDIO_CONFIG
        )
        path = os.path.join(tmp, f"{item_id}_{idx}.mp3")
        with open(path, "wb") as f:
            f.write(resp.audio_content)
        seg_paths.append(path)

    # FFmpeg concat
    list_txt = os.path.join(tmp, f"{item_id}_list.txt")
    with open(list_txt, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
    merged = os.path.join(tmp, f"{item_id}_full.mp3")
    subprocess.run([
        "ffmpeg","-y","-loglevel","error","-f","concat","-safe","0",
        "-i", list_txt, "-c","copy", merged
    ], check=True)

    # Upload
    blob = bucket.blob(f"{item_id}.mp3")
    blob.upload_from_filename(merged, content_type="audio/mpeg")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{item_id}.mp3"