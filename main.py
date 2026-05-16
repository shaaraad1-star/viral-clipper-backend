import os
import shutil
import tempfile
import subprocess

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import yt_dlp


app = FastAPI()

SERVICE_SECRET = os.getenv("SERVICE_SECRET")


# =========================
# MODELS
# =========================

class VideoRequest(BaseModel):
    url: str


class ClipRequest(BaseModel):
    url: str
    start: float = 0
    end: float = 0
    format: str = "mp4"


# =========================
# HEALTH
# =========================

@app.get("/health")
def health():
    return {"status": "online"}


# =========================
# RESOLVE VIDEO INFO
# =========================

@app.post("/resolve")
async def resolve_video(
    request: VideoRequest,
    x_service_secret: str = Header(None)
):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                request.url,
                download=False
            )

        return {
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "id": info.get("id"),
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to resolve video: {str(e)[:200]}"
        )


# =========================
# DOWNLOAD FULL VIDEO
# =========================

@app.post("/download")
async def download_video(
    request: VideoRequest,
    x_service_secret: str = Header(None)
):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                request.url,
                download=False
            )

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid video: {str(e)[:200]}"
        )

    title = info.get("title", "video")

    cmd = [
        "yt-dlp",
        "-f",
        "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
        "-o",
        "-",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "--extractor-args",
        "youtube:player_client=android",
        request.url,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def stream_gen():
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)

                if not chunk:
                    break

                yield chunk

        finally:
            if proc.stdout:
                proc.stdout.close()

            if proc.stderr:
                proc.stderr.close()

            proc.wait()

    return StreamingResponse(
        stream_gen(),
        media_type="video/mp4",
        headers={
            "X-Video-Title": title,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "X-Video-Title",
        },
    )


# =========================
# CLIP VIDEO
# =========================

@app.post("/clip")
async def render_clip(
    request: ClipRequest,
    x_service_secret: str = Header(None)
):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    duration = request.end - request.start

    if duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid clip range"
        )

    fmt_map = {
        "mp4": "mp4",
        "mov": "mov",
        "mkv": "matroska",
        "webm": "webm",
    }

    mime_map = {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
        "webm": "video/webm",
    }

    ff_fmt = fmt_map.get(request.format, "mp4")
    mime = mime_map.get(request.format, "video/mp4")

    tmp_dir = tempfile.mkdtemp(prefix="vc-")

    raw_file = os.path.join(tmp_dir, "raw.mp4")
    clip_file = os.path.join(
        tmp_dir,
        f"clip.{request.format}"
    )

    try:
        # =========================
        # STEP 1: DOWNLOAD SPECIFIC SECTON ONLY
        # =========================
        dl_cmd = [
            "yt-dlp",
            "-f", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "--download-sections", f"*{request.start}-{request.end}",
            "--force-keyframes-at-cuts",
            "-o", raw_file,
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "--extractor-args", "youtube:player_client=android",
            request.url,
        ]

        result = subprocess.run(
            dl_cmd,
            capture_output=True,
            timeout=300
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail="Failed to download video section"
            )

        if not os.path.exists(raw_file):
            raise HTTPException(
                status_code=502,
                detail="Downloaded temporary segment missing"
            )

        # =========================
        # STEP 2: RE-ENC CODE / CONVERT TO TARGET FORMAT
        # =========================
        trim_cmd = [
            "ffmpeg",
            "-y",
            "-i", raw_file,
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-f", ff_fmt,
            clip_file,
        ]
        
        result = subprocess.run(
            trim_cmd,
            capture_output=True,
            timeout=120
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail="Failed to process clip formatting"
            )

        if not os.path.exists(clip_file):
            raise HTTPException(
                status_code=502,
                detail="Processed clip file missing"
            )

        clip_size = os.path.getsize(clip_file)

        if clip_size == 0:
            raise HTTPException(
                status_code=502,
                detail="Processed file size evaluates to 0"
            )

        # =========================
        # STEP 3: STREAM CLIP
        # =========================
        def stream_gen():
            try:
                with open(clip_file, "rb") as f:
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                shutil.rmtree(
                    tmp_dir,
                    ignore_errors=True
                )

        return StreamingResponse(
            stream_gen(),
            media_type=mime,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Length": str(clip_size),
                "Content-Disposition": f'attachment; filename="clip.{request.format}"',
            },
        )

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=502,
            detail=str(e)
        )


# =========================
# TRANSCRIPT PLACEHOLDER
# =========================

@app.post("/transcript")
async def get_transcript(
    request: VideoRequest,
    x_service_secret: str = Header(None)
):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    return {
        "message": "Transcription logic initialized"
    }
