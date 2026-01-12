from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp
import requests
import os
import random
import shutil
import re
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------
# PIPED instances
# -------------------------
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.in.projectsegfau.lt",
    "https://pipedapi.brighteon.wtf"
]

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
# FASTAPI setup
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
    pattern = r"(?:v=|youtu\.be/)([A-Za-z0-9_-]+)"
    m = re.search(pattern, url)
    if not m:
        raise ValueError("Invalid YouTube URL")
    return m.group(1)


# -------------------------
# YouTube Search
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
        if "youtube.com" in query or "youtu.be" in query:
            info = ydl.extract_info(query, download=False)
            entries = [info]
        else:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = info.get("entries", [info])

    songs = []
    for e in entries[:limit]:
        vid = e.get("id")
        thumb = e.get("thumbnail") or (f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else "")
        songs.append({
            "title": e.get("title") or "Unknown",
            "artist": e.get("uploader") or "Unknown Artist",
            "thumbnail": thumb,
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        })
    return songs


# -----------------------------------------------------
# FAST RESOLVE CHAIN — SUPER OPTIMIZED (FASTEST VERSION)
# -----------------------------------------------------
def resolve_audio_url(video_id: str):
    """
    Multi-layer resolver:
    1. Piped API (fast)
    2. piped.video fallback (very fast)
    3. youtubei unofficial API (fast)
    4. yt-dlp fallback (slow)
    """

    # 1) Piped instances
    for instance in PIPED_INSTANCES:
        try:
            api = f"{instance}/streams/{video_id}"
            r = requests.get(api, timeout=3)
            if r.status_code == 200:
                data = r.json()
                streams = data.get("audioStreams") or []
                if streams:
                    filtered = [
                        s for s in streams
                        if s.get("bitrate") and s.get("bitrate") <= 128000
                    ]

                    if not filtered:
                        filtered = streams  # fallback if low bitrate not found

                    best = sorted(filtered, key=lambda x: x.get("bitrate", 0))[-1]
                    if best.get("url"):
                        return best["url"]
        except:
            continue

    # 2) piped.video universal fallback
    try:
        api = f"https://piped.video/streams/{video_id}"
        r = requests.get(api, timeout=3)
        if r.status_code == 200:
            data = r.json()
            streams = data.get("audioStreams") or []
            if streams:
                filtered = [
                    s for s in streams
                    if s.get("bitrate") and s.get("bitrate") <= 128000
                ]

                if not filtered:
                    filtered = streams  # fallback if low bitrate not found

                best = sorted(filtered, key=lambda x: x.get("bitrate", 0))[-1]
                if best.get("url"):
                    return best["url"]
    except:
        pass

    # 3) youtubei unofficial API
    try:
        api = f"https://yt-api.yashvardhan.info/api/v1/video?id={video_id}"
        r = requests.get(api, timeout=3)
        if r.status_code == 200:
            info = r.json()
            formats = info.get("adaptiveFormats") or []
            audio_formats = [f for f in formats if "audio" in f.get("mimeType", "")]
            if audio_formats:
                filtered = [
                    f for f in audio_formats
                    if f.get("bitrate") and f.get("bitrate") <= 128000
                ]

                if not filtered:
                    filtered = audio_formats

                best = sorted(filtered, key=lambda x: x.get("bitrate", 0))[-1]
                if best.get("url"):
                    return best["url"]
    except:
        pass

    # 4) Final fallback — yt-dlp
    try:
        opts = {
            "quiet": True,
            "format": "bestaudio/best",
        }
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            opts["cookiefile"] = COOKIES_FILE

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if "url" in info:
                return info["url"]

            fmts = info.get("formats") or []
            audio_fmts = [f for f in fmts if f.get("url")]
            if audio_fmts:
                best = sorted(audio_fmts, key=lambda x: x.get("abr") or x.get("tbr") or 0)[-1]
                return best["url"]
    except:
        pass

    raise RuntimeError("No audio URL found after all resolvers")


# -----------------------------------------------------
# SEARCH / POPULAR / RECOMMENDATIONS
# -----------------------------------------------------
@app.post("/search")
def search_song(req: SearchRequest):
    try:
        q = req.query.strip()
        is_youtube = "youtube.com" in q or "youtu.be" in q
        raw = youtube_search(q, limit=15)

        if not is_youtube:
            filtered = [
                s for s in raw
                if any(k in (s["title"] + " " + s["artist"]).lower()
                       for k in ["music","song","audio","track"])
            ]
        else:
            filtered = raw

        return {"status": "success", "results": filtered[:15]}

    except Exception as e:
        raise HTTPException(400, f"Search failed: {e}")


@app.get("/popular")
def get_popular():
    try:
        queries = [
            "Bollywood top hits 2025", "Indian music chart", "Bollywood songs playlist",
            "Top Hindi songs 2025", "Popular Indian tracks"
        ]
        q = random.choice(queries)
        raw = youtube_search(q, limit=15)
        filtered = [
            s for s in raw
            if any(k in (s["title"] + " " + s["artist"]).lower()
                   for k in ["music","song","audio","track","bollywood","hindi"])
        ]
        return {"status": "success", "results": filtered[:15]}
    except Exception as e:
        raise HTTPException(400, f"Popular failed: {e}")


@app.get("/recommendations")
def get_recommendations():
    try:
        base = [
            "Bollywood romantic songs", "Relaxing Hindi music", "Indian pop hits",
            "Bollywood trending songs", "Acoustic Hindi covers", "Top Hindi tracks"
        ]
        q = random.choice(base)
        raw = youtube_search(q, limit=12)
        filtered = [
            s for s in raw
            if any(k in (s["title"] + " " + s["artist"]).lower()
                   for k in ["music","song","audio","track","bollywood","hindi"])
        ]
        return {"status": "success", "query": q, "results": filtered[:12]}
    except Exception as e:
        raise HTTPException(400, f"Recommendations failed: {e}")


# -----------------------------------------------------
# NEW: /resolve — only returns DIRECT AUDIO STREAM URL
# -----------------------------------------------------
@app.post("/resolve")
def resolve_audio(req: ResolveRequest):
    try:
        vid = extract_video_id(req.url.strip())
        audio_url = resolve_audio_url(vid)
        return {"status": "success", "audio_url": audio_url}
    except Exception as e:
        raise HTTPException(400, f"Resolve failed: {e}")


# -----------------------------------------------------
# KEEP ALIVE (Render)
# -----------------------------------------------------
import threading, time
PING_URL = os.getenv("PING_URL", "http://localhost:8000")

def keep_awake():
    while True:
        try:
            requests.get(f"{PING_URL}/resolve?url=https://youtu.be/dQw4w9WgXcQ", timeout=5)
        except:
            pass
        time.sleep(14 * 60)

threading.Thread(target=keep_awake, daemon=True).start()
