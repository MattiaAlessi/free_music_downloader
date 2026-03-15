import os
import re
import threading
import time
import subprocess
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import requests
from datetime import datetime
from tkinter import messagebox, filedialog
import customtkinter as ctk
from bs4 import BeautifulSoup

# ============================================
# CONFIGURAZIONE TEMA
# ============================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ============================================
# CLASSE PER AUTOCOMPLETAMENTO
# ============================================
class YoutubeSuggestions:
    @staticmethod
    def get_suggestions(query):
        if len(query) < 2:
            return []
        try:
            url = f"http://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2) as response:
                data = response.read().decode('utf-8')
                if data.startswith('window.google.ac.h('):
                    data = data[19:-1]
                    suggestions = json.loads(data)
                    if suggestions and len(suggestions) > 1:
                        return [s[0] for s in suggestions[1]]
            return []
        except:
            return []

# ============================================
# CLASSE PER RICERCA ALBUM VIA GOOGLE (SENZA API)
# ============================================
class AlbumSearcher:
    @staticmethod
    def search_album_tracks(album_name, artist_name=""):
        tracks = []
        try:
            if artist_name:
                search_query = f"{album_name} {artist_name} tracklist"
            else:
                search_query = f"{album_name} tracklist"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            google_url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
            response = requests.get(google_url, headers=headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if 'url?q=' in href and 'webcache' not in href:
                        match = re.search(r'url\?q=([^&]+)', href)
                        if match:
                            url = urllib.parse.unquote(match.group(1))
                            if any(site in url for site in ['genius.com', 'wikipedia.org', 'allmusic.com', 'discogs.com']):
                                links.append(url)

                for link in links[:3]:
                    print(f"Tentativo: {link}")
                    page_tracks = AlbumSearcher.parse_tracklist_page(link, album_name, artist_name)
                    if page_tracks and len(page_tracks) >= 4:
                        tracks = page_tracks
                        break

            if not tracks:
                genius_url = f"https://genius.com/albums/{artist_name.replace(' ', '-')}/{album_name.replace(' ', '-')}" if artist_name else ""
                if genius_url:
                    tracks = AlbumSearcher.parse_genius(genius_url, album_name, artist_name)

            if not tracks:
                tracks = [f"Traccia {i}" for i in range(1, 9)]

            return tracks[:15]

        except Exception as e:
            print(f"Errore ricerca album: {e}")
            return [f"Traccia {i}" for i in range(1, 9)]

    @staticmethod
    def parse_tracklist_page(url, album_name, artist_name):
        tracks = []
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                track_elements = soup.find_all(['li', 'tr', 'div'], class_=re.compile(r'track|song|list-item|chartlist-row', re.I))

                for elem in track_elements[:20]:
                    text = elem.get_text().strip()
                    match = re.search(r'(\d+)[\s.)-]+([A-Za-z0-9\s\'\-&]+)', text)
                    if match:
                        track_num = match.group(1)
                        track_name = match.group(2).strip()
                        if track_name and len(track_name) > 3:
                            tracks.append(f"{int(track_num):02d}. {track_name}")

                if not tracks:
                    all_text = soup.get_text()
                    lines = all_text.split('\n')
                    for line in lines[:50]:
                        match = re.search(r'(\d+)[\s.)-]+([A-Za-z0-9\s\'\-&]{3,30})', line)
                        if match:
                            track_num = match.group(1)
                            track_name = match.group(2).strip()
                            if track_name and len(track_name) > 3:
                                tracks.append(f"{int(track_num):02d}. {track_name}")

            return list(dict.fromkeys(tracks))

        except:
            return []

    @staticmethod
    def parse_genius(url, album_name, artist_name):
        tracks = []
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                track_rows = soup.find_all('div', class_=re.compile(r'chart_row|track_listing|song_row', re.I))

                for row in track_rows[:20]:
                    track_name_elem = row.find(['a', 'span'], class_=re.compile(r'title|name|song', re.I))
                    if track_name_elem:
                        track_name = track_name_elem.get_text().strip()
                        if track_name and len(track_name) > 3:
                            tracks.append(track_name)

                if not tracks:
                    all_text = soup.get_text()
                    lines = all_text.split('\n')
                    track_count = 0
                    for line in lines:
                        if album_name.lower() in line.lower() and len(line) < 100 and line.strip():
                            track_count += 1
                            tracks.append(f"Traccia {track_count:02d}")
                            if track_count >= 8:
                                break

            return tracks

        except:
            return []

# ============================================
# CLASSE PER FORMATTAZIONE NOMI
# ============================================
class NameFormatter:
    @staticmethod
    def format_title(title):
        minor_words = ['a', 'an', 'the', 'and', 'or', 'but', 'for', 'nor', 'on', 'at', 'to', 'by', 'with', 'in', 'of', 'feat', 'ft']
        words = title.split()
        formatted_words = []
        for i, word in enumerate(words):
            if i == 0 or word.lower() not in minor_words:
                if word.isupper():
                    formatted_words.append(word)
                else:
                    formatted_words.append(word.capitalize())
            else:
                formatted_words.append(word.lower())
        return ' '.join(formatted_words)

    @staticmethod
    def format_artist(artist):
        words = artist.split()
        formatted_words = []
        for word in words:
            if word.isupper():
                formatted_words.append(word)
            else:
                formatted_words.append(word.capitalize())
        return ' '.join(formatted_words)

    @staticmethod
    def format_filename(song, artist):
        formatted_song = NameFormatter.format_title(song)
        formatted_artist = NameFormatter.format_artist(artist) if artist else "Artista Sconosciuto"
        filename = f"{formatted_song} - {formatted_artist}"
        return re.sub(r'[\\/*?:"<>|]', "", filename)

# ============================================
# CLASSE PRINCIPALE
# ============================================
class SpotifyDownloaderApp:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("🎵 Music Downloader - Ricerca Album Automatica")

        self.window.geometry("900x680")
        self.window.minsize(820, 600)
        self.window.maxsize(1200, 800)

        self.center_window()

        self.download_path = os.path.join(os.path.expanduser("~"), "Desktop", "Musica Scaricata")
        self.is_downloading = False
        self._stop_flag = False       # FIX: rinominato per evitare conflitto col metodo stop_download()
        self.current_song_index = 0
        self.total_songs = 0
        self.success_count = 0
        self.error_count = 0
        self.tracks_list = []
        self.pause_duration = 10
        self.current_mode = "spotify"
        self.suggestions = []
        self.suggestion_buttons = []

        os.makedirs(self.download_path, exist_ok=True)

        self.setup_ui()
        self.check_requirements()

    def center_window(self):
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry(f'{width}x{height}+{x}+{y}')

    def setup_ui(self):
        self.main_frame = ctk.CTkFrame(self.window, corner_radius=15)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.main_frame.grid_rowconfigure(7, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # HEADER
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=60)
        header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 5))
        header_frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="🎵 MUSIC DOWNLOADER",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=("#1DB954", "#1DB954")
        )
        title_label.grid(row=0, column=0)

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Ricerca album automatica su Google",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        subtitle_label.grid(row=1, column=0)

        # STATO SISTEMA
        status_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)
        status_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        status_frame.grid_columnconfigure((0,1,2), weight=1)

        self.ytdlp_status = ctk.CTkLabel(status_frame, text="⚪ yt-dlp", font=ctk.CTkFont(size=11))
        self.ytdlp_status.grid(row=0, column=0, padx=2, pady=5)

        self.ffmpeg_status = ctk.CTkLabel(status_frame, text="⚪ FFmpeg", font=ctk.CTkFont(size=11))
        self.ffmpeg_status.grid(row=0, column=1, padx=2, pady=5)

        self.path_status = ctk.CTkLabel(status_frame, text="📁 Desktop", font=ctk.CTkFont(size=11))
        self.path_status.grid(row=0, column=2, padx=2, pady=5)

        # SELEZIONE MODALITÀ
        self.mode_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)
        self.mode_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=5)
        self.mode_frame.grid_columnconfigure(0, weight=1)

        mode_buttons = ctk.CTkFrame(self.mode_frame, fg_color="transparent")
        mode_buttons.grid(row=0, column=0, pady=5, padx=10, sticky="ew")
        mode_buttons.grid_columnconfigure((0,1), weight=1)

        self.spotify_mode_btn = ctk.CTkButton(
            mode_buttons,
            text="🎵 SPOTIFY",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            corner_radius=16,
            fg_color="#1DB954",
            hover_color="#1AA34A",
            text_color="black",
            command=lambda: self.switch_mode("spotify")
        )
        self.spotify_mode_btn.grid(row=0, column=0, padx=3, sticky="ew")

        self.manual_mode_btn = ctk.CTkButton(
            mode_buttons,
            text="🔍 MANUALE",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            corner_radius=16,
            fg_color="#FFA500",
            hover_color="#FF8C00",
            text_color="black",
            command=lambda: self.switch_mode("manual")
        )
        self.manual_mode_btn.grid(row=0, column=1, padx=3, sticky="ew")

        # SPOTIFY FRAME
        self.spotify_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)

        spotify_row = ctk.CTkFrame(self.spotify_frame, fg_color="transparent")
        spotify_row.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        spotify_row.grid_columnconfigure(0, weight=1)

        self.spotify_entry = ctk.CTkEntry(
            spotify_row,
            placeholder_text="Cerca canzone (es. Bohemian Rhapsody Queen)...",
            height=32,
            font=ctk.CTkFont(size=11)
        )
        self.spotify_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.spotify_paste = ctk.CTkButton(
            spotify_row,
            text="📋",
            width=30,
            height=32,
            font=ctk.CTkFont(size=11),
            command=lambda: self.paste_to_entry(self.spotify_entry)
        )
        self.spotify_paste.grid(row=0, column=1)

        # MANUAL FRAME
        self.manual_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)

        album_row = ctk.CTkFrame(self.manual_frame, fg_color="transparent")
        album_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        album_row.grid_columnconfigure(0, weight=1)

        album_label = ctk.CTkLabel(album_row, text="🎵 Nome Album:", font=ctk.CTkFont(size=11, weight="bold"))
        album_label.grid(row=0, column=0, sticky="w")

        self.album_entry = ctk.CTkEntry(
            album_row,
            placeholder_text="es. The Dark Side of the Moon",
            height=32,
            font=ctk.CTkFont(size=11)
        )
        self.album_entry.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.album_entry.bind("<KeyRelease>", self.on_search_key)

        self.suggestions_frame = ctk.CTkFrame(self.manual_frame, fg_color="#2D2D2D", corner_radius=5)
        self.suggestions_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        self.suggestions_frame.grid_columnconfigure(0, weight=1)

        artist_row = ctk.CTkFrame(self.manual_frame, fg_color="transparent")
        artist_row.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        artist_row.grid_columnconfigure(0, weight=1)

        artist_label = ctk.CTkLabel(artist_row, text="👤 Artista (opzionale):", font=ctk.CTkFont(size=11, weight="bold"))
        artist_label.grid(row=0, column=0, sticky="w")

        self.artist_entry = ctk.CTkEntry(
            artist_row,
            placeholder_text="es. Pink Floyd",
            height=32,
            font=ctk.CTkFont(size=11)
        )
        self.artist_entry.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        search_row = ctk.CTkFrame(self.manual_frame, fg_color="transparent")
        search_row.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        search_row.grid_columnconfigure(0, weight=1)

        self.search_album_btn = ctk.CTkButton(
            search_row,
            text="🔍 CERCA ALBUM SU GOOGLE",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#FFA500",
            hover_color="#FF8C00",
            command=self.search_album_and_show_tracks
        )
        self.search_album_btn.grid(row=0, column=0, sticky="ew")

        self.album_result_label = ctk.CTkLabel(
            self.manual_frame,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#FFA500"
        )
        self.album_result_label.grid(row=4, column=0, pady=(0, 5))

        # OPZIONI
        options_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)
        options_frame.grid(row=4, column=0, sticky="ew", padx=15, pady=5)
        options_frame.grid_columnconfigure(0, weight=1)

        folder_row = ctk.CTkFrame(options_frame, fg_color="transparent")
        folder_row.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        folder_row.grid_columnconfigure(0, weight=1)

        folder_controls = ctk.CTkFrame(folder_row, fg_color="transparent")
        folder_controls.grid(row=0, column=0, sticky="ew")
        folder_controls.grid_columnconfigure(0, weight=1)

        self.folder_label = ctk.CTkLabel(
            folder_controls,
            text=f"📁 {os.path.basename(self.download_path)}",
            font=ctk.CTkFont(size=10),
            anchor="w"
        )
        self.folder_label.grid(row=0, column=0, sticky="w", padx=(0, 5))

        self.browse_btn = ctk.CTkButton(
            folder_controls,
            text="📂 Sfoglia",
            width=70,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self.browse_folder
        )
        self.browse_btn.grid(row=0, column=1)

        pause_row = ctk.CTkFrame(options_frame, fg_color="transparent")
        pause_row.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        pause_label = ctk.CTkLabel(pause_row, text="⏱️ Pausa tra tracce:", font=ctk.CTkFont(size=10))
        pause_label.pack(side="left", padx=(0, 5))

        self.pause_var = ctk.StringVar(value="10")
        pause_menu = ctk.CTkOptionMenu(
            pause_row,
            values=["5", "10", "15", "20"],
            variable=self.pause_var,
            width=55,
            height=28,
            font=ctk.CTkFont(size=10)
        )
        pause_menu.pack(side="left")

        ctk.CTkLabel(pause_row, text="sec", font=ctk.CTkFont(size=10)).pack(side="left", padx=(2, 0))

        # BOTTONI PRINCIPALI
        buttons_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        buttons_frame.grid(row=5, column=0, sticky="ew", padx=15, pady=5)
        buttons_frame.grid_columnconfigure(0, weight=1)

        self.download_btn = ctk.CTkButton(
            buttons_frame,
            text="🚀 AVVIA DOWNLOAD",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=38,
            corner_radius=19,
            fg_color="#1DB954",
            hover_color="#1AA34A",
            text_color="black",
            command=self.start_download
        )
        self.download_btn.grid(row=0, column=0, sticky="ew", pady=(0, 3))

        self.stop_btn = ctk.CTkButton(
            buttons_frame,
            text="⏹️ FERMA",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=30,
            corner_radius=15,
            fg_color="#F44336",
            hover_color="#D32F2F",
            state="disabled",
            command=self.stop_download
        )
        self.stop_btn.grid(row=1, column=0, sticky="ew")

        # AREA PROGRESSO
        progress_frame = ctk.CTkFrame(self.main_frame, corner_radius=10)
        progress_frame.grid(row=6, column=0, sticky="nsew", padx=15, pady=(5, 10))
        progress_frame.grid_rowconfigure(4, weight=1)
        progress_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            progress_frame,
            text="⏳ In attesa...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#1DB954"
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=8, pady=(5, 2))

        info_row = ctk.CTkFrame(progress_frame, fg_color="transparent")
        info_row.grid(row=1, column=0, sticky="ew", padx=8, pady=2)
        info_row.grid_columnconfigure((0,1,2), weight=1)

        self.current_label = ctk.CTkLabel(info_row, text="🎵 -", font=ctk.CTkFont(size=10), anchor="w")
        self.current_label.grid(row=0, column=0, sticky="w")

        self.counter_label = ctk.CTkLabel(info_row, text="📊 0/0", font=ctk.CTkFont(size=10))
        self.counter_label.grid(row=0, column=1)

        self.time_label = ctk.CTkLabel(info_row, text="⏱️ --:--", font=ctk.CTkFont(size=10), anchor="e")
        self.time_label.grid(row=0, column=2, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=12, corner_radius=6, border_width=1)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=8, pady=2)
        self.progress_bar.set(0)

        self.pause_bar = ctk.CTkProgressBar(progress_frame, height=4, corner_radius=2, progress_color="#FFA500")
        self.pause_bar.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 2))
        self.pause_bar.set(0)

        stats_row = ctk.CTkFrame(progress_frame, fg_color="transparent")
        stats_row.grid(row=4, column=0, sticky="ew", padx=8, pady=2)

        self.success_label = ctk.CTkLabel(stats_row, text="✅ 0", font=ctk.CTkFont(size=10), text_color="#4CAF50")
        self.success_label.pack(side="left", padx=(0, 8))

        self.error_label = ctk.CTkLabel(stats_row, text="❌ 0", font=ctk.CTkFont(size=10), text_color="#F44336")
        self.error_label.pack(side="left")

        log_label = ctk.CTkLabel(progress_frame, text="📋 LOG:", font=ctk.CTkFont(size=11, weight="bold"))
        log_label.grid(row=5, column=0, sticky="w", padx=8, pady=(3, 1))

        self.log_box = ctk.CTkTextbox(progress_frame, height=70, font=ctk.CTkFont(size=10))
        self.log_box.grid(row=6, column=0, sticky="nsew", padx=8, pady=(0, 5))

        self.switch_mode("spotify")

    def switch_mode(self, mode):
        self.current_mode = mode
        if mode == "spotify":
            self.spotify_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=5)
            self.manual_frame.grid_forget()
            self.spotify_mode_btn.configure(fg_color="#1DB954")
            self.manual_mode_btn.configure(fg_color="#FFA500")
        else:
            self.manual_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=5)
            self.spotify_frame.grid_forget()
            self.manual_mode_btn.configure(fg_color="#1DB954")
            self.spotify_mode_btn.configure(fg_color="#FFA500")

    def on_search_key(self, event):
        query = self.album_entry.get().strip()
        for btn in self.suggestion_buttons:
            btn.destroy()
        self.suggestion_buttons.clear()
        if len(query) >= 2:
            thread = threading.Thread(target=self.get_suggestions, args=(query,))
            thread.daemon = True
            thread.start()

    def get_suggestions(self, query):
        suggestions = YoutubeSuggestions.get_suggestions(query)
        self.window.after(0, self.show_suggestions, suggestions)

    def show_suggestions(self, suggestions):
        if suggestions:
            for s in suggestions[:3]:
                btn = ctk.CTkButton(
                    self.suggestions_frame,
                    text=f"🔍 {s[:35]}",
                    font=ctk.CTkFont(size=10),
                    height=24,
                    fg_color="#3D3D3D",
                    hover_color="#4D4D4D",
                    anchor="w",
                    command=lambda x=s: self.select_suggestion(x)
                )
                btn.pack(fill="x", padx=2, pady=1)
                self.suggestion_buttons.append(btn)

    def select_suggestion(self, suggestion):
        self.album_entry.delete(0, "end")
        self.album_entry.insert(0, suggestion)
        for btn in self.suggestion_buttons:
            btn.destroy()
        self.suggestion_buttons.clear()

    def search_album_and_show_tracks(self):
        album = self.album_entry.get().strip()
        artist = self.artist_entry.get().strip()

        if not album:
            messagebox.showwarning("Attenzione", "Inserisci il nome dell'album!")
            return

        self.log(f"🔍 Cerco album su Google: {album} {artist if artist else ''}")
        self.status_label.configure(text="⏳ Cerco tracce album su Google...")
        self.search_album_btn.configure(state="disabled")
        self.window.update()

        thread = threading.Thread(target=self._search_and_show_window, args=(album, artist))
        thread.daemon = True
        thread.start()

    def _search_and_show_window(self, album, artist):
        try:
            tracks = AlbumSearcher.search_album_tracks(album, artist)
            self.window.after(0, lambda: self.search_album_btn.configure(state="normal"))
            if tracks and len(tracks) > 0:
                self.window.after(0, self._show_tracks_window, tracks, album, artist)
            else:
                self.window.after(0, lambda: messagebox.showwarning("Attenzione",
                    f"Nessuna traccia trovata per '{album}'. Verifica il nome dell'album."))
                self.window.after(0, lambda: self.status_label.configure(text="⏳ In attesa..."))
        except Exception as e:
            self.window.after(0, lambda: self.search_album_btn.configure(state="normal"))
            self.window.after(0, lambda: messagebox.showerror("Errore", f"Errore ricerca: {str(e)}"))
            self.window.after(0, lambda: self.status_label.configure(text="⏳ In attesa..."))

    def _show_tracks_window(self, tracks, album, artist):
        self.status_label.configure(text="✅ Tracce trovate! Verifica...")

        tracks_window = ctk.CTkToplevel(self.window)
        tracks_window.title(f"Tracce album: {album}")
        tracks_window.geometry("550x450")
        tracks_window.minsize(450, 350)

        tracks_window.update_idletasks()
        width = tracks_window.winfo_width()
        height = tracks_window.winfo_height()
        x = (tracks_window.winfo_screenwidth() // 2) - (width // 2)
        y = (tracks_window.winfo_screenheight() // 2) - (height // 2)
        tracks_window.geometry(f'{width}x{height}+{x}+{y}')

        tracks_window.grab_set()
        tracks_window.focus_set()
        tracks_window.transient(self.window)

        main_frame = ctk.CTkFrame(tracks_window, corner_radius=10)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        title_label = ctk.CTkLabel(
            main_frame,
            text=f"🎵 {album}",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#FFA500"
        )
        title_label.pack(pady=(10, 2))

        if artist:
            artist_label = ctk.CTkLabel(
                main_frame,
                text=f"👤 {artist}",
                font=ctk.CTkFont(size=13)
            )
            artist_label.pack(pady=(0, 5))

        info_label = ctk.CTkLabel(
            main_frame,
            text=f"Trovate {len(tracks)} tracce su Google:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        info_label.pack(pady=(5, 5))

        list_frame = ctk.CTkFrame(main_frame, corner_radius=5)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        text_widget = ctk.CTkTextbox(list_frame, font=ctk.CTkFont(size=11), corner_radius=5, wrap="word")
        text_widget.pack(side="left", fill="both", expand=True)

        for i, track in enumerate(tracks, 1):
            text_widget.insert("end", f"{i:2d}. {track}\n")

        text_widget.configure(state="disabled")

        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=10)

        def on_confirm():
            self.tracks_list = []
            for track in tracks:
                self.tracks_list.append({
                    "name": track,
                    "artist": artist if artist else "Artista sconosciuto"
                })
            self.album_result_label.configure(text=f"✅ {len(tracks)} tracce pronte per download")
            self.log(f"✅ Album pronto: {len(tracks)} tracce da scaricare", "success")
            tracks_window.destroy()
            self.status_label.configure(text="✅ Pronto per download album")

        def on_cancel():
            tracks_window.destroy()
            self.status_label.configure(text="⏳ In attesa...")
            self.log("❌ Download album annullato", "info")

        confirm_btn = ctk.CTkButton(
            button_frame,
            text="✅ SCARICA QUESTE TRACCE",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=38,
            fg_color="#1DB954",
            hover_color="#1AA34A",
            text_color="black",
            command=on_confirm
        )
        confirm_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        cancel_btn = ctk.CTkButton(
            button_frame,
            text="❌ ANNULLA",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=38,
            fg_color="#F44336",
            hover_color="#D32F2F",
            command=on_cancel
        )
        cancel_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

    def check_requirements(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            self.ffmpeg_status.configure(text="✅ FFmpeg", text_color="#4CAF50")
        except:
            self.ffmpeg_status.configure(text="❌ FFmpeg", text_color="#F44336")
            self.log("⚠️ FFmpeg non trovato. Installa con: winget install FFmpeg", "warning")

        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
            self.ytdlp_status.configure(text="✅ yt-dlp", text_color="#4CAF50")
            self.log("✅ yt-dlp trovato", "success")
        except:
            self.ytdlp_status.configure(text="⚠️ yt-dlp", text_color="#FFA500")
            self.log("📦 Installazione yt-dlp...", "info")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"], check=True)
                self.ytdlp_status.configure(text="✅ yt-dlp", text_color="#4CAF50")
                self.log("✅ yt-dlp installato", "success")
            except:
                self.log("❌ Errore installazione yt-dlp", "error")

    def paste_to_entry(self, entry):
        try:
            text = self.window.clipboard_get()
            if text:
                entry.delete(0, "end")
                entry.insert(0, text)
                self.log("📋 Incollato")
        except:
            pass

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.folder_label.configure(text=f"📁 {os.path.basename(folder)}")
            self.log(f"📁 Cartella: {os.path.basename(folder)}")

    def log(self, msg, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = "✅" if type == "success" else "❌" if type == "error" else "⚠️" if type == "warning" else "ℹ️"
        self.log_box.insert("end", f"[{timestamp}] {prefix} {msg}\n")
        self.log_box.see("end")
        self.window.update()

    def update_stats(self):
        self.success_label.configure(text=f"✅ {self.success_count}")
        self.error_label.configure(text=f"❌ {self.error_count}")
        self.counter_label.configure(text=f"📊 {self.current_song_index}/{self.total_songs}")
        if self.total_songs > 0:
            self.progress_bar.set(self.current_song_index / self.total_songs)

    def stop_download(self):
        # FIX: usa _stop_flag invece di self.stop_download (che puntava al metodo stesso)
        self._stop_flag = True
        self.log("⏹️ Fermato", "warning")
        self.status_label.configure(text="⏹️ Fermato")
        self.stop_btn.configure(state="disabled")

    def start_download(self):
        if self.is_downloading:
            return

        if self.current_mode == "spotify":
            if not self.spotify_entry.get().strip():
                messagebox.showwarning("Attenzione", "Inserisci una canzone da cercare!")
                return
            download_type = "spotify"
        else:
            if self.tracks_list:
                download_type = "album"
            else:
                if not self.album_entry.get().strip():
                    messagebox.showwarning("Attenzione", "Inserisci il nome dell'album o cerca prima le tracce!")
                    return
                messagebox.showinfo("Info", "Cerca prima le tracce con 'CERCA ALBUM SU GOOGLE'")
                return

        self._stop_flag = False
        self.current_song_index = 0
        self.success_count = 0
        self.error_count = 0
        self.is_downloading = True
        self.pause_duration = int(self.pause_var.get())

        self.download_btn.configure(state="disabled", text="⏳ DOWNLOAD...")
        self.stop_btn.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.progress_bar.set(0)
        self.pause_bar.set(0)
        self.update_stats()

        thread = threading.Thread(target=self.download_process, args=(download_type,))
        thread.daemon = True
        thread.start()

    # ------------------------------------------------------------------
    # FIX: metodo centralizzato per eseguire yt-dlp in modo affidabile
    # ------------------------------------------------------------------
    def _run_ytdlp(self, search_query, output_path):
        """
        Scarica la prima corrispondenza YouTube come MP3.
        Ritorna True se il file è stato creato, False altrimenti.

        Strategia:
        - Usa un template con %(ext)s in modo che yt-dlp scriva il file
          col nome corretto prima della conversione.
        - Dopo la conversione cerca il .mp3 risultante nella cartella.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Template senza estensione fissa: yt-dlp aggiunge .mp3 dopo la conversione
        output_template = output_path  # es. /path/to/Song - Artist.mp3
        # Rimuovi .mp3 finale dal template, yt-dlp lo aggiunge da solo
        base_path = output_path[:-4] if output_path.endswith(".mp3") else output_path

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-warnings",
            "-o", f"{base_path}.%(ext)s",
            f"ytsearch1:{search_query}"
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            output_lines = []
            for line in process.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    # Mostra progressi rilevanti nel log
                    if any(kw in line for kw in ["[download]", "[ExtractAudio]", "Destination", "ERROR"]):
                        self.window.after(0, self.log, f"   {line[:80]}")

            process.wait()

            # Controlla se il file mp3 esiste
            if os.path.exists(output_path):
                return True

            # yt-dlp potrebbe aver salvato con nome leggermente diverso —
            # cerca qualsiasi .mp3 creato di recente nella stessa cartella
            folder = os.path.dirname(output_path)
            now = time.time()
            for fname in os.listdir(folder):
                if fname.endswith(".mp3"):
                    fpath = os.path.join(folder, fname)
                    if now - os.path.getmtime(fpath) < 60:  # creato nell'ultimo minuto
                        return True

            if process.returncode != 0:
                self.window.after(0, self.log,
                    f"   yt-dlp exit code {process.returncode}: {' '.join(output_lines[-2:])}", )
            return False

        except FileNotFoundError:
            self.window.after(0, self.log,
                "❌ yt-dlp non trovato. Installalo con: pip install yt-dlp", "error")
            return False
        except Exception as e:
            self.window.after(0, self.log, f"❌ Errore yt-dlp: {e}", "error")
            return False

    def download_process(self, download_type):
        try:
            if download_type == "spotify":
                query = self.spotify_entry.get().strip()
                self.total_songs = 1
                self.current_song_index = 1
                self.update_stats()

                self.log(f"🔍 Cerco su YouTube: {query}")
                self.window.after(0, self.status_label.configure, {"text": f"⬇️ Scarico: {query[:30]}..."})

                # Per la modalità spotify salva con titolo dal video
                temp_name = NameFormatter.format_filename(query, "")
                output_path = os.path.join(self.download_path, f"{temp_name}.mp3")

                ok = self._run_ytdlp(query, output_path)

                if ok:
                    self.success_count = 1
                    self.log("✅ Download completato!", "success")
                else:
                    self.error_count = 1
                    self.log("❌ Download fallito", "error")

            elif download_type == "album":
                self.total_songs = len(self.tracks_list)
                self.log(f"💿 Download album - {self.total_songs} tracce")
                start_time = time.time()

                for i, track in enumerate(self.tracks_list, 1):
                    if self._stop_flag:
                        break

                    self.current_song_index = i
                    song_name = track["name"]
                    artist_name = track["artist"]

                    filename = NameFormatter.format_filename(song_name, artist_name)
                    self.window.after(0, self.current_label.configure,
                                      {"text": f"🎵 {filename[:30]}..."})
                    self.update_stats()

                    self.log(f"[{i}/{self.total_songs}] {song_name[:40]}...")
                    self.window.after(0, self.status_label.configure,
                                      {"text": f"⬇️ [{i}/{self.total_songs}] {song_name[:25]}..."})

                    search_query = f"{song_name} {artist_name}"
                    output_path = os.path.join(self.download_path, f"{filename}.mp3")

                    ok = self._run_ytdlp(search_query, output_path)

                    if ok:
                        self.success_count += 1
                        self.log(f"   ✅ Scaricata", "success")
                    else:
                        self.error_count += 1
                        self.log(f"   ❌ Errore download", "error")

                    self.update_stats()

                    # Pausa tra tracce
                    if i < self.total_songs and not self._stop_flag:
                        self.log(f"   ⏸️ Pausa {self.pause_duration}s...")
                        for s in range(self.pause_duration):
                            if self._stop_flag:
                                break
                            self.window.after(0, self.pause_bar.set, (s + 1) / self.pause_duration)
                            self.window.after(0, self.time_label.configure,
                                              {"text": f"⏱️ {self.pause_duration - s}s"})
                            time.sleep(1)
                        self.window.after(0, self.pause_bar.set, 0)

                if not self._stop_flag:
                    elapsed = int(time.time() - start_time)
                    self.log(f"✨ Album completato in {elapsed}s!", "success")

            if not self._stop_flag:
                self.window.after(0, self.status_label.configure, {"text": "✅ COMPLETATO!"})
                self.window.after(0, self.progress_bar.set, 1.0)
                self.log(f"{'='*30}")
                self.log(f"✨ COMPLETATO! {self.success_count}/{self.total_songs} tracce", "success")

                if self.success_count > 0:
                    self.window.after(0, messagebox.showinfo,
                        "Successo!", f"✅ {self.success_count} file salvati in:\n{self.download_path}")

        except Exception as e:
            self.log(f"❌ ERRORE: {str(e)}", "error")
            self.window.after(0, messagebox.showerror, "Errore", str(e))

        finally:
            self.window.after(0, self.download_btn.configure,
                              {"state": "normal", "text": "🚀 AVVIA DOWNLOAD"})
            self.window.after(0, self.stop_btn.configure, {"state": "disabled"})
            self.is_downloading = False
            self.window.after(0, self.pause_bar.set, 0)
            self.window.after(0, self.time_label.configure, {"text": "⏱️ --:--"})

    def run(self):
        self.window.mainloop()

# ============================================
# AVVIO
# ============================================
if __name__ == "__main__":
    try:
        import customtkinter
    except ImportError:
        print("📦 Installazione customtkinter...")
        subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter"])
        import customtkinter

    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("📦 Installazione requests e beautifulsoup4...")
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"])

    try:
        import yt_dlp
    except ImportError:
        print("📦 Installazione yt-dlp...")
        subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"])

    app = SpotifyDownloaderApp()
    app.run()
