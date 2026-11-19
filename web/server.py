"""StreamClips Web Server - Modern Automation Studio for Short-Form Video Creation."""

import asyncio
import datetime
import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Insert stream-clips scripts to sys.path
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR.parent
SKILL_DIR = WORKSPACE_DIR / ".agents" / "skills" / "stream-clips"
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sc import brains, discover, media, memes, pipeline, produce, settings
from sc.common import CACHE, DATA, MODELS, Problem, add_listener, clock, human, keywords_for, probe, remove_listener, say, slug, write_json

app = FastAPI(title="StreamClips AI Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Job Management & Realtime State
# ============================================================================

class Job:
    def __init__(self, job_id: str, payload: dict):
        self.id = job_id
        self.payload = payload
        self.status = "queued"  # queued, running, completed, failed, cancelled
        self.progress = 0
        self.current_step = "Starting job..."
        self.logs: List[dict] = []
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.thread: Optional[threading.Thread] = None
        self.cancelled = False

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "logs_count": len(self.logs),
            "created_at": self.created_at,
            "payload": {k: v for k, v in self.payload.items() if k != "cookies"},
            "result": self.result,
            "error": self.error,
        }


jobs: Dict[str, Job] = {}
active_connections: List[WebSocket] = []
connections_lock = threading.Lock()


def broadcast_event(event_type: str, data: dict):
    """Notify all connected WebSockets asynchronously."""
    message = json.dumps({"type": event_type, "data": data})
    with connections_lock:
        to_remove = []
        for ws in active_connections:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_text(message), loop)
            except Exception:
                to_remove.append(ws)
        for dead in to_remove:
            if dead in active_connections:
                active_connections.remove(dead)


# Event loop holder for async websocket calls from background threads
loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
def startup():
    global loop
    loop = asyncio.get_event_loop()

    # Register logging callback into sc.common
    def log_handler(log_entry):
        msg = log_entry.get("msg", "")
        # Find active job
        for j in jobs.values():
            if j.status == "running":
                j.logs.append(log_entry)
                # Infer step and progress
                low = msg.lower()
                if "downloading the audio" in low or "extracting audio" in low:
                    j.current_step = "📥 Downloading / Extracting Audio"
                    j.progress = 15
                elif "listening to" in low or "heard" in low:
                    j.current_step = "🎙️ Whisper AI Transcribing Audio"
                    j.progress = 35
                elif "reading the chat" in low or "analyzing audio spikes" in low:
                    j.current_step = "📊 Analyzing Audio Spikes & Highlights"
                    j.progress = 50
                elif "picked" in low and "moment" in low:
                    j.current_step = "🎯 Viral Highlights Selected"
                    j.progress = 65
                elif "clip " in low and ("stack" in low or "crop" in low or "blur" in low or "slicing" in low or "sync" in low):
                    j.current_step = f"📐 Producing 9:16 Video Clip ({msg[:40]})"
                    j.progress = 80
                elif "splicing" in low or "meme" in low:
                    j.current_step = "🎭 Splicing Indian Meme Reaction"
                    j.progress = 88
                elif "done:" in low:
                    j.current_step = "✅ Video Processing Complete"
                    j.progress = 100

                broadcast_event("job_update", j.to_dict())
                broadcast_event("job_log", {"job_id": j.id, "log": log_entry})
                break

    add_listener(log_handler)


# ============================================================================
# API Models
# ============================================================================

class ClipRequest(BaseModel):
    url: str
    topic: Optional[str] = "Viral Clips"
    keywords: Optional[str] = None
    clips: Optional[int] = 3
    layout: Optional[str] = "auto"  # auto, stack, crop, blur
    meme: Optional[str] = "auto"   # auto, none, or specific meme id
    meme_style: Optional[str] = "insert"  # insert, outro
    language: Optional[str] = None  # None/auto, en, hi, etc.
    brain: Optional[str] = "auto"   # auto, heuristic, gemini_api, etc.
    model: Optional[str] = None
    section: Optional[str] = None   # "0:10:00-0:30:00"
    min_len: Optional[int] = 15
    max_len: Optional[int] = 55
    fast: Optional[bool] = True
    cam: Optional[str] = None
    focus: Optional[str] = None
    cookies: Optional[str] = None


class CustomClipRequest(BaseModel):
    url: str
    start: float
    end: float
    title: Optional[str] = "Viral Highlight"
    type: Optional[str] = "reaction"
    layout: Optional[str] = "auto"
    meme: Optional[str] = "auto"
    meme_style: Optional[str] = "insert"
    language: Optional[str] = None
    fast: Optional[bool] = True
    cam: Optional[str] = None


class SettingsUpdate(BaseModel):
    brain: Optional[str] = None
    layout: Optional[str] = None
    clips: Optional[int] = None
    min_len: Optional[int] = None
    max_len: Optional[int] = None
    language: Optional[str] = None
    meme: Optional[str] = None
    meme_style: Optional[str] = None
    crf: Optional[int] = None
    fast: Optional[bool] = None
    gemini_api_key: Optional[str] = None


# ============================================================================
# Core Worker Logic
# ============================================================================

class OptionsAdapter:
    def __init__(self, data: dict):
        self.url = data.get("url")
        self.urls = [self.url]
        self.topic = data.get("topic") or "Clips"
        self.keywords = data.get("keywords")
        self.clips = int(data.get("clips") or 3)
        self.layout = data.get("layout") or "auto"
        self.meme = None if data.get("meme") == "none" else data.get("meme")
        self.no_meme = data.get("meme") == "none"
        self.meme_style = data.get("meme_style") or "insert"
        self.language = data.get("language")
        self.brain = data.get("brain") or "auto"
        self.model = data.get("model")
        self.section = data.get("section")
        self.new_only = False
        self.fast = bool(data.get("fast", True))
        self.min_len = int(data.get("min_len") or 15)
        self.max_len = int(data.get("max_len") or 55)
        self.focus = data.get("focus")
        self.cookies = data.get("cookies")
        self.repick = False
        self.keep_audio = False
        self.cam = data.get("cam")
        self.cam_box = None
        if self.cam:
            try:
                self.cam_box = tuple(float(v) for v in self.cam.split(","))
            except Exception:
                self.cam_box = None
        self.brain_resolved = brains.choose(self.brain)


def run_clip_job(job: Job):
    try:
        job.status = "running"
        job.progress = 5
        job.current_step = "Resolving video source..."
        broadcast_event("job_update", job.to_dict())

        opts = OptionsAdapter(job.payload)
        meme_val = False if opts.no_meme else (opts.meme or "auto")

        cfg = settings.load({
            "clips": opts.clips,
            "layout": opts.layout if opts.layout != "auto" else None,
            "min_len": opts.min_len,
            "max_len": opts.max_len,
            "language": opts.language if opts.language != "auto" else None,
            "meme": meme_val,
            "meme_style": opts.meme_style,
        })

        url = opts.url.strip()
        # Resolve Kick channel URL if provided
        resolved = media.resolve_channel_url(url, opts.cookies)
        if resolved != url:
            say(f"Resolved channel {url} -> {resolved}", "info")
            url = resolved

        job.current_step = "Processing video stream..."
        job.progress = 10
        broadcast_event("job_update", job.to_dict())

        # Run pipeline
        res = pipeline.process(url, opts, cfg)

        job.status = "completed"
        job.progress = 100
        job.current_step = f"Completed! Generated {len(res.get('clips', []))} viral clips."
        job.result = {
            "name": res["name"],
            "title": res["title"],
            "summary": res["summary"],
            "outdir": str(res["outdir"]),
            "clips": res["clips"],
        }
        broadcast_event("job_update", job.to_dict())
        broadcast_event("job_completed", job.to_dict())

    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.current_step = f"Failed: {str(exc)[:100]}"
        say(f"Job failed: {exc}", "bad")
        broadcast_event("job_update", job.to_dict())
        broadcast_event("job_failed", job.to_dict())


def run_custom_clip_job(job: Job):
    try:
        job.status = "running"
        job.progress = 10
        job.current_step = "Preparing custom clip..."
        broadcast_event("job_update", job.to_dict())

        p = job.payload
        url = p["url"].strip()
        start = float(p["start"])
        end = float(p["end"])
        title = p.get("title") or "Viral Highlight"
        clip_type = p.get("type") or "reaction"
        layout = p.get("layout") or "auto"
        meme_choice = p.get("meme") or "auto"
        meme_style = p.get("meme_style") or "insert"
        fast = bool(p.get("fast", True))

        args = media.ytdlp_args(url)
        work = pipeline.work_dir(url)
        meta = media.metadata(url, args, work)

        audio_file = media.audio(url, args, work)
        day = datetime.date.today().isoformat()
        outdir = (DATA / day / slug("custom", 30)
                  / f"{slug(meta['name'], 24)}__{slug(meta['title'], 40)}")
        outdir.mkdir(parents=True, exist_ok=True)

        cfg = settings.load({
            "layout": layout if layout != "auto" else None,
            "meme": False if meme_choice == "none" else (meme_choice if meme_choice != "auto" else True),
            "meme_style": meme_style,
        })

        ctx = {
            "url": url,
            "args": args,
            "audio": audio_file,
            "work": work,
            "outdir": outdir,
            "language": None,
            "fast": fast,
            "cam": None,
        }

        pick = {
            "start": start,
            "end": end,
            "type": clip_type,
            "title": title,
            "caption": f"{title} 🔥 Watch till the end!",
            "hashtags": [f"#{slug(meta['name'])}", "#Shorts", "#Viral"],
            "score": 92,
            "why": "Custom clipped moment",
        }
        if meme_choice and meme_choice not in ("none", "auto"):
            pick["meme"] = meme_choice

        job.current_step = "Producing 9:16 vertical clip..."
        job.progress = 40
        broadcast_event("job_update", job.to_dict())

        memory = {}
        clip_record = produce.make(1, pick, ctx, cfg, memory)

        pipeline.posting_sheet(outdir, {"name": meta["name"], "title": meta["title"], "url": url},
                               [clip_record], "Custom single clip cut", start, end)

        # Write clips.json
        write_json(outdir / "clips.json", {
            "source": {"title": meta["title"], "name": meta["name"], "url": url, "topic": "custom", "focus": None},
            "covered": [start, end],
            "clips": [clip_record]
        })

        job.status = "completed"
        job.progress = 100
        job.current_step = "Finished custom clip!"
        job.result = {
            "name": meta["name"],
            "title": meta["title"],
            "summary": f"Custom clip {human(end - start)} created successfully",
            "outdir": str(outdir),
            "clips": [clip_record],
        }
        broadcast_event("job_update", job.to_dict())
        broadcast_event("job_completed", job.to_dict())

    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.current_step = f"Failed: {str(exc)[:100]}"
        broadcast_event("job_update", job.to_dict())
        broadcast_event("job_failed", job.to_dict())


# ============================================================================
# API Routes
# ============================================================================

@app.get("/api/status")
def get_system_status():
    """Check health, installed engines, models and tools."""
    tools = {}
    for t in ("ffmpeg", "ffprobe", "yt-dlp"):
        tools[t] = bool(shutil.which(t))
    js_runtime = shutil.which("deno") or shutil.which("node") or shutil.which("bun")
    tools["javascript"] = bool(js_runtime)
    tools["face_model"] = (MODELS / "face_yunet.onnx").exists()

    cat = memes.load_catalog()
    v_count = sum(1 for m in cat if m.get("video_url"))

    cli_brains = [b for b in ("claude", "codex", "gemini", "opencode") if shutil.which(b)]

    free_gb = shutil.disk_usage(Path.home()).free / 1e9

    return {
        "status": "ready" if tools["ffmpeg"] and tools["yt-dlp"] else "degraded",
        "tools": tools,
        "js_runtime": js_runtime,
        "cli_brains": cli_brains,
        "default_brain": brains.choose("auto"),
        "has_gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        "memes": {
            "total_templates": len(cat),
            "templates_with_video": v_count,
        },
        "storage": {
            "output_dir": str(DATA),
            "free_gb": round(free_gb, 1),
        },
        "active_jobs": sum(1 for j in jobs.values() if j.status == "running"),
    }


@app.get("/api/settings")
def get_settings():
    s = settings.load()
    s["gemini_api_key_set"] = bool(os.environ.get("GEMINI_API_KEY"))
    return s


@app.post("/api/settings")
def update_settings(req: SettingsUpdate):
    curr = settings.load()
    updates = req.dict(exclude_unset=True)
    if "gemini_api_key" in updates and updates["gemini_api_key"]:
        os.environ["GEMINI_API_KEY"] = updates.pop("gemini_api_key").strip()
    curr.update(updates)
    settings_file = DATA / "settings.json"
    write_json(settings_file, curr)
    return {"message": "Settings saved", "settings": curr}


@app.get("/api/find")
def find_streams(
    topic: str = Query(..., description="Topic or game (e.g. GTA 6, Valorant)"),
    when: str = Query("today", pattern="^(hour|today|week|month)$"),
    count: int = Query(8, ge=1, le=25),
    search: Optional[str] = None,
    keywords: Optional[str] = None,
):
    """Find trending streams for a topic."""
    words = keywords_for(topic, keywords)
    cfg = settings.load({"search_when": when})
    try:
        results = discover.find(topic, words, cfg, count, search)
        return {"topic": topic, "count": len(results), "streams": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/memes")
def list_memes(
    query: Optional[str] = None,
    mood: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
):
    """Search and browse Indian meme templates."""
    results = memes.search_memes(query=query or "", mood=mood, limit=limit)
    return {"count": len(results), "memes": results}


@app.get("/api/memes/moods")
def list_meme_moods():
    """Return available meme mood filters."""
    cat = memes.load_catalog()
    moods = set()
    for m in cat:
        for md in m.get("moods", []):
            if md:
                moods.add(md.capitalize())
    return sorted(list(moods))


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a local video file to be clipped."""
    file_id = uuid.uuid4().hex[:8]
    ext = Path(file.filename).suffix or ".mp4"
    dest_name = f"{file_id}_{slug(Path(file.filename).stem)}{ext}"
    dest_path = UPLOADS_DIR / dest_name

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    info = probe(dest_path)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "path": str(dest_path),
        "size_mb": round(dest_path.stat().st_size / 1e6, 2),
        "duration": info["duration"],
        "duration_human": human(info["duration"]),
        "width": info["width"],
        "height": info["height"],
        "url": f"/api/uploads/{dest_name}",
    }


@app.get("/api/uploads/{filename}")
def serve_uploaded_file(filename: str):
    target = UPLOADS_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, media_type="video/mp4")


@app.post("/api/clip")
def start_clip_job(req: ClipRequest):
    """Start an automatic clipping job."""
    if not req.url:
        raise HTTPException(status_code=400, detail="URL or video file path required")

    job_id = uuid.uuid4().hex[:8]
    job = Job(job_id, req.dict())
    jobs[job_id] = job

    t = threading.Thread(target=run_clip_job, args=(job,), daemon=True)
    job.thread = t
    t.start()

    return {"job_id": job_id, "status": "queued"}


@app.post("/api/clip-custom")
def start_custom_clip(req: CustomClipRequest):
    """Start cutting a custom single clip."""
    if req.end <= req.start:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    job_id = uuid.uuid4().hex[:8]
    job = Job(job_id, req.dict())
    jobs[job_id] = job

    t = threading.Thread(target=run_custom_clip_job, args=(job,), daemon=True)
    job.thread = t
    t.start()

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs")
def list_jobs():
    """List all recent jobs."""
    return [j.to_dict() for j in sorted(jobs.values(), key=lambda x: x.created_at, reverse=True)]


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    """Get single job details and logs."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    res = job.to_dict()
    res["logs"] = job.logs[-200:]
    return res


@app.get("/api/library")
def get_library():
    """Scan and return all generated clips and projects."""
    if not DATA.exists():
        return []

    projects = []
    for clips_file in sorted(DATA.glob("*/*/*/clips.json"), reverse=True):
        folder = clips_file.parent
        data = None
        try:
            data = json.loads(clips_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        source = data.get("source", {})
        clips_data = data.get("clips", [])
        rel_parts = folder.relative_to(DATA).parts  # (date, topic, project_folder)
        if len(rel_parts) < 3:
            continue

        date_str, topic_str, proj_str = rel_parts[0], rel_parts[1], rel_parts[2]

        clip_items = []
        for c in clips_data:
            c_file = c.get("file")
            if not c_file:
                continue
            mp4_path = folder / c_file
            if not mp4_path.exists():
                continue

            thumb_name = Path(c_file).stem + ".jpg"
            thumb_path = folder / "checks" / thumb_name
            has_thumb = thumb_path.exists()

            clip_items.append({
                "file": c_file,
                "title": c.get("title") or "Clip",
                "type": c.get("type") or "moment",
                "seconds": c.get("seconds") or 0,
                "score": c.get("score") or 80,
                "why": c.get("why") or "",
                "look": c.get("look") or "stack",
                "meme": c.get("meme"),
                "caption": c.get("caption") or "",
                "hashtags": c.get("hashtags") or [],
                "video_url": f"/api/media/{date_str}/{topic_str}/{proj_str}/{c_file}",
                "thumb_url": f"/api/thumb/{date_str}/{topic_str}/{proj_str}/{thumb_name}" if has_thumb else None,
                "download_url": f"/api/download/{date_str}/{topic_str}/{proj_str}/{c_file}",
                "size_mb": round(mp4_path.stat().st_size / 1e6, 2),
            })

        posting_md = ""
        post_path = folder / "POSTING.md"
        if post_path.exists():
            try:
                posting_md = post_path.read_text(encoding="utf-8")
            except Exception:
                pass

        if clip_items:
            projects.append({
                "date": date_str,
                "topic": topic_str,
                "folder_name": proj_str,
                "creator": source.get("name") or "Creator",
                "title": source.get("title") or proj_str,
                "url": source.get("url") or "",
                "covered": data.get("covered", []),
                "posting_guide": posting_md,
                "clips_count": len(clip_items),
                "clips": clip_items,
            })

    return projects


@app.get("/api/media/{date}/{topic}/{folder}/{filename}")
def stream_clip_video(date: str, topic: str, folder: str, filename: str):
    """Stream generated MP4 video with Range headers for video player."""
    target = DATA / date / topic / folder / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(target, media_type="video/mp4")


@app.get("/api/thumb/{date}/{topic}/{folder}/{filename}")
def stream_clip_thumbnail(date: str, topic: str, folder: str, filename: str):
    """Serve 3-frame thumbnail check image."""
    target = DATA / date / topic / folder / "checks" / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(target, media_type="image/jpeg")


@app.get("/api/download/{date}/{topic}/{folder}/{filename}")
def download_clip_video(date: str, topic: str, folder: str, filename: str):
    """Download MP4 attachment."""
    target = DATA / date / topic / folder / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(target, media_type="video/mp4", filename=filename)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    with connections_lock:
        active_connections.append(websocket)
    try:
        while True:
            # Keep-alive ping/pong
            await websocket.receive_text()
    except WebSocketDisconnect:
        with connections_lock:
            if websocket in active_connections:
                active_connections.remove(websocket)


# Mount static frontend
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"\n==================================================")
    print(f"🎬 StreamClips AI Studio Web Server")
    print(f"👉 Local Web UI: http://localhost:{port}")
    print(f"📁 Output folder: {DATA}")
    print(f"==================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
