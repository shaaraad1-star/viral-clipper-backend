import os
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
        raise HTTPException(status_code=403, detail="Unauthorized")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(request.url, download=False)

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
        raise HTTPException(status_code=403, detail="Unauthorized")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(request.url, download=False)

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
        "--no-warnings",
        "--quiet",
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
        raise HTTPException(status_code=403, detail="Unauthorized")

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

    yt_cmd = [
        "yt-dlp",
        "-f",
        "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
        "-o",
        "-",
        "--no-warnings",
        "--quiet",
        request.url,
    ]

    ff_cmd = [
        "ffmpeg",
        "-i",
        "pipe:0",
        "-ss",
        f"{request.start:.2f}",
        "-t",
        f"{duration:.2f}",

        # MUCH more reliable than -c copy
        "-c:v",
        "libx264",
        "-c:a",
        "aac",

        "-f",
        ff_fmt,

        "-movflags",
        "+frag_keyframe+empty_moov",

        "-preset",
        "veryfast",

        "-y",
        "pipe:1",
    ]

    yt_proc = subprocess.Popen(
        yt_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    ff_proc = subprocess.Popen(
        ff_cmd,
        stdin=yt_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    yt_proc.stdout.close()

    def stream_gen():
        try:
            while True:
                chunk = ff_proc.stdout.read(64 * 1024)

                if not chunk:
                    break

                yield chunk

        finally:
            if ff_proc.stdout:
                ff_proc.stdout.close()

            if ff_proc.stderr:
                ff_proc.stderr.close()

            ff_proc.wait()
            yt_proc.wait()

    return StreamingResponse(
        stream_gen(),
        media_type=mime,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition":
                f'attachment; filename="clip.{request.format}"',
        },
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
        raise HTTPException(status_code=403, detail="Unauthorized")

    return {
        "message": "Transcription logic initialized"
    }
