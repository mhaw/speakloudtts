# tts.py
import logging
import os
import tempfile
import subprocess
import html # For SSML escaping
from typing import List, Dict, Tuple
from google.cloud import texttospeech
from google.cloud import storage

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME", "speakloudtts-audio-files")
MAX_BYTES = 4500  # Max SSML payload size for Google TTS (limit is 5000)

# ─── GCP Clients (Initialization should be handled by the calling app, e.g. app.py) ───
# For modularity, it's better if these are passed or accessed via a shared context/app instance.
# However, if this module is run standalone or needs its own clients:
TTS_CLIENT_INSTANCE = None
STORAGE_CLIENT_INSTANCE = None
GCS_BUCKET_INSTANCE = None

def _get_tts_client():
    global TTS_CLIENT_INSTANCE
    if TTS_CLIENT_INSTANCE is None:
        try:
            TTS_CLIENT_INSTANCE = texttospeech.TextToSpeechClient()
            logger.info("Initialized TextToSpeechClient in tts.py")
        except Exception as e:
            logger.critical(f"tts.py: Failed to initialize TextToSpeechClient: {e}", exc_info=True)
            raise
    return TTS_CLIENT_INSTANCE

def _get_storage_client_and_bucket():
    global STORAGE_CLIENT_INSTANCE, GCS_BUCKET_INSTANCE
    if STORAGE_CLIENT_INSTANCE is None or GCS_BUCKET_INSTANCE is None:
        try:
            STORAGE_CLIENT_INSTANCE = storage.Client()
            GCS_BUCKET_INSTANCE = STORAGE_CLIENT_INSTANCE.bucket(GCS_BUCKET)
            logger.info(f"Initialized StorageClient and bucket '{GCS_BUCKET}' in tts.py")
        except Exception as e:
            logger.critical(f"tts.py: Failed to initialize StorageClient or bucket '{GCS_BUCKET}': {e}", exc_info=True)
            raise
    return STORAGE_CLIENT_INSTANCE, GCS_BUCKET_INSTANCE


# ─── Audio Config ───────────────────────────────────────────────────────────────
AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3,
    speaking_rate=1.1, # 10% faster
    # Example: pitch = 0, sample_rate_hertz = 24000 (for higher quality WaveNet/Studio)
    # effects_profile_id=['medium-bluetooth-speaker-class-device'] # For specific audio profiles
)

def _build_ssml(title: str, author: str, paragraphs: List[str]) -> List[str]:
    logger.debug(f"Building SSML for title: '{title}', author: '{author}', {len(paragraphs)} paragraphs.")
    speak_open_tag = "<speak>"
    speak_close_tag = "</speak>"
    
    prefix_content = ""
    if title:
        # Escape title for SSML
        escaped_title = html.escape(title)
        prefix_content += f"<emphasis level='strong'>{escaped_title}</emphasis><break time='600ms'/>"
    if author:
        escaped_author = html.escape(author)
        prefix_content += f"By {escaped_author}<break time='800ms'/>"

    chunks = []
    current_chunk_ssml_parts = [] # Store parts like ["<p>...</p>", "<break.../>"]
    current_chunk_byte_len = len(speak_open_tag.encode('utf-8')) + len(speak_close_tag.encode('utf-8'))
    
    # Add initial prefix to the first chunk if it exists
    if prefix_content:
        prefix_bytes = len(prefix_content.encode('utf-8'))
        if prefix_bytes < MAX_BYTES - current_chunk_byte_len : # Check if prefix itself fits
            current_chunk_ssml_parts.append(prefix_content)
            current_chunk_byte_len += prefix_bytes
        else:
            logger.warning("SSML prefix content is too large for a single chunk. It might be truncated or split.")
            # Basic split for very large prefix (rare)
            # This part can be made more robust if needed
            chunks.append(speak_open_tag + prefix_content[:MAX_BYTES // 2] + speak_close_tag)
            prefix_content = prefix_content[MAX_BYTES // 2:]


    for p_text in paragraphs:
        if not p_text.strip(): # Skip empty paragraphs
            logger.debug("Skipping empty paragraph in SSML generation.")
            continue
            
        escaped_p_text = html.escape(p_text)
        paragraph_ssml = f"<p>{escaped_p_text}</p><break time='500ms'/>" # Adjusted break time
        para_bytes = len(paragraph_ssml.encode('utf-8'))

        if current_chunk_byte_len + para_bytes > MAX_BYTES:
            if current_chunk_ssml_parts: # Finalize current chunk
                chunks.append(speak_open_tag + "".join(current_chunk_ssml_parts) + speak_close_tag)
                logger.debug(f"SSML chunk created, length approx {current_chunk_byte_len} bytes.")
            # Start new chunk with the current paragraph
            current_chunk_ssml_parts = [paragraph_ssml]
            current_chunk_byte_len = len(speak_open_tag.encode('utf-8')) + len(speak_close_tag.encode('utf-8')) + para_bytes
        else:
            current_chunk_ssml_parts.append(paragraph_ssml)
            current_chunk_byte_len += para_bytes

    # Add the last remaining chunk
    if current_chunk_ssml_parts:
        chunks.append(speak_open_tag + "".join(current_chunk_ssml_parts) + speak_close_tag)
        logger.debug(f"Final SSML chunk created, length approx {current_chunk_byte_len} bytes.")
    
    if not chunks and prefix_content: # Only prefix, no paragraphs
         chunks.append(speak_open_tag + prefix_content + speak_close_tag)
         logger.debug("SSML created with only prefix content.")

    logger.info(f"Built {len(chunks)} SSML chunks for synthesis.")
    if not chunks:
        logger.warning("No SSML chunks were generated. Input text might have been empty or only whitespace.")
    return chunks


def synthesize_long_text(title: str, author: str, full_text: str, item_id: str, voice_name: str) -> Dict[str, any]:
    logger.info(f"Starting TTS synthesis for item_id: {item_id}, title: '{title}', voice: {voice_name}.")
    
    try:
        tts_client = _get_tts_client()
        _, bucket_instance = _get_storage_client_and_bucket() # Ensure bucket_instance is from here
    except Exception as e:
        # Error already logged by _get_... functions.
        return {"uri": None, "duration_seconds": 0, "error": f"Failed to initialize GCP clients: {str(e)}"}


    paras = [p.strip() for p in full_text.split('\n') if p.strip()]
    if not paras and not title and not author: # Check if there's any content at all
        logger.warning(f"No paragraphs, title, or author found for item_id: {item_id}. Aborting synthesis.")
        return {"uri": None, "duration_seconds": 0, "error": "No content to synthesize."}

    ssml_chunks = _build_ssml(title, author, paras)
    if not ssml_chunks:
        logger.warning(f"No SSML chunks generated for item_id: {item_id}. Aborting synthesis.")
        return {"uri": None, "duration_seconds": 0, "error": "SSML generation resulted in no chunks."}

    segment_files_paths = [] # Store paths of successfully created segment files
    output_gcs_filename = f"{item_id}.mp3" # Filename in GCS

    try:
        with tempfile.TemporaryDirectory(prefix=f"speakloudtts_{item_id}_") as tmpdir:
            logger.info(f"Using temporary directory: {tmpdir} for item_id: {item_id}")

            for idx, ssml_text in enumerate(ssml_chunks):
                synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
                # Language code might also depend on the voice, many en-* voices exist
                lang_code_part = voice_name.split('-')[0] + '-' + voice_name.split('-')[1] # e.g., en-US
                voice_params = texttospeech.VoiceSelectionParams(
                    language_code=lang_code_part, 
                    name=voice_name,
                )
                
                logger.debug(f"Synthesizing chunk {idx + 1}/{len(ssml_chunks)} for item {item_id}. SSML length: {len(ssml_text.encode('utf-8'))} bytes.")
                try:
                    response = tts_client.synthesize_speech(
                        request={"input": synthesis_input, "voice": voice_params, "audio_config": AUDIO_CONFIG}
                    )
                    segment_path = os.path.join(tmpdir, f"segment_{idx}.mp3") # Simpler segment name
                    with open(segment_path, "wb") as out_file:
                        out_file.write(response.audio_content)
                    segment_files_paths.append(segment_path)
                    logger.debug(f"Saved audio segment {idx + 1} to {segment_path} ({len(response.audio_content)} bytes).")
                except Exception as e:
                    logger.error(f"Failed to synthesize SSML chunk {idx + 1} for item {item_id}: {e}", exc_info=True)
                    # Decide if one failed chunk should abort the whole process or try to continue
                    # For now, let's abort if any chunk fails, as it would result in incomplete audio.
                    raise Exception(f"TTS API call failed for chunk {idx + 1}: {str(e)}")


            if not segment_files_paths:
                logger.warning(f"No audio segments were successfully synthesized for item_id: {item_id}.")
                return {"uri": None, "duration_seconds": 0, "error": "No audio segments produced by TTS."}

            list_file_path = os.path.join(tmpdir, "segment_list.txt")
            with open(list_file_path, "w") as f:
                for seg_path in segment_files_paths:
                    # FFmpeg needs paths to be escaped/quoted if they contain special characters.
                    # os.path.abspath might be safer for ffmpeg if paths are complex.
                    # For tempfile paths, direct usage is usually fine.
                    f.write(f"file '{seg_path}'\n") 
            logger.debug(f"FFmpeg segment list file created at {list_file_path} with {len(segment_files_paths)} entries.")
            
            merged_mp3_path = os.path.join(tmpdir, output_gcs_filename) # Local merged file
            
            ffmpeg_cmd = [
                "ffmpeg", "-y", # Overwrite output files without asking
                "-f", "concat", "-safe", "0",
                "-i", list_file_path,
                "-c", "copy", # Segments are already MP3
                merged_mp3_path
            ]
            logger.info(f"Running ffmpeg for item {item_id}: {' '.join(ffmpeg_cmd)}")
            
            process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=False) # Don't check=True, handle manually
            if process.returncode != 0:
                err_msg = f"ffmpeg concatenation failed for item {item_id}. Code: {process.returncode}. Stderr: {process.stderr.strip()}"
                logger.error(err_msg)
                logger.debug(f"ffmpeg stdout for item {item_id}: {process.stdout.strip()}") # Log stdout for more info
                raise Exception(err_msg)
            logger.info(f"Successfully merged {len(segment_files_paths)} audio segments to {merged_mp3_path} for item {item_id}.")

            duration_seconds = 0.0
            try:
                ffprobe_cmd = [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", merged_mp3_path
                ]
                result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
                duration_seconds = float(result.stdout.strip())
                logger.info(f"Probed duration for item {item_id}: {duration_seconds:.2f} seconds.")
            except Exception as e:
                logger.warning(f"Could not probe audio duration for item {item_id} using ffprobe: {e}. Duration set to 0.", exc_info=True)
            
            logger.info(f"Uploading {merged_mp3_path} to GCS: gs://{GCS_BUCKET}/{output_gcs_filename} for item {item_id}.")
            blob = bucket_instance.blob(output_gcs_filename)
            blob.upload_from_filename(merged_mp3_path, content_type="audio/mpeg")
            logger.info(f"Upload successful for item {item_id}. Public URL (if bucket is public): {blob.public_url}")
            
            # Using the standard GCS URI format
            uri = f"https://storage.googleapis.com/{GCS_BUCKET}/{output_gcs_filename}"
            
            return {
                "uri": uri, "duration_seconds": duration_seconds, "gcs_bucket": GCS_BUCKET,
                "gcs_path": output_gcs_filename, "num_segments": len(segment_files_paths),
                "error": None
            }

    except Exception as e:
        logger.error(f"Critical error in synthesize_long_text for item_id {item_id}: {e}", exc_info=True)
        return {
            "uri": None, "duration_seconds": 0, "error": f"Synthesis process failed: {str(e)}"
        }
    # Temporary directory 'tmpdir' and its contents are automatically cleaned up here.