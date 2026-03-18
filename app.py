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
    "status": "idle",
    "download_path": os.path.join(os.path.expanduser("~"), "Desktop", "Musica Scaricata"),
    "spotdl_available": False,
}

# ============================================
# DOWNLOAD QUEUE
# ============================================
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
        if mode == "album":
            tracks = data.get("tracks", [])
            artist = data.get("artist", "")
            album_name = data.get("album", "Album")
            added_items = []
            for track in tracks:
                clean_name = re.sub(r'^\d+[\s.)-]+', '', track).strip()
                item_data = {
                    "query": f"{clean_name} {artist}",
                    "artist": artist,
                    "album": album_name
                }
                item = {
                    "id": queue_next_id(),
                    "mode": "single",
                    "data": item_data,
                    "label": clean_name
                }
                download_queue.append(item)
                added_items.append(item)
            return added_items
        item = {"id": queue_next_id(), "mode": mode, "data": data, "label": label}
        download_queue.append(item)
        return [item]

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

# ============================================
# FIX 1 — QUEUE WORKER
# Dopo uno stop, resetta correttamente lo stato e riprende
# il prossimo item in coda senza bloccarsi.
# ============================================
def queue_worker():
    while True:
        # Aspetta se è in pausa
        if download_state["status"] == "pausing":
            time.sleep(0.5)
            continue

        # Aspetta se download attivo
        if download_state["active"]:
            time.sleep(0.5)
            continue

        # Dopo uno stop: resetta flag e torna idle
        if download_state["stop"]:
            download_state["stop"] = False
            download_state["status"] = "idle"
            time.sleep(0.5)
            continue

        item = queue_pop_first()
        if item is None:
            time.sleep(1)
            continue

        # Reset completo prima di ogni download
        download_state["active"] = True
        download_state["status"] = "downloading"
        download_state["stop"] = False
        download_state["success"] = 0
        download_state["errors"] = 0
        download_state["current"] = 0
        download_state["total"] = 0
        download_state["current_track"] = ""
        download_state["log"] = []

        try:
            push_log(f"▶ Inizio: {item['label']}", "info")
            do_download(item["mode"], item["data"])
        except Exception as e:
            push_log(f"❌ Errore worker: {e}", "error")
            download_state["status"] = "error"
        finally:
            download_state["active"] = False
            if download_state["status"] not in ("pausing", "stopped", "error"):
                download_state["status"] = "idle"


_queue_worker_thread = threading.Thread(target=queue_worker, daemon=True)
_queue_worker_thread.start()

def push_log(msg, level="info"):
    ts = time.strftime("%H:%M:%S")
    download_state["log"].append({"ts": ts, "msg": msg, "level": level})
    if len(download_state["log"]) > 300:
        download_state["log"] = download_state["log"][-300:]

# ============================================
# FIX 2 — ALBUM SEARCHER
# Usa MusicBrainz (API JSON, nessun blocco) come fonte principale,
# poi Genius scraping, poi DuckDuckGo come fallback.
# User-Agent realistico su tutte le richieste HTTP.
# ============================================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

class AlbumSearcher:

    @staticmethod
    def search_album_tracks(album_name, artist_name=""):
        # 1) MusicBrainz — API pubblica, no blocchi
        tracks = AlbumSearcher._musicbrainz(album_name, artist_name)
        if tracks:
            return tracks[:20]

        # 2) Genius scraping
        if artist_name:
            slug_artist = re.sub(r"[^a-z0-9]+", "-", artist_name.lower()).strip("-")
            slug_album  = re.sub(r"[^a-z0-9]+", "-", album_name.lower()).strip("-")
            genius_url = f"https://genius.com/albums/{slug_artist}/{slug_album}"
            tracks = AlbumSearcher._parse_genius(genius_url)
            if tracks:
                return tracks[:20]

        # 3) DuckDuckGo → pagine esterne
        tracks = AlbumSearcher._duckduckgo(album_name, artist_name)
        if tracks:
            return tracks[:20]

        return []

    @staticmethod
    def _musicbrainz(album_name, artist_name=""):
        try:
            query = f'release:"{album_name}"'
            if artist_name:
                query += f' AND artist:"{artist_name}"'
            resp = requests.get(
                "https://musicbrainz.org/ws/2/release",
                # Prendi le prime 10 release per scegliere quella con più tracce
                params={"query": query, "fmt": "json", "limit": 10},
                headers={"User-Agent": "MusicDownloader/1.0 (local)"},
                timeout=10
            )
            if resp.status_code != 200:
                return []
            releases = resp.json().get("releases", [])
            if not releases:
                return []

            # Scarica i dettagli di ogni release e tieni quella con più tracce
            best_tracks = []
            for release in releases:
                release_id = release["id"]
                detail = requests.get(
                    f"https://musicbrainz.org/ws/2/release/{release_id}",
                    params={"fmt": "json", "inc": "recordings"},
                    headers={"User-Agent": "MusicDownloader/1.0 (local)"},
                    timeout=10
                )
                if detail.status_code != 200:
                    continue
                tracks = []
                for medium in detail.json().get("media", []):
                    for t in medium.get("tracks", []):
                        title = t.get("title", "").strip()
                        if title:
                            tracks.append(title)
                if len(tracks) > len(best_tracks):
                    best_tracks = tracks
                # Piccola pausa per rispettare il rate limit di MusicBrainz (1 req/s)
                time.sleep(1.1)

            return best_tracks
        except Exception as e:
            push_log(f"  MusicBrainz: {e}", "warning")
            return []

    @staticmethod
    def _duckduckgo(album_name, artist_name=""):
        try:
            q = f"{album_name} {artist_name} tracklist".strip()
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            links = []
            for a in soup.find_all("a", class_="result__url", href=True):
                href = a["href"]
                if any(s in href for s in ["genius.com", "wikipedia.org",
                                            "allmusic.com", "discogs.com"]):
                    links.append(href if href.startswith("http") else "https://" + href)
            for link in links[:4]:
                tracks = AlbumSearcher._parse_page(link)
                if len(tracks) >= 4:
                    return tracks
            return []
        except Exception as e:
            push_log(f"  DuckDuckGo: {e}", "warning")
            return []

    @staticmethod
    def _parse_page(url):
        tracks = []
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            elems = soup.find_all(
                ["li", "tr", "div"],
                class_=re.compile(r"track|song|list-item|chartlist-row", re.I)
            )
            for e in elems[:25]:
                text = e.get_text(separator=" ").strip()
                m = re.search(r"(\d+)[\s.)-]+([^\n\r]{3,60})", text)
                if m:
                    name = m.group(2).strip()
                    if 3 < len(name) < 80:
                        tracks.append(f"{int(m.group(1)):02d}. {name}")
            if not tracks:
                for line in soup.get_text().split("\n"):
                    line = line.strip()
                    m = re.search(r"^(\d{1,2})[\s.)-]+([A-Za-zÀ-ÖØ-öø-ÿ0-9\s'\-&]{3,50})$", line)
                    if m:
                        tracks.append(f"{int(m.group(1)):02d}. {m.group(2).strip()}")
                    if len(tracks) >= 20:
                        break
            return list(dict.fromkeys(tracks))
        except:
            return []

    @staticmethod
    def _parse_genius(url):
        tracks = []
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all(
                "div",
                class_=re.compile(r"chart_row|track_listing|song_row", re.I)
            )
            for row in rows[:25]:
                el = row.find(["a", "span"], class_=re.compile(r"title|name|song", re.I))
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
# FIX 3 — FOLDER DIALOG (Windows)
# Usa tkinter come metodo principale (built-in Python, nessuna dipendenza).
# Fallback PowerShell con escape corretto dei percorsi.
# ============================================
def open_folder_dialog(initial_dir=None):
    initial = initial_dir or os.path.expanduser("~")
    if not os.path.isdir(initial):
        initial = os.path.expanduser("~")

    if sys.platform == "win32":
        # Metodo 1: tkinter (built-in, funziona sempre su Windows)
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(
                title="Scegli cartella di download",
                initialdir=initial
            )
            root.destroy()
            return path.replace("/", "\\") if path else None
        except Exception as e:
            push_log(f"  tkinter dialog error: {e}", "warning")

        # Metodo 2: PowerShell con escape
        try:
            safe_initial = initial.replace("'", "''")
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                f"$f.SelectedPath='{safe_initial}';"
                "$f.ShowNewFolderButton=$true;"
                "if($f.ShowDialog()-eq'OK'){Write-Output $f.SelectedPath}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=60
            )
            path = result.stdout.strip()
            return path if path else None
        except Exception as e:
            push_log(f"  PowerShell dialog error: {e}", "warning")
            return None

    elif sys.platform == "darwin":
        try:
            safe_initial = initial.replace('"', '\\"')
            script = (
                f'tell app "Finder" to return POSIX path of '
                f'(choose folder with prompt "Scegli cartella" '
                f'default location POSIX file "{safe_initial}")'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=60
            )
            path = result.stdout.strip()
            return path if path else None
        except Exception as e:
            push_log(f"  osascript error: {e}", "warning")
            return None

    else:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askdirectory(title="Scegli cartella", initialdir=initial)
            root.destroy()
            return path if path else None
        except:
            pass
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


# ============================================
# SPOTDL
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
    os.makedirs(output_folder, exist_ok=True)
    output_template = os.path.join(output_folder, "{artists} - {title}.{output-ext}")
    cmd = ["spotdl", "--output", output_template, "--format", "mp3", "--bitrate", "320k"]
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        cmd += ["--client-id", client_id, "--client-secret", client_secret]
        push_log("🔑 Uso credenziali Spotify da .env", "info")
    else:
        push_log("⚠️  Nessuna credenziale Spotify. Se ricevi rate limit, aggiungile nel tab Spotify.", "warning")
    cmd.append(spotify_url)
    push_log("🎵 Avvio spotdl...")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", cwd=output_folder
        )
        downloaded = 0
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            push_log(f"  {line[:100]}")
            if "rate" in line.lower() and ("limit" in line.lower() or "86400" in line):
                push_log("❌ RATE LIMIT Spotify! Crea credenziali su developer.spotify.com", "error")
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
# YT-DLP
# ============================================
def run_ytdlp(search_query, output_path, max_duration=600):
    """
    Scarica una singola traccia da YouTube.
    - max_duration: durata massima in secondi per escludere full-album video
    - Il nome del file è sempre quello passato in output_path (non il titolo YouTube)
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    base = output_path[:-4] if output_path.endswith(".mp3") else output_path

    # Query in ordine di priorità. Le keyword extra ("official audio", "lyrics")
    # servono SOLO per orientare YouTube, non finiscono nel nome file.
    search_variants = [
        f"{search_query} official audio",
        f"{search_query} official",
        f"{search_query}",
    ]

    base_cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-warnings",
        "--match-filter", f"duration < {max_duration}",
        # Nome file FISSO — non usa il titolo YouTube
        "-o", f"{base}.%(ext)s",
    ]

    for variant in search_variants:
        cmd = base_cmd + [f"ytsearch3:{variant}"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace"
            )
            found = False
            for line in proc.stdout:
                line = line.strip()
                if line and any(k in line for k in ["[download]", "[ExtractAudio]", "Destination", "ERROR"]):
                    push_log(f"  {line[:90]}")
                if "Destination" in line:
                    found = True
            proc.wait()

            if os.path.exists(output_path):
                return True
            # yt-dlp a volte usa estensioni intermedie — cerca mp3 recenti
            folder = os.path.dirname(output_path) or "."
            now = time.time()
            for f in os.listdir(folder):
                if f.endswith(".mp3") and now - os.path.getmtime(os.path.join(folder, f)) < 90:
                    return True

            if not found:
                push_log(f"  ⚠ Nessun video valido per: {variant[:50]}, provo...", "warning")
                continue
            # File non trovato ma processo ok — probabilmente tutti i risultati
            # erano più lunghi di max_duration, prova la variante successiva
            continue

        except FileNotFoundError:
            push_log("❌ yt-dlp non trovato. Installa con: pip install yt-dlp", "error")
            return False
        except Exception as e:
            push_log(f"❌ Errore yt-dlp: {e}", "error")
            return False

    push_log(f"❌ Nessun risultato per: {search_query[:60]}", "error")
    return False

def download_playlist_url(playlist_url, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    output_template = os.path.join(output_folder, "%(playlist_index)s. %(title)s.%(ext)s")
    cmd = [
        "yt-dlp", "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-warnings", "--yes-playlist",
        "-o", output_template, playlist_url
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
# DO_DOWNLOAD (chiamato dal worker)
# ============================================
def do_download(mode, data):
    dl = download_state
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
            # Singola canzone: fino a 15 minuti (per suite, medley, ecc.)
            ok = run_ytdlp(query, out, max_duration=900)
            dl["success"] = 1 if ok else 0
            dl["errors"] = 0 if ok else 1
            push_log("✅ Download completato!" if ok else "❌ Download fallito",
                     "success" if ok else "error")

        elif mode == "playlist_url":
            url = data["url"]
            push_log(f"🔗 Download YouTube playlist: {url}")
            dl["total"] = 0
            dl["current"] = 0
            ok = download_playlist_url(url, folder)
            push_log("✅ Playlist completata!" if ok else "❌ Errore playlist",
                     "success" if ok else "error")

        elif mode == "spotify":
            url = data["url"]
            dl["total"] = 0
            dl["current"] = 0
            dl["current_track"] = "Avvio spotdl..."
            if not check_spotdl():
                push_log("⚠️ spotdl non trovato, lo installo...", "warning")
                if not install_spotdl():
                    push_log("❌ Impossibile installare spotdl. Esegui: pip install spotdl", "error")
                    dl["status"] = "error"
                    return
            ok = download_spotify(url, folder)
            push_log("✅ Download Spotify completato!" if ok else "❌ Errore download Spotify",
                     "success" if ok else "error")

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
                # Tracce album: max 10 minuti per evitare full-album video
                ok = run_ytdlp(f"{track} {artist}", out, max_duration=600)
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
            push_log(f"✨ Completato in {elapsed}s — {dl['success']}/{dl['total']} tracce", "success")

        dl["status"] = "done"

    except Exception as e:
        push_log(f"❌ ERRORE: {e}", "error")
        dl["status"] = "error"


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
    items = queue_add(mode, body, label)
    item = items[0]
    position = len(queue_as_list())
    return jsonify({"ok": True, "queued": True, "id": item["id"],
                    "label": label, "position": position})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Ferma il download corrente e svuota anche la coda."""
    download_state["stop"] = True
    download_state["status"] = "stopped"
    queue_clear()
    return jsonify({"ok": True})

@app.route("/api/skip", methods=["POST"])
def api_skip():
    """Ferma il download corrente e passa automaticamente al prossimo in coda."""
    download_state["stop"] = True
    download_state["status"] = "stopped"
    # Il queue_worker rileva stop=True con active=False, resetta e prende il prossimo item
    return jsonify({"ok": True})

@app.route("/api/queue", methods=["GET"])
def api_queue_get():
    return jsonify({"queue": queue_as_list(), "active": download_state["active"]})

@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    cleared = len(queue_as_list())
    queue_clear()
    push_log(f"🗑️ Coda svuotata ({cleared} elementi rimossi)", "warning")
    return jsonify({"ok": True, "cleared": cleared})

@app.route("/api/queue/remove", methods=["POST"])
def api_queue_remove():
    body = request.json or {}
    item_id = body.get("id")
    ok = queue_remove(item_id)
    return jsonify({"ok": ok})

@app.route("/api/queue/remove/<int:item_id>", methods=["POST"])
def api_queue_remove_by_id(item_id):
    with queue_lock:
        global download_queue
        download_queue = [i for i in download_queue if i["id"] != item_id]
    return jsonify({"ok": True})

@app.route("/api/browse_folder", methods=["POST"])
def api_browse_folder():
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
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
        deps["yt-dlp"] = True
    except:
        deps["yt-dlp"] = False
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