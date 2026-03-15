# 🎵 Music Downloader

A desktop app to download music from YouTube using album search or Spotify-style search queries. Built with Python, `yt-dlp`, and `customtkinter`.

---

## Requirements

- **Python 3.8+** — [Download here](https://www.python.org/downloads/)
- **FFmpeg** — Required to convert audio to MP3

### Install FFmpeg

**Windows:**
```bash
winget install FFmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

---

## Installation

### 1. Clone or download this project

Place `music_downloader.py` and `requirements.txt` in the same folder.

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

> On some systems you may need `pip3` instead of `pip`.

---

## Running the App

```bash
python music_downloader.py
```

> On some systems use `python3 music_downloader.py`

The app will automatically check for and install any missing Python dependencies on first launch.

---

## How to Use

The app has two modes, selectable via the buttons at the top.

---

### 🎵 Spotify Mode

Use this to search and download a **single track** by name or Spotify-style query.

1. Select the **SPOTIFY** tab
2. Type or paste a song name (e.g. `Bohemian Rhapsody Queen`) into the search field  
   _(You can also paste a direct YouTube URL if you prefer)_
3. Click **🚀 AVVIA DOWNLOAD**

The app will search YouTube for the best match and download it as an MP3.

---

### 🔍 Manual / Album Mode

Use this to download an **entire album** automatically.

1. Select the **MANUALE** tab
2. Enter the **album name** (e.g. `The Dark Side of the Moon`)
3. Optionally enter the **artist name** (e.g. `Pink Floyd`) for better results
4. Click **🔍 CERCA ALBUM SU GOOGLE**
5. A window will appear with the tracklist found online — review it
6. Click **✅ SCARICA QUESTE TRACCE** to confirm
7. Click **🚀 AVVIA DOWNLOAD** to start downloading all tracks

---

## Options

| Option | Description |
|---|---|
| 📂 Sfoglia | Choose where downloaded files are saved (default: `~/Desktop/Musica Scaricata`) |
| ⏱️ Pausa tra tracce | Delay between track downloads (5–20 seconds). Helps avoid rate limiting. |
| ⏹️ FERMA | Stop the current download session |

---

## Output

- Files are saved as **MP3** in the selected folder
- Album tracks are named: `Track Name - Artist Name.mp3`
- Single tracks use the YouTube video title

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `FFmpeg not found` | Install FFmpeg (see above) and restart the app |
| `yt-dlp` errors | Run `pip install -U yt-dlp` to update to the latest version |
| Album tracks not found | Try adding the artist name, or check the spelling |
| Download fails for a track | The app will log the error and continue with the next track |
| App doesn't open | Make sure Python 3.8+ is installed and `customtkinter` is installed |

---

## Notes

- This tool downloads audio from **YouTube** — it does not connect to Spotify
- Tracklist lookup uses **Google Search** (no API key needed)
- For best results, use artist + album name together
- yt-dlp is kept up to date automatically by running `pip install -U yt-dlp` periodically
