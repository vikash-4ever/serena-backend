from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
import requests
import os
import random
import shutil
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware  

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------- COOKIES HANDLING --------------------
COOKIES_FILE = os.getenv("COOKIES_FILE")

if COOKIES_FILE:
    # On Render, /etc/secrets/cookies.txt is read-only → copy it
    writable_path = os.path.join(BASE_DIR, "cookies.txt")
    try:
        if not os.path.exists(writable_path):
            shutil.copy(COOKIES_FILE, writable_path)
        COOKIES_FILE = writable_path
    except Exception as e:
        print(f"Warning: failed to copy cookies file: {e}")
        COOKIES_FILE = None
else:
    # Local dev fallback
    COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

# ----------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure downloads folder exists
os.makedirs("downloads", exist_ok=True)


class SearchRequest(BaseModel):
    query: str

class DownloadRequest(BaseModel):
    url: str

# ------------------------- HELPERS -------------------------

def get_spotify_token():
    auth_response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    if auth_response.status_code != 200:
        raise Exception("Failed to get Spotify token")
    return auth_response.json().get("access_token")

def get_spotify_metadata(track_url: str):
    token = get_spotify_token()
    track_id = track_url.split("/")[-1].split("?")[0]
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers=headers)
    if response.status_code != 200:
        raise Exception("Failed to fetch Spotify metadata")
    data = response.json()
    title = data["name"]
    artist = data["artists"][0]["name"]
    duration_sec = data["duration_ms"] // 1000
    return {
        "query": f"{title} {artist}",
        "title": title,
        "artist": artist,
        "duration": duration_sec
    }

def youtube_search(query: str, limit: int = 10):
    """Search or fetch YouTube videos using cookies"""
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
        "forcejson": True,
        "cookiefile": COOKIES_FILE,   # <-- Added cookies support
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        if "youtube.com" in query or "youtu.be" in query:
            results = ydl.extract_info(query, download=False)
            entries = [results]
        else:
            results = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = results.get("entries", [results])

    songs = []
    for entry in entries[:limit]:
        video_id = entry.get("id")
        thumbnail = entry.get("thumbnail") or (f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
        songs.append({
            "title": entry.get("title") or "Unknown",
            "artist": entry.get("uploader") or "Unknown Artist",
            "thumbnail": thumbnail,
            "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        })
    return songs

# ------------------------- ENDPOINTS -------------------------

@app.post("/search")
def search_song(request: SearchRequest):
    """Search songs on YouTube but filter to actual music videos"""
    try:
        query = request.query.strip()
        if "spotify.com" in query:
            meta = get_spotify_metadata(query)
            raw_results = youtube_search(meta["query"], limit=15)
        else:
            raw_results = youtube_search(query, limit=15)

        # Filter results to likely music videos
        filtered_results = [
            song for song in raw_results
            if any(k in (song["title"] + " " + song["artist"]).lower() for k in ["music", "song", "audio", "track"])
        ]
        return {"status": "success", "results": filtered_results[:15]}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search failed: {str(e)}")


@app.get("/popular")
def get_popular():
    """Fetch trending / popular songs, biased toward Bollywood/Indian music"""
    try:
        trending_queries = [
            "Bollywood top hits 2025", "Indian music chart", "Bollywood songs playlist",
            "Top Hindi songs 2025", "Popular Indian tracks"
        ]
        query = random.choice(trending_queries)
        raw_results = youtube_search(query, limit=15)

        # Filter results to likely music videos
        filtered_results = [
            song for song in raw_results
            if any(k in (song["title"] + " " + song["artist"]).lower() for k in ["music", "song", "audio", "track", "bollywood", "hindi"])
        ]
        return {"status": "success", "results": filtered_results[:15]}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Popular fetch failed: {str(e)}")


@app.get("/recommendations")
def get_recommendations():
    """Provide music recommendations, biased toward relaxing / Bollywood / Indian songs"""
    try:
        base_queries = [
            "Bollywood romantic songs", "Relaxing Hindi music", "Indian pop hits",
            "Bollywood trending songs", "Acoustic Hindi covers", "Top Hindi tracks"
        ]
        query = random.choice(base_queries)
        raw_results = youtube_search(query, limit=12)

        # Filter results to likely music videos
        filtered_results = [
            song for song in raw_results
            if any(k in (song["title"] + " " + song["artist"]).lower() for k in ["music", "song", "audio", "track", "bollywood", "hindi"])
        ]
        return {"status": "success", "query": query, "results": filtered_results[:12]}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Recommendations failed: {str(e)}")


@app.get("/download")
async def download_audio(url: str):
    try:
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "quiet": True,
            "skip_download": True,
            "cookiefile": COOKIES_FILE,   # <-- Added cookies support
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])

            # pick m4a if possible
            audio_url = None
            ext = "m4a"
            for f in formats:
                if f.get("ext") == "m4a":
                    audio_url = f["url"]
                    break
            if not audio_url and formats:
                audio_url = formats[0]["url"]
                ext = formats[0]["ext"]

            return {
                "url": audio_url,
                "ext": ext,
                "title": info.get("title"),
                "artist": info.get("uploader"),
            }
    except Exception as e:
        return {"error": str(e)}

@app.get("/stream")
def stream_audio(link: str):
    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
            "cookiefile": COOKIES_FILE,   # <-- Added cookies support
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            audio_url = info["url"]

        return {
            "url": audio_url,
            "title": info.get("title", ""),
            "ext": info.get("ext", ""),
        }
    except Exception as e:
        return {"error": str(e)}
