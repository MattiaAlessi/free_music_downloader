import os
import re
import json
import time
import threading
import subprocess
import sys
import urllib.request
import urllib.parse
import requests
from flask import Flask, request, jsonify, send_from_directory
from bs4 import BeautifulSoup

app = Flask(__name__, static_folder="static")

# ============================================
# STATO GLOBALE DEI DOWNLOAD
# ============================================
download_state = {
    "active": False,
    "stop": False,
    "total": 0,
    "current": 0,
    "success": 0,
    "errors": 0,
    "current_track": "",
    "log": [],
    "status": "idle",   # idle | downloading | pausing | done | stopped | error
    "download_path": os.path.join(os.path.expanduser("~"), "Desktop", "Musica Scaricata"),
}

def push_log(msg, level="info"):
    ts = time.strftime("%H:%M:%S")
    download_state["log"].append({"ts": ts, "msg": msg, "level": level})
    if len(download_state["log"]) > 300:
        download_state["log"] = download_state["log"][-300:]

# ============================================
# ALBUM SEARCHER
# ============================================
class AlbumSearcher:
    @staticmethod
    def search_album_tracks(album_name, artist_name=""):
        tracks = []
        try:
            q = f"{album_name} {artist_name} tracklist" if artist_name else f"{album_name} tracklist"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            url = f"https://www.google.com/search?q={urllib.parse.quote(q)}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "url?q=" in href and "webcache" not in href:
                        m = re.search(r"url\?q=([^&]+)", href)
                        if m:
                            u = urllib.parse.unquote(m.group(1))
                            if any(s in u for s in ["genius.com", "wikipedia.org", "allmusic.com", "discogs.com"]):
                                links.append(u)
                for link in links[:3]:
                    t = AlbumSearcher.parse_page(link)
                    if t and len(t) >= 4:
                        tracks = t
                        break
            if not tracks and artist_name:
                genius_url = f"https://genius.com/albums/{artist_name.replace(' ','-')}/{album_name.replace(' ','-')}"
                tracks = AlbumSearcher.parse_genius(genius_url)
            return tracks[:15]
        except Exception as e:
            return []

    @staticmethod
    def parse_page(url):
        tracks = []
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                elems = soup.find_all(["li","tr","div"], class_=re.compile(r"track|song|list-item|chartlist-row", re.I))
                for e in elems[:20]:
                    text = e.get_text().strip()
                    m = re.search(r"(\d+)[\s.)-]+([A-Za-z0-9\s\'\-&]+)", text)
                    if m:
                        name = m.group(2).strip()
                        if len(name) > 3:
                            tracks.append(f"{int(m.group(1)):02d}. {name}")
                if not tracks:
                    for line in soup.get_text().split("\n")[:50]:
                        m = re.search(r"(\d+)[\s.)-]+([A-Za-z0-9\s\'\-&]{3,30})", line)
                        if m:
                            name = m.group(2).strip()
                            if len(name) > 3:
                                tracks.append(f"{int(m.group(1)):02d}. {name}")
            return list(dict.fromkeys(tracks))
        except:
            return []

    @staticmethod
    def parse_genius(url):
        tracks = []
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                rows = soup.find_all("div", class_=re.compile(r"chart_row|track_listing|song_row", re.I))
                for row in rows[:20]:
                    el = row.find(["a","span"], class_=re.compile(r"title|name|song", re.I))
                    if el:
                        name = el.get_text().strip()
                        if len(name) > 3:
                            tracks.append(name)
            return tracks
        except:
            return []

# ============================================
# NAME FORMATTER
# ============================================
class NameFormatter:
    @staticmethod
    def format_filename(song, artist):
        minor = ['a','an','the','and','or','but','for','on','at','to','by','with','in','of']
        words = song.split()
        title = " ".join(
            w if w.isupper() else (w.capitalize() if i == 0 or w.lower() not in minor else w.lower())
            for i, w in enumerate(words)
        )
        art = " ".join(w if w.isupper() else w.capitalize() for w in (artist or "Unknown").split())
        name = f"{title} - {art}" if art else title
        return re.sub(r'[\\/*?:"<>|]', "", name)

# ============================================
# YT-DLP DOWNLOADER
# ============================================
def run_ytdlp(search_query, output_path):
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    base = output_path[:-4] if output_path.endswith(".mp3") else output_path
    cmd = [
        "yt-dlp", "--no-playlist",
        "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-warnings",
        "-o", f"{base}.%(ext)s",
        f"ytsearch1:{search_query}"
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.strip()
            if line and any(k in line for k in ["[download]", "[ExtractAudio]", "Destination", "ERROR"]):
                push_log(f"  {line[:90]}")
        proc.wait()
        if os.path.exists(output_path):
            return True
        folder = os.path.dirname(output_path) or "."
        now = time.time()
        for f in os.listdir(folder):
            if f.endswith(".mp3") and now - os.path.getmtime(os.path.join(folder, f)) < 90:
                return True
        return False
    except FileNotFoundError:
        push_log("❌ yt-dlp non trovato. Installa con: pip install yt-dlp", "error")
        return False
    except Exception as e:
        push_log(f"❌ Errore: {e}", "error")
        return False

def download_playlist_url(playlist_url, output_folder):
    """Download diretto da URL YouTube playlist/canale/video"""
    os.makedirs(output_folder, exist_ok=True)
    output_template = os.path.join(output_folder, "%(playlist_index)s. %(title)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-warnings", "--yes-playlist",
        "-o", output_template,
        playlist_url
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        downloaded = 0
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            push_log(f"  {line[:100]}")
            if "[ExtractAudio]" in line and "Destination" in line:
                downloaded += 1
                download_state["success"] = downloaded
                download_state["current_track"] = line.split("Destination:")[-1].strip()[:50]
        proc.wait()
        return proc.returncode == 0
    except Exception as e:
        push_log(f"❌ Errore playlist: {e}", "error")
        return False

# ============================================
# BACKGROUND DOWNLOAD THREAD
# ============================================
def do_download(mode, data):
    dl = download_state
    dl["active"] = True
    dl["stop"] = False
    dl["log"] = []
    dl["success"] = 0
    dl["errors"] = 0
    dl["current"] = 0
    dl["status"] = "downloading"
    folder = dl["download_path"]
    os.makedirs(folder, exist_ok=True)

    try:
        if mode == "single":
            query = data["query"]
            dl["total"] = 1
            dl["current"] = 1
            dl["current_track"] = query
            push_log(f"🔍 Cerco: {query}")
            fname = NameFormatter.format_filename(query, "")
            out = os.path.join(folder, f"{fname}.mp3")
            ok = run_ytdlp(query, out)
            dl["success"] = 1 if ok else 0
            dl["errors"] = 0 if ok else 1
            push_log("✅ Download completato!" if ok else "❌ Download fallito", "success" if ok else "error")

        elif mode == "playlist_url":
            url = data["url"]
            push_log(f"🔗 Download playlist: {url}")
            dl["total"] = 0
            dl["current"] = 0
            ok = download_playlist_url(url, folder)
            push_log("✅ Playlist completata!" if ok else "❌ Errore playlist", "success" if ok else "error")

        elif mode == "album":
            tracks = data["tracks"]
            artist = data.get("artist", "")
            dl["total"] = len(tracks)
            push_log(f"💿 Inizio download album: {len(tracks)} tracce → {folder}")
            start = time.time()
            pause_sec = int(data.get("pause", 10))

            for i, track in enumerate(tracks, 1):
                if dl["stop"]:
                    break
                dl["current"] = i
                dl["current_track"] = track
                push_log(f"[{i}/{dl['total']}] {track[:50]}...")
                dl["status"] = "downloading"
                fname = NameFormatter.format_filename(track, artist)
                out = os.path.join(folder, f"{fname}.mp3")
                ok = run_ytdlp(f"{track} {artist}", out)
                if ok:
                    dl["success"] += 1
                    push_log(f"  ✅ Scaricata", "success")
                else:
                    dl["errors"] += 1
                    push_log(f"  ❌ Errore", "error")

                if i < dl["total"] and not dl["stop"]:
                    dl["status"] = "pausing"
                    push_log(f"  ⏸ Pausa {pause_sec}s...")
                    for s in range(pause_sec):
                        if dl["stop"]:
                            break
                        time.sleep(1)

            elapsed = int(time.time() - start)
            push_log(f"✨ Completato in {elapsed}s — {dl['success']}/{dl['total']} tracce", "success")

        dl["status"] = "done"

    except Exception as e:
        push_log(f"❌ ERRORE: {e}", "error")
        dl["status"] = "error"
    finally:
        dl["active"] = False

# ============================================
# API ROUTES
# ============================================
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/status")
def api_status():
    return jsonify(download_state)

@app.route("/api/search_album", methods=["POST"])
def api_search_album():
    body = request.json or {}
    album = body.get("album", "").strip()
    artist = body.get("artist", "").strip()
    if not album:
        return jsonify({"error": "Album name required"}), 400
    tracks = AlbumSearcher.search_album_tracks(album, artist)
    return jsonify({"tracks": tracks, "count": len(tracks)})

@app.route("/api/download", methods=["POST"])
def api_download():
    if download_state["active"]:
        return jsonify({"error": "Download già in corso"}), 409
    body = request.json or {}
    mode = body.get("mode")   # single | album | playlist_url
    folder = body.get("folder", "").strip()
    if folder:
        download_state["download_path"] = folder
    t = threading.Thread(target=do_download, args=(mode, body), daemon=True)
    t.start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    download_state["stop"] = True
    download_state["status"] = "stopped"
    return jsonify({"ok": True})

@app.route("/api/set_folder", methods=["POST"])
def api_set_folder():
    body = request.json or {}
    folder = body.get("folder", "").strip()
    if folder:
        os.makedirs(folder, exist_ok=True)
        download_state["download_path"] = folder
    return jsonify({"folder": download_state["download_path"]})

@app.route("/api/check_deps")
def api_check_deps():
    deps = {}
    for tool in ["yt-dlp", "ffmpeg"]:
        try:
            subprocess.run([tool, "--version"], capture_output=True, check=True)
            deps[tool] = True
        except:
            deps[tool] = False
    return jsonify(deps)

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    print("\n🎵 Music Downloader avviato!")
    print("➡  Apri il browser su: http://localhost:5000\n")
    app.run(debug=False, port=5000)
