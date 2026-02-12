import os
import uuid
import shutil
import subprocess
import threading
import time
from flask import Flask, request, jsonify, send_from_directory

import whisper

app = Flask(__name__, static_folder="static")

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Find yt-dlp: prefer the one in the same virtual environment as this script
YTDLP_BIN = os.path.join(os.path.dirname(os.sys.executable), "yt-dlp")
if not os.path.isfile(YTDLP_BIN):
    YTDLP_BIN = shutil.which("yt-dlp") or "yt-dlp"

# Load whisper model once at startup (use "base" for speed; "medium" or "large" for accuracy)
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
print(f"Loading Whisper model '{MODEL_SIZE}'... (this may take a moment on first run)")
model = whisper.load_model(MODEL_SIZE)
print("Whisper model loaded.")

# In-memory job store  {job_id: {status, progress, transcript, error}}
jobs = {}
jobs_lock = threading.Lock()


def update_job(job_id, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def transcribe_worker(job_id, video_url):
    """Background worker: download video -> extract audio -> transcribe."""
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    audio_path = os.path.join(job_dir, "audio.mp3")

    try:
        # --- Step 1: Download video & extract audio with yt-dlp ---
        update_job(job_id, status="downloading", progress=10)

        result = subprocess.run(
            [
                YTDLP_BIN,
                "--no-playlist",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "5",
                "--output", os.path.join(job_dir, "%(title)s.%(ext)s"),
                "--postprocessor-args", "-ac 1 -ar 16000",
                video_url,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            update_job(job_id, status="error",
                       error=f"Download failed: {result.stderr[:500]}")
            return

        # Find the downloaded mp3 file
        mp3_files = [f for f in os.listdir(job_dir) if f.endswith(".mp3")]
        if not mp3_files:
            update_job(job_id, status="error", error="No audio file produced after download.")
            return

        audio_path = os.path.join(job_dir, mp3_files[0])

        # --- Step 2: Transcribe with Whisper ---
        update_job(job_id, status="transcribing", progress=50)

        result = model.transcribe(audio_path, verbose=False)

        # Build both plain text and timestamped segments
        plain_text = result["text"].strip()
        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            })

        update_job(
            job_id,
            status="done",
            progress=100,
            transcript=plain_text,
            segments=segments,
            language=result.get("language", "unknown"),
        )

    except subprocess.TimeoutExpired:
        update_job(job_id, status="error", error="Download timed out (10 min limit).")
    except Exception as e:
        update_job(job_id, status="error", error=str(e))
    finally:
        # Clean up downloaded files to save disk space
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception:
            pass


# ---- API Routes ----

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/transcribe", methods=["POST"])
def start_transcription():
    data = request.get_json(force=True)
    video_url = data.get("url", "").strip()

    if not video_url:
        return jsonify({"error": "No URL provided."}), 400

    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "transcript": None,
            "segments": None,
            "error": None,
            "language": None,
        }

    thread = threading.Thread(target=transcribe_worker, args=(job_id, video_url), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404

    return jsonify(job)


@app.route("/api/cleanup/<job_id>", methods=["DELETE"])
def cleanup_job(job_id):
    """Remove a finished job from memory."""
    with jobs_lock:
        jobs.pop(job_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Transcript Website on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
