import os
import time
import uuid
import traceback
import asyncio
import shutil
from urllib.parse import quote
from pathlib import Path
from contextlib import asynccontextmanager

import aiofiles
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.log_config import setup_logger

# ---------- Logger ----------
logger = setup_logger("main")
logger.info("Logger initialized")

# ---------- Connection manager for WebSocket ----------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Failed to send message: %s", e)
                disconnected.append(connection)
        
        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()

# ---------- App setup ----------
def _ensure_ffmpeg_tools():
    """Ensure `ffmpeg` and `ffprobe` are available on startup."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(
            f"Missing required system tools: {', '.join(missing)}. "
            "Install ffmpeg / ffprobe before starting the app."
        )
    logger.info("ffmpeg and ffprobe are present")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifecycle: startup and shutdown"""
    logger.info("Application startup")

    _ensure_ffmpeg_tools()
    
    # Initialize janus queue (async/thread bridge)
    import janus
    from app import downloader
    downloader._update_queue = janus.Queue()
    
    # Start global queue monitor task
    monitor_task = asyncio.create_task(_monitor_update_queue_global())
    logger.info("Global queue monitor started (async-awaitable)")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Application shutdown")
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        logger.info("Queue monitor stopped")
    finally:
        # Close janus queue
        downloader._update_queue.close()
        await downloader._update_queue.wait_closed()


app = FastAPI(title="yt-downloader", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
templates_path = Path(__file__).parent / "templates"

if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


def _new_key():
    return uuid.uuid4().hex


# ---------- File processor ----------
async def _run_ffmpeg(cmd):
    """Run FFmpeg asynchronously"""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return {
        "returncode": process.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode()
    }


async def _probe_audio_codec(src_path: str) -> str | None:
    """Probe the first audio stream codec with ffprobe."""
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        src_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning("ffprobe failed for %s: %s", src_path, stderr.decode().strip())
        return None
    return stdout.decode().strip().lower() or None


async def process_file(src_path: str, dst_dir: str, audio_only: bool, key: str, title: str):
    """Process downloaded file with FFmpeg"""
    DST_DIR = "/app/download"
    full_dir = os.path.join(DST_DIR, dst_dir)
    os.makedirs(full_dir, exist_ok=True)

    filename = os.path.basename(src_path)
    name, ext = os.path.splitext(filename)

    name = name[:70]
    ext = ext.lower()

    if audio_only:
        dst = os.path.join(full_dir, f"{name}.aac")
        if ext in {".m4a", ".aac"}:
            dst = os.path.join(full_dir, f"{name}{ext}")
            logger.info("Source file %s is already AAC/M4A, moving file without re-encoding", src_path)
            await asyncio.to_thread(shutil.move, src_path, dst)
            cmd = None
        else:
            audio_codec = await _probe_audio_codec(src_path)
            logger.info("Probed audio codec for %s: %s", src_path, audio_codec)
            if audio_codec in {"aac", "mp4a"}:
                logger.info("Audio codec is already AAC, copying without re-encoding")
                cmd = ["ffmpeg", "-y", "-i", src_path, "-vn", "-map", "0:a:0", "-c:a", "copy", dst]
            else:
                logger.info("Audio codec is %s, re-encoding to AAC", audio_codec)
                cmd = ["ffmpeg", "-y", "-i", src_path, "-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", dst]
    else:  # video
        logger.info("Processing video file %s, copying streams without re-encoding", src_path)
        dst = os.path.join(full_dir, f"{name}.mp4")
        if ext == ".mp4":
            logger.info("Source file %s is already MP4, moving file without re-encoding", src_path)
            await asyncio.to_thread(shutil.move, src_path, dst)
            cmd = None
        else:
            cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    if cmd is not None:
        logger.info("Running FFmpeg command: %s", " ".join(cmd))
        proc_result = await _run_ffmpeg(cmd)
        if proc_result["returncode"] != 0:
            logger.error("FFmpeg error: %s", proc_result["stderr"])
            raise RuntimeError(f"FFmpeg failed: {proc_result['stderr']}")

    final_path = dst
    file_name = os.path.basename(final_path)
    safe_name = quote(file_name)

    logger.info("File processed: %s", final_path)
    await manager.broadcast({
        "type": "download_complete",
        "key": key,
        "status": "done",
        "title": title,
        "download_url": f"/download/aac/{safe_name}"
    })
    logger.info("Download URL emitted for key %s", key)


# ---------- Routes ----------
@app.get("/")
async def index():
    """Serve the main HTML page"""
    file_path = templates_path / "index.html"
    if file_path.exists():
        return FileResponse(file_path, media_type="text/html")
    return {"error": "index.html not found"}


@app.post("/inspect")
async def inspect(request: Request):
    """Inspect video info without downloading"""
    data = await request.json()
    url = data.get("url")

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        from app.downloader import get_video_info
        info = get_video_info(url)
        return {
            "title": info.get("title"),
            "formats": info.get("formats", [])
        }
    except Exception as e:
        logger.error("inspect failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/download")
async def download(request: Request):
    """Start a download job"""
    data = await request.json()

    url = data.get("url")
    format_id = data.get("format_id")
    audio_only = str(data.get("audio_only", "0")) == "1"

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    key = _new_key()

    await manager.broadcast({
        "type": "download_started",
        "key": key,
        "status": "queued"
    })
    logger.info("Scheduled download job for key %s", key)

    # Start background task
    asyncio.create_task(bg_download(url, format_id, audio_only, key))

    return {"key": key, "status": "queued"}


async def bg_download(url: str, format_id: str | None, audio_only: bool, key: str):
    """Background download task - can run in parallel for multiple keys"""
    logger.info("bg_download started for key %s", key)
    try:
        from app.downloader import download_video
        from concurrent.futures import ThreadPoolExecutor

        await manager.broadcast({
            "type": "download_status",
            "key": key,
            "status": "downloading",
            "message": "Downloading..."
        })
        logger.info("Calling download_video for key %s", key)

        # Run blocking download_video in executor with optimized thread pool
        # Default: None uses default ThreadPoolExecutor (min(32, os.cpu_count() + 4) workers)
        # For many concurrent downloads, increase max_workers
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            None,
            download_video,
            url,
            "downloads",
            format_id,
            audio_only,
            key
        )
        
        logger.info("download_video finished for key %s, filepath=%s", key, result.get("filepath"))

        await manager.broadcast({
            "type": "download_status",
            "key": key,
            "status": "processing",
            "message": "Processing...",
            "title": result.get("title")
        })
        logger.info("Processing file for key %s", key)

        # Process file
        await process_file(result["filepath"], "aac", audio_only, key, result.get("title"))

    except Exception as e:
        logger.error(traceback.format_exc())
        await manager.broadcast({
            "type": "download_complete",
            "key": key,
            "status": "error",
            "message": str(e)
        })


async def _monitor_update_queue_global():
    """
    Global queue monitor - runs once for entire app lifetime.
    Monitors shared queue and broadcasts updates for ALL keys to WebSocket clients.
    Batches multiple updates for efficient broadcast with many concurrent downloads.
    """
    from app.downloader import _update_queue
    
    logger.info("Global queue monitor started (awaiting async queue)")
    async_queue = _update_queue.async_q  # Get async side of janus queue
    
    while True:
        try:
            # Collect updates: get first item, then batch remaining items (non-blocking)
            batch = []
            
            # Wait for first item (blocking)
            first_update = await asyncio.wait_for(async_queue.get(), timeout=30)
            batch.append(first_update)
            
            # Collect remaining items without blocking (up to 50 items per batch)
            for _ in range(49):
                try:
                    update = async_queue.get_nowait()
                    batch.append(update)
                except:
                    break
            
            # Broadcast batch efficiently using asyncio.gather
            if batch:
                broadcast_tasks = [
                    manager.broadcast({
                        "type": "download_status",
                        **update
                    })
                    for update in batch
                ]
                await asyncio.gather(*broadcast_tasks, return_exceptions=True)
                logger.debug("Broadcasted %d updates to %d clients", 
                           len(batch), len(manager.active_connections))
                    
        except asyncio.TimeoutError:
            # Periodic health check
            logger.debug("Queue monitor health check - no updates in 30s")
        except asyncio.CancelledError:
            logger.info("Global queue monitor cancelled")
            break
        except Exception as e:
            logger.error("Queue monitor error: %s", e)
            break


@app.get("/download/aac/{filename}")
async def download_aac(filename: str):
    """Download processed file"""
    DST_DIR = "/app/download/aac"
    path = os.path.join(DST_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    ascii_filename = ''.join(c if ord(c) < 128 else '_' for c in filename)
    safe_filename = quote(filename)
    file_size = os.path.getsize(path)

    headers = {
        "Content-Disposition": f"attachment; filename='{ascii_filename}'; filename*=UTF-8''{safe_filename}",
        "Content-Length": str(file_size),
        "Content-Type": "application/octet-stream"
    }

    async def file_generator():
        async with aiofiles.open(path, 'rb') as f:
            while True:
                chunk = await f.read(262144)  # 256KB chunks for faster streaming
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(file_generator(), headers=headers)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            logger.info("Received from WebSocket: %s", data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


# ---------- Health check ----------
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "yt-downloader",
        "timestamp": int(time.time())
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    env = os.environ.get("ENV", "production").lower()

    if env == "local":
        logger.info("LOCAL dev server on port %s", port)
        uvicorn.run(app, host="0.0.0.0", port=port, reload=True)
    else:
        logger.info("PROD server on port %s", port)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
