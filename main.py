from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp
import requests
import os
import random
import shutil
import re
import threading
import time
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------
# CONFIG
# -------------------------
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.in.projectsegfau.lt",
    "https://pipedapi.brighteon.wtf",
]

ALLOWED_ITAGS = {249, 250}  # low-bitrate audio only (mobile safe)

# -------------------------
# COOKIEFILE SUPPORT
# -------------------------
COOKIES_FILE = os.getenv("COOKIES_FILE")
if COOKIES_FILE:
    try:
        local = os.path.join(BASE_DIR, "cookies.txt")
        if not os.path.exists(local):
            shutil.copy(COOKIES_FILE, local)
        COOKIES_FILE = local
    except:
        COOKIES_FILE = None
else:
    COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

# -------------------------
# FASTAPI SETUP
# -------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -------------------------
# MODELS
# -------------------------
class SearchRequest(BaseModel):
    query: str

class ResolveRequest(BaseModel):
    url: str

# -------------------------
# HELPERS
# -------------------------
def extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError("Invalid YouTube URL")
    return m.group(1)

def is_hls(url: str) -> bool:
    return (
        ".m3u8" in url
        or "hls_playlist" in url
        or "manifest.googlevideo.com" in url
    )

def is_valid_audio(stream: dict) -> bool:
    return (
        stream.get("url")
        and not is_hls(stream["url"])
        and stream.get("itag") in ALLOWED_ITAGS
    )

# -------------------------
# YOUTUBE SEARCH
# -------------------------
def youtube_search(query: str, limit: int = 10):
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
        "forcejson": True,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            query if "youtube.com" in query else f"ytsearch{limit}:{query}",
            download=False,
        )
        entries = info.get("entries", [info])

    songs = []
    for e in entries[:limit]:
        vid = e.get("id")
        songs.append({
            "title": e.get("title", "Unknown"),
            "artist": e.get("uploader", "Unknown Artist"),
            "thumbnail": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return songs

# -------------------------
# RESOLVE AUDIO (SAFE)
# -------------------------
def resolve_audio_url(video_id: str):
    # 1) PIPED
    for instance in PIPED_INSTANCES:
        try:
            r = requests.get(f"{instance}/streams/{video_id}", timeout=3)
            if r.status_code == 200:
                streams = r.json().get("audioStreams", [])
                valid = [s for s in streams if is_valid_audio(s)]
                if valid:
                    return valid[-1]["url"]
        except:
            pass

    # 2) YOUTUBEI
    try:
        r = requests.get(
            f"https://yt-api.yashvardhan.info/api/v1/video?id={video_id}",
            timeout=3,
        )
        if r.status_code == 200:
            formats = r.json().get("adaptiveFormats", [])
            valid = [
                f for f in formats
                if f.get("itag") in ALLOWED_ITAGS
                and f.get("url")
                and not is_hls(f["url"])
                and f.get("mimeType", "").startswith("audio/")
            ]
            if valid:
                return valid[-1]["url"]
    except:
        pass

    raise RuntimeError("No safe low-bitrate audio found")

# -------------------------
# API ROUTES
# -------------------------
@app.get("/ping")
def ping():
    return {"status": "alive"}

@app.post("/search")
def search_song(req: SearchRequest):
    try:
        return {"status": "success", "results": youtube_search(req.query, 15)}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/popular")
def get_popular():
    return {
        "status": "success",
        "results": youtube_search(
            random.choice([
                "Bollywood top hits",
                "Popular Hindi songs",
                "Trending Indian music",
            ]),
            15,
        ),
    }

@app.get("/recommendations")
def get_recommendations():
    q = random.choice([
        "Relaxing Hindi music",
        "Bollywood romantic songs",
        "Acoustic Hindi covers",
    ])
    return {
        "status": "success",
        "query": q,
        "results": youtube_search(q, 12),
    }

@app.post("/resolve")
def resolve_audio(req: ResolveRequest):
    try:
        vid = extract_video_id(req.url)
        return {
            "status": "success",
            "audio_url": resolve_audio_url(vid),
        }
    except Exception as e:
        raise HTTPException(400, str(e))

# -------------------------
# KEEP ALIVE (LIGHTWEIGHT)
# -------------------------
PING_URL = os.getenv("PING_URL", "http://localhost:8000")

def keep_awake():
    while True:
        try:
            requests.get(f"{PING_URL}/ping", timeout=5)
        except:
            pass
        time.sleep(14 * 60)

threading.Thread(target=keep_awake, daemon=True).start()
