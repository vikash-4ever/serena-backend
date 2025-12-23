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

PREFERRED_ITAGS = [249, 250]   # low data
FALLBACK_ITAGS = [251]         # allow ONLY if direct audio (no HLS)

# -------------------------
# COOKIE SUPPORT
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
    return ".m3u8" in url or "manifest.googlevideo.com" in url

def is_direct_audio(url: str) -> bool:
    return "googlevideo.com/videoplayback" in url and not is_hls(url)

def is_english(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z]", text))

# -------------------------
# SEARCH (ENGLISH BIAS)
# -------------------------
def youtube_search(query: str, limit: int = 10):
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
        "forcejson": True,
        "geo_bypass": True,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = info.get("entries", [])

    songs = []
    for e in entries:
        title = e.get("title", "")
        artist = e.get("uploader", "")
        vid = e.get("id")

        if not vid or not is_english(title):
            continue

        songs.append({
            "title": title,
            "artist": artist or "Unknown Artist",
            "thumbnail": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })

        if len(songs) >= limit:
            break

    return songs

# -------------------------
# RESOLVE AUDIO (SAFE + FALLBACK)
# -------------------------
def resolve_audio_url(video_id: str):
    # 1️⃣ PIPED
    for instance in PIPED_INSTANCES:
        try:
            r = requests.get(f"{instance}/streams/{video_id}", timeout=3)
            if r.status_code == 200:
                streams = r.json().get("audioStreams", [])

                # preferred
                for s in streams:
                    if s.get("itag") in PREFERRED_ITAGS and is_direct_audio(s.get("url", "")):
                        return s["url"]

                # safe fallback
                for s in streams:
                    if s.get("itag") in FALLBACK_ITAGS and is_direct_audio(s.get("url", "")):
                        return s["url"]
        except:
            pass

    # 2️⃣ youtubei
    try:
        r = requests.get(
            f"https://yt-api.yashvardhan.info/api/v1/video?id={video_id}",
            timeout=3
        )
        if r.status_code == 200:
            formats = r.json().get("adaptiveFormats", [])

            for f in formats:
                if (
                    f.get("itag") in PREFERRED_ITAGS
                    and f.get("mimeType", "").startswith("audio/")
                    and is_direct_audio(f.get("url", ""))
                ):
                    return f["url"]

            for f in formats:
                if (
                    f.get("itag") in FALLBACK_ITAGS
                    and f.get("mimeType", "").startswith("audio/")
                    and is_direct_audio(f.get("url", ""))
                ):
                    return f["url"]
    except:
        pass

    raise RuntimeError("No safe audio stream available")

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
                "Top Bollywood English titles",
                "Popular Hindi songs English",
                "Trending Indian music",
            ]),
            15,
        ),
    }

@app.get("/recommendations")
def get_recommendations():
    q = random.choice([
        "Relaxing Hindi music English",
        "Bollywood romantic songs English",
        "Acoustic Hindi covers English",
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
        return {"status": "success", "audio_url": resolve_audio_url(vid)}
    except Exception as e:
        raise HTTPException(400, str(e))

# -------------------------
# KEEP ALIVE (LIGHT)
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
