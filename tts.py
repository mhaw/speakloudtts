import logging
import os
import tempfile
import subprocess
import html  # For SSML escaping
from typing import List, Dict
from google.cloud import texttospeech, storage

logger = logging.getLogger("tts")
logger.setLevel(logging.INFO)

# ─── Configuration ──────────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
MAX_BYTES = 4500  # Google TTS SSML limit is 5000; leave buffer

# ─── GCP Clients ────────────────────────────────────────────────
TTS_CLIENT_INSTANCE = None
STORAGE_CLIENT_INSTANCE = None
GCS_BUCKET_INSTANCE = None

def _get_tts_client():
    global TTS_CLIENT_INSTANCE
    if TTS_CLIENT_INSTANCE is None:
        try:
            TTS_CLIENT_INSTANCE = texttospeech.TextToSpeechClient()
            logger.info("TTS: Initialized TextToSpeechClient.")
        except Exception as e:
            logger.critical(f"TTS: Failed to initialize TextToSpeechClient: {e}", exc_info=True)
            raise
    return TTS_CLIENT_INSTANCE

def _get_storage_client_and_bucket():
    global STORAGE_CLIENT_INSTANCE, GCS_BUCKET_INSTANCE
    if STORAGE_CLIENT_INSTANCE is None or GCS_BUCKET_INSTANCE is None:
        try:
            STORAGE_CLIENT_INSTANCE = storage.Client()
            GCS_BUCKET_INSTANCE = STORAGE_CLIENT_INSTANCE.bucket(GCS_BUCKET)
            logger.info(f"TTS: Initialized StorageClient and bucket '{GCS_BUCKET}'.")
        except Exception as e:
            logger.critical(f"TTS: Failed to initialize StorageClient or bucket '{GCS_BUCKET}': {e}", exc_info=True)
            raise
    return STORAGE_CLIENT_INSTANCE, GCS_BUCKET_INSTANCE

def _build_ssml(title: str, author: str, paragraphs: List[str]) -> List[str]:
    """Splits article into SSML chunks < MAX_BYTES bytes for Google TTS."""
    logger.debug(f"Building SSML for '{title}', by '{author}', {len(paragraphs)} paragraphs.")
    speak_open_tag, speak_close_tag = "<speak>", "</speak>"
    prefix_content = ""
    if title:
        prefix_content += f"<emphasis level='strong'>{html.escape(title)}</emphasis><break time='600ms'/>"
    if author:
        prefix_content += f"By {html.escape(author)}<break time='800ms'/>"
    chunks, current, current_bytes = [], [], len(speak_open_tag) + len(speak_close_tag)
    if prefix_content:
        prefix_bytes = len(prefix_content.encode('utf-8'))
        if prefix_bytes < MAX_BYTES - current_bytes:
            current.append(prefix_content)
            current_bytes += prefix_bytes
        else:
            logger.warning("SSML prefix is too long, splitting.")
            chunks.append(speak_open_tag + prefix_content[:MAX_BYTES//2] + speak_close_tag)
            prefix_content = prefix_content[MAX_BYTES//2:]
    for p in paragraphs:
        if not p.strip():
            continue
        p_ssml = f"<p>{html.escape(p)}</p><break time='500ms'/>"
        p_bytes = len(p_ssml.encode('utf-8'))
        if current_bytes + p_bytes > MAX_BYTES:
            if current:
                chunks.append(speak_open_tag + "".join(current) + speak_close_tag)
            current, current_bytes = [p_ssml], len(speak_open_tag) + len(speak_close_tag) + p_bytes
        else:
            current.append(p_ssml)
            current_bytes += p_bytes
    if current:
        chunks.append(speak_open_tag + "".join(current) + speak_close_tag)
    logger.info(f"Built {len(chunks)} SSML chunk(s).")
    if not chunks:
        logger.warning("No SSML chunks generated; text was empty or too fragmented.")
    return chunks

def synthesize_long_text(
    title: str,
    author: str,
    full_text: str,
    item_id: str,
    voice_name: str,
    speaking_rate: float = 1.1,
    force_overwrite: bool = False
) -> Dict[str, any]:
    """
    Synthesizes long-form text using Google TTS, uploads MP3 to GCS, returns dict with result.
    """
    logger.info(f"TTS: Synthesizing item {item_id}: '{title}' with voice {voice_name}")
    try:
        tts_client = _get_tts_client()
        _, bucket = _get_storage_client_and_bucket()
    except Exception as e:
        return {"uri": None, "duration_seconds": 0, "error": f"Failed to initialize GCP clients: {str(e)}"}

    output_gcs_filename = f"{item_id}.mp3"
    blob = bucket.blob(output_gcs_filename)

    if not force_overwrite and blob.exists():
        logger.info(f"TTS: File {output_gcs_filename} already exists in GCS and force_overwrite is False. Skipping synthesis.")
        return {
            "gcs_path": output_gcs_filename,
            "duration_seconds": 0,  # Duration is unknown without probing, which we skip.
            "gcs_bucket": GCS_BUCKET,
            "num_segments": 0,
            "error": "skipped_existing_file"
        }

    paras = [p.strip() for p in full_text.split('\n') if p.strip()]
    if not paras and not title and not author:
        logger.warning(f"TTS: No content for item {item_id}. Aborting.")
        return {"uri": None, "duration_seconds": 0, "error": "No content to synthesize."}

    ssml_chunks = _build_ssml(title, author, paras)
    if not ssml_chunks:
        logger.warning(f"TTS: No SSML for item {item_id}. Aborting.")
        return {"uri": None, "duration_seconds": 0, "error": "SSML generation resulted in no chunks."}

    total_chars = sum(len(chunk) for chunk in ssml_chunks)
    logger.info(f"TTS: Total billable characters for {item_id}: {total_chars}")

    segment_files = []
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
    )

    try:
        with tempfile.TemporaryDirectory(prefix=f"speakloudtts_{item_id}_") as tmpdir:
            logger.info(f"TTS: Using temp dir {tmpdir}")
            # Synthesize all chunks
            for idx, ssml_text in enumerate(ssml_chunks):
                lang_code = "-".join(voice_name.split('-')[:2])
                voice_params = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_name)
                try:
                    response = tts_client.synthesize_speech(
                        request={"input": texttospeech.SynthesisInput(ssml=ssml_text),
                                 "voice": voice_params,
                                 "audio_config": audio_config}
                    )
                    seg_path = os.path.join(tmpdir, f"segment_{idx}.mp3")
                    with open(seg_path, "wb") as out_file:
                        out_file.write(response.audio_content)
                    segment_files.append(seg_path)
                    logger.debug(f"TTS: Saved segment {idx+1} to {seg_path}")
                except Exception as e:
                    logger.error(f"TTS: Failed to synthesize SSML chunk {idx+1}/{len(ssml_chunks)}: {e}", exc_info=True)
                    raise Exception(f"TTS failed for chunk {idx+1}: {e}")
            if not segment_files:
                logger.error(f"TTS: No segments produced for {item_id}.")
                return {"uri": None, "duration_seconds": 0, "error": "No audio segments produced by TTS."}

            # Write concat file for ffmpeg
            concat_path = os.path.join(tmpdir, "segments.txt")
            with open(concat_path, "w") as f:
                for path in segment_files:
                    f.write(f"file '{path}'\n")
            merged_path = os.path.join(tmpdir, output_gcs_filename)
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_path, "-c", "copy", merged_path
            ]
            logger.info(f"TTS: Running ffmpeg: {' '.join(ffmpeg_cmd)}")
            process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            if process.returncode != 0:
                err_msg = f"ffmpeg failed with code {process.returncode}. Stderr: {process.stderr.strip()}. Stdout: {process.stdout.strip()}"
                logger.error(f"TTS: {err_msg}")
                raise Exception(err_msg)

            # Probe duration (optional)
            duration = 0.0
            try:
                ffprobe_cmd = [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", merged_path
                ]
                res = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
                duration = float(res.stdout.strip())
                logger.info(f"TTS: Duration: {duration:.2f}s")
            except Exception as e:
                logger.warning(f"TTS: Could not probe audio duration: {e}")

            # Upload to GCS
            blob.upload_from_filename(merged_path, content_type="audio/mpeg")
            logger.info(f"TTS: Uploaded to gs://{GCS_BUCKET}/{output_gcs_filename}")

            return {
                "gcs_path": output_gcs_filename,
                "duration_seconds": duration,
                "gcs_bucket": GCS_BUCKET,
                "num_segments": len(segment_files),
                "error": None
            }
    except Exception as e:
        logger.error(f"TTS: Critical error for {item_id}: {e}", exc_info=True)
        return {
            "gcs_path": None, "duration_seconds": 0, "error": f"Synthesis process failed: {str(e)}"
        }
