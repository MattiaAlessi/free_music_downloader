# 🎵 Music Downloader — Web UI

Interfaccia web stile Spotify per scaricare musica da YouTube, playlist e album.  
Backend Python (Flask) + Frontend HTML/CSS/JS moderno.

---

## Requisiti

- **Python 3.8+**
- **FFmpeg** installato nel sistema

### Installa FFmpeg

| OS | Comando |
|---|---|
| Windows | `winget install FFmpeg` |
| macOS | `brew install ffmpeg` |
| Linux | `sudo apt install ffmpeg` |

---

## Installazione

```bash
# 1. Clona o scarica il progetto
cd music_downloader

# 2. Installa le dipendenze Python
pip install -r requirements.txt
```

---

## Avvio

```bash
python app.py
```

Poi apri il browser su: **http://localhost:5000**

---

## Funzionalità

### 🎵 Singola canzone
- Cerca per nome (es. `Bohemian Rhapsody Queen`)
- Oppure incolla direttamente un URL YouTube

### 💿 Album completo
- Inserisci nome album + artista
- L'app cerca la tracklist su Google (Genius, Wikipedia, Discogs…)
- Conferma le tracce e avvia il download automatico

### 🔗 Playlist / URL diretto
- Incolla qualsiasi URL YouTube (playlist, canale, video singolo)
- Supporta anche SoundCloud, Bandcamp, Vimeo e altri siti yt-dlp

### 📊 Progresso
- Visualizzazione in tempo reale traccia per traccia
- Log dettagliato
- Statistiche successi/errori

---

## Cartella di download

Impostabile dall'interfaccia (campo in alto a destra).  
Default: `~/Desktop/Musica Scaricata`

Esempi:
- Windows: `C:\Users\Mattia\Music\Download`
- macOS/Linux: `/home/mattia/Musica`

---

## Struttura progetto

```
music_downloader/
├── app.py              # Backend Flask
├── requirements.txt    # Dipendenze Python
├── README.md
└── static/
    └── index.html      # Frontend (tutto in un file)
```
