import os
import re
import time
import threading
import subprocess
import sys
import urllib.parse
import requests
from flask import Flask, request, jsonify, send_from_directory
from bs4 import BeautifulSoup

# Load .env if present (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    "spotdl_available": False,
}

# ============================================
# DOWNLOAD QUEUE
# ============================================
# Each item: {"mode": str, "data": dict, "label": str, "id": int}
download_queue = []
queue_lock = threading.Lock()
_queue_id_counter = 0

def queue_next_id():
    global _queue_id_counter
    _queue_id_counter += 1
    return _queue_id_counter

def queue_as_list():
    with queue_lock:
        return list(download_queue)

def queue_add(mode, data, label):
    with queue_lock:
        item = {"id": queue_next_id(), "mode": mode, "data": data, "label": label}
        download_queue.append(item)
    return item

def queue_pop_first():
    with queue_lock:
        if download_queue:
            return download_queue.pop(0)
    return None

def queue_clear():
    with queue_lock:
        download_queue.clear()

def queue_remove(item_id):
    with queue_lock:
        idx = next((i for i, x in enumerate(download_queue) if x["id"] == item_id), None)
        if idx is not None:
            download_queue.pop(idx)
            return True
    return False

def queue_label(mode, data):
    """Human-readable label for a queue item."""
    if mode == "single":
        return data.get("query", "Canzone")[:50]
    elif mode == "album":
        tracks = data.get("tracks", [])
        artist = data.get("artist", "")
        return f"Album · {artist} ({len(tracks)} tracce)" if artist else f"Album ({len(tracks)} tracce)"
    elif mode == "playlist_url":
        url = data.get("url", "")
        return f"Playlist · {url[:40]}..."
    elif mode == "spotify":
        url = data.get("url", "")
        return f"Spotify · {url[:40]}..."
    return mode

# Worker that drains the queue one item at a time
def queue_worker():
    while True:
        if download_state["active"]:
            time.sleep(1)
            continue
        item = queue_pop_first()
        if item is None:
            time.sleep(1)
            continue
        push_log(f"▶ Inizio: {item['label']}", "info")
        do_download(item["mode"], item["data"])

_queue_worker_thread = threading.Thread(target=queue_worker, daemon=True)
_queue_worker_thread.start()

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
        except:
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
# NATIVE FOLDER DIALOG
# ============================================
def open_folder_dialog(initial_dir=None):
    """Open a native OS folder picker. Returns selected path string or None."""
    initial = initial_dir or os.path.expanduser("~")
    try:
        if sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                f"$f.SelectedPath = '{initial}';"
                "$f.ShowNewFolderButton = $true;"
                "if($f.ShowDialog() -eq 'OK'){Write-Output $f.SelectedPath}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=60
            )
            path = result.stdout.strip()
            return path if path else None

        elif sys.platform == "darwin":
            script = (
                f'tell app "Finder" to return POSIX path of '
                f'(choose folder with prompt "Scegli cartella" '
                f'default location POSIX file "{initial}")'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=60
            )
            path = result.stdout.strip()
            return path if path else None

        else:
            # Linux: try zenity then kdialog
            for args in [
                ["zenity", "--file-selection", "--directory", f"--filename={initial}/"],
                ["kdialog", "--getexistingdirectory", initial],
            ]:
                try:
                    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
                    path = result.stdout.strip()
                    if path:
                        return path
                except FileNotFoundError:
                    continue
            return None

    except Exception as e:
        print(f"Folder dialog error: {e}")
        return None

# ============================================
# SPOTDL — Spotify support
# ============================================
def check_spotdl():
    try:
        subprocess.run(["spotdl", "--version"], capture_output=True, timeout=10)
        download_state["spotdl_available"] = True
        return True
    except:
        download_state["spotdl_available"] = False
        return False

def install_spotdl():
    try:
        push_log("📦 Installazione spotdl in corso...", "warning")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "spotdl"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            push_log("✅ spotdl installato con successo!", "success")
            download_state["spotdl_available"] = True
            return True
        else:
            push_log(f"❌ Installazione spotdl fallita: {result.stderr[:120]}", "error")
            return False
    except Exception as e:
        push_log(f"❌ Errore: {e}", "error")
        return False

def download_spotify(spotify_url, output_folder):
    """Download a Spotify track / album / playlist using spotdl."""
    os.makedirs(output_folder, exist_ok=True)
    output_template = os.path.join(output_folder, "{artists} - {title}.{output-ext}")

    cmd = [
        "spotdl",
        "--output", output_template,
        "--format", "mp3",
        "--bitrate", "320k",
    ]

    # Use Spotify API credentials from .env if available — avoids rate limits
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        cmd += ["--client-id", client_id, "--client-secret", client_secret]
        push_log("🔑 Uso credenziali Spotify da .env", "info")
    else:
        push_log(
            "⚠️  Nessuna credenziale Spotify. Se ricevi rate limit, "
            "aggiungile nel tab Spotify → Credenziali.",
            "warning"
        )

    cmd.append(spotify_url)
    push_log(f"🎵 Avvio spotdl...")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=output_folder
        )
        downloaded = 0
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            push_log(f"  {line[:100]}")
            # Detect rate limit early and give actionable message
            if "rate" in line.lower() and ("limit" in line.lower() or "86400" in line):
                push_log(
                    "❌ RATE LIMIT Spotify! Crea credenziali gratuite su "
                    "developer.spotify.com e salvale nel tab Spotify → Credenziali.",
                    "error"
                )
            if "Downloaded" in line or "Skipping" in line:
                downloaded += 1
                download_state["success"] = downloaded
                m = re.search(r'"([^"]+)"', line)
                if m:
                    download_state["current_track"] = m.group(1)[:60]
        proc.wait()
        return proc.returncode == 0

    except FileNotFoundError:
        push_log("❌ spotdl non trovato nel PATH", "error")
        return False
    except Exception as e:
        push_log(f"❌ Errore spotdl: {e}", "error")
        return False

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
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        for line in proc.stdout:
            line = line.strip()
            if line and any(k in line for k in ["[download]", "[ExtractAudio]", "Destination", "ERROR"]):
                push_log(f"  {line[:90]}")
        proc.wait()
        if os.path.exists(output_path):
            return True
        # yt-dlp may have used a slightly different name — scan recent mp3s
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
        push_log(f"❌ Errore yt-dlp: {e}", "error")
        return False

def download_playlist_url(playlist_url, output_folder):
    """Download a YouTube playlist / channel / direct URL."""
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
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
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
        # ── Single track ──────────────────────────────────────────────
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
            push_log(
                "✅ Download completato!" if ok else "❌ Download fallito",
                "success" if ok else "error"
            )

        # ── YouTube playlist / direct URL ─────────────────────────────
        elif mode == "playlist_url":
            url = data["url"]
            push_log(f"🔗 Download YouTube playlist: {url}")
            dl["total"] = 0
            dl["current"] = 0
            ok = download_playlist_url(url, folder)
            push_log(
                "✅ Playlist completata!" if ok else "❌ Errore playlist",
                "success" if ok else "error"
            )

        # ── Spotify ───────────────────────────────────────────────────
        elif mode == "spotify":
            url = data["url"]
            dl["total"] = 0
            dl["current"] = 0
            dl["current_track"] = "Avvio spotdl..."
            # Auto-install spotdl if missing
            if not check_spotdl():
                push_log("⚠️ spotdl non trovato, lo installo...", "warning")
                if not install_spotdl():
                    push_log(
                        "❌ Impossibile installare spotdl. "
                        "Esegui manualmente: pip install spotdl",
                        "error"
                    )
                    dl["status"] = "error"
                    dl["active"] = False
                    return
            ok = download_spotify(url, folder)
            push_log(
                "✅ Download Spotify completato!" if ok else "❌ Errore download Spotify",
                "success" if ok else "error"
            )

        # ── Album (tracklist via Google) ──────────────────────────────
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
                    push_log("  ✅ Scaricata", "success")
                else:
                    dl["errors"] += 1
                    push_log("  ❌ Errore", "error")

                if i < dl["total"] and not dl["stop"]:
                    dl["status"] = "pausing"
                    push_log(f"  ⏸ Pausa {pause_sec}s...")
                    for _ in range(pause_sec):
                        if dl["stop"]:
                            break
                        time.sleep(1)

            elapsed = int(time.time() - start)
            push_log(
                f"✨ Completato in {elapsed}s — {dl['success']}/{dl['total']} tracce",
                "success"
            )

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
    body = request.json or {}
    mode = body.get("mode")
    folder = body.get("folder", "").strip()
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            download_state["download_path"] = folder
        except Exception as e:
            return jsonify({"error": f"Cartella non valida: {e}"}), 400

    label = queue_label(mode, body)
    item = queue_add(mode, body, label)
    position = len(queue_as_list())  # position after adding
    return jsonify({"ok": True, "queued": True, "id": item["id"],
                    "label": label, "position": position})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    download_state["stop"] = True
    download_state["status"] = "stopped"
    return jsonify({"ok": True})

@app.route("/api/queue", methods=["GET"])
def api_queue_get():
    return jsonify({"queue": queue_as_list(), "active": download_state["active"]})

@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    """Remove all pending items from the queue (does NOT stop the active download)."""
    cleared = len(queue_as_list())
    queue_clear()
    push_log(f"🗑️ Coda svuotata ({cleared} elementi rimossi)", "warning")
    return jsonify({"ok": True, "cleared": cleared})

@app.route("/api/queue/remove", methods=["POST"])
def api_queue_remove():
    """Remove a single item from the queue by id."""
    body = request.json or {}
    item_id = body.get("id")
    ok = queue_remove(item_id)
    return jsonify({"ok": ok})

@app.route("/api/browse_folder", methods=["POST"])
def api_browse_folder():
    """Open a native OS folder picker dialog and return selected path."""
    body = request.json or {}
    initial = body.get("initial", download_state["download_path"])
    selected = open_folder_dialog(initial)
    if selected:
        try:
            os.makedirs(selected, exist_ok=True)
            download_state["download_path"] = selected
            return jsonify({"folder": selected, "ok": True})
        except Exception as e:
            return jsonify({"folder": None, "ok": False, "error": str(e)})
    return jsonify({"folder": None, "ok": False})

@app.route("/api/set_folder", methods=["POST"])
def api_set_folder():
    body = request.json or {}
    folder = body.get("folder", "").strip()
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            download_state["download_path"] = folder
            return jsonify({"folder": folder, "ok": True})
        except Exception as e:
            return jsonify({"error": str(e), "ok": False}), 400
    return jsonify({"folder": download_state["download_path"], "ok": True})

@app.route("/api/check_deps")
def api_check_deps():
    deps = {}

    # yt-dlp uses --version
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
        deps["yt-dlp"] = True
    except:
        deps["yt-dlp"] = False

    # FFmpeg uses -version (single dash) — --version returns exit code 1 on Windows
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        deps["ffmpeg"] = result.returncode == 0
    except FileNotFoundError:
        deps["ffmpeg"] = False

    deps["spotdl"] = check_spotdl()
    deps["current_folder"] = download_state["download_path"]
    deps["spotify_creds"] = bool(
        os.environ.get("SPOTIFY_CLIENT_ID") and os.environ.get("SPOTIFY_CLIENT_SECRET")
    )
    return jsonify(deps)

@app.route("/api/install_spotdl", methods=["POST"])
def api_install_spotdl():
    threading.Thread(target=install_spotdl, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/spotify_creds", methods=["POST"])
def api_spotify_creds():
    """Save Spotify API credentials to .env and apply them immediately."""
    body = request.json or {}
    client_id = body.get("client_id", "").strip()
    client_secret = body.get("client_secret", "").strip()
    if not client_id or not client_secret:
        return jsonify({"error": "client_id e client_secret richiesti"}), 400
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        with open(env_path, "w") as f:
            f.write(f"SPOTIFY_CLIENT_ID={client_id}\n")
            f.write(f"SPOTIFY_CLIENT_SECRET={client_secret}\n")
        # Apply immediately without restart
        os.environ["SPOTIFY_CLIENT_ID"] = client_id
        os.environ["SPOTIFY_CLIENT_SECRET"] = client_secret
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    check_spotdl()

    if os.environ.get("SPOTIFY_CLIENT_ID"):
        print("✅ Credenziali Spotify trovate nel .env")
    else:
        print("⚠️  Nessuna credenziale Spotify — aggiungile dal tab Spotify nell'app per evitare rate limit.")

    print("\n🎵 Music Downloader avviato!")
    print("➡  Apri il browser su: http://localhost:5000\n")
    app.run(debug=False, port=5000)
