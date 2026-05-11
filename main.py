import os
import subprocess
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

SERVICE_SECRET = os.getenv("SERVICE_SECRET")

class VideoRequest(BaseModel):
    url: str


@app.post("/resolve")
async def resolve_video(request: VideoRequest, x_service_secret: str = Header(None)):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(request.url, download=False)
        return {
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "id": info.get("id"),
        }


@app.post("/download")
async def download_video(request: VideoRequest, x_service_secret: str = Header(None)):
    """Stream video bytes using yt-dlp piped to stdout — no temp files."""
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Validate URL first
    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(request.url, download=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid video: {str(e)[:200]}")

    title = info.get("title", "video")

    # Stream via subprocess — yt-dlp outputs to stdout
    cmd = [
        "yt-dlp",
        "-f", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
        "-o", "-",
        "--no-warnings",
        "--quiet",
        request.url,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stream_gen():
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
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


@app.post("/transcript")
async def get_transcript(request: VideoRequest, x_service_secret: str = Header(None)):
    if SERVICE_SECRET and x_service_secret != SERVICE_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    return {"message": "Transcription logic initialized"}


@app.get("/health")
def health():
    return {"status": "online"}
