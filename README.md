# Multi-Platform Media Downloader

Video and audio downloader supporting 9 Chinese platforms, with Web UI, cookie management, and Baidu Netdisk upload.

## Quick Start

```powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium
```

## Web UI (Recommended)

```powershell
python backend\webui.py
```

Opens at [http://localhost:5000](http://localhost:5000). Chrome auto-launches on startup.

### Tabs

| Tab | What it does |
|-----|-------------|
| **Download** | Paste URL → auto-detect platform → fetch metadata → download. Multi-P videos / albums auto-batch. Task cards with live progress, quality tag, CLI command, pause/resume/retry, copy details. URL history saved locally (last 10). |
| **Login** | Cookie status table. One-click Chrome login per platform. Paste raw cookies from DevTools (auto-detects domain, filters to essential keys). Manual cookie string input. |

### Download Features

- Auto-detect platform from URL
- Pre-fetch metadata (title, episode count) before download starts
- Multi-P Bilibili videos download all parts into a named subdirectory
- Bilibili single-episode seasons / movies download as a single file
- Bilibili Wbi API signing (automatic key rotation)
- Ximalaya Login Mode: opens Chrome, wait for user to scan QR, confirm via UI button, then capture audio streams
- Douyin short links: resolve to video ID, fetch play URL via aweme API (cookie optional)
- Kuaishou: Playwright captures the HLS playlist, bundled `bin/ffmpeg.exe` merges all segments into one mp4
- Task progress: real-time progress bar (byte-level for current file), pause/resume, cancel + clean up files
- Task card shows quality tag (e.g. [1080P]) and equivalent CLI command (click to copy)
- During retries the task card shows the last failure reason (e.g. `HTTP 403`, `invalid content`, `no audio captured`)
- Ximalaya retries use a per-track 24h budget with 30s->30min backoff; **Pause** takes effect immediately, even mid-wait
- **Retry** button on every task: reuses same task id, resumes from already-downloaded files (skips existing), preserves start_from/to/tracks
- Retry guard: prevents retrying a task that is already actively downloading
- To # / Tracks inputs: download a range or specific episodes (e.g. 3,5,10)
- Delete task: stops download, removes all files and auto-created directories

### Using the Web UI

1. Open http://localhost:5000, go to the **Download** tab.
2. Paste a URL into the top field. The platform is detected automatically and metadata (title, item count) is previewed below.
3. Optional filters (combine freely):
   - `All / Batch` checkbox: download every episode in the album/season.
   - `From #` + `To #`: download only episodes in that range (e.g. From 10, To 20).
   - `Tracks`: download specific episodes, comma separated (e.g. `3,5,10`).
   - `Login Mode` (Ximalaya): opens Chrome for QR login before capturing audio.
4. Click **Download**. A task card appears with a live progress bar, byte progress for the current file, quality tag, and the equivalent CLI command (click the dark command line to copy).
5. Task card actions: **Pause / Resume**, **Retry** (reuses the same task, skips already-downloaded files), **Copy** (details + CLI command + file list), **Delete** (stops and removes files).
6. The **Login** tab shows cookie status per platform. Use one-click Chrome login, or paste cookies from DevTools.

Progress is shown against the **effective** episode count after filters, not the full album size.

## CLI Usage

### Download

```powershell
python run.py <url>                        # Single item
python run.py --all <url>                  # Batch: all episodes in album/season
python run.py --all --start-from 10 <url>  # Start from episode 10
python run.py --all --to 50 <url>          # Download up to episode 50
python run.py --all --tracks 3,5,10 <url>  # Download only specific episodes
python run.py --file urls.txt              # Batch from file (one URL per line)
```

### Login

```powershell
python run.py -l <platform>    # Auto-extract from Chrome or interactive window
python run.py -s               # Show cookie status
```

### Baidu Netdisk

```powershell
python upload_baidu.py --auth                                         # One-time OAuth
python run.py --upload-baidu <url>                                    # Upload after download
python run.py --upload-baidu --baidu-dir "/music/排行榜" <url>         # Custom dir
```

> **Credentials:** copy `config.example.json` to `config.json` and fill in your
> Baidu app credentials (run `python upload_baidu.py --auth` to obtain tokens).
> `config.json` holds live access/refresh tokens and is **gitignored** — never
> commit it. If it was ever exposed, revoke & re-authorize.

## Supported Platforms

| Platform | Module | Cookie | Batch | Notes |
|----------|--------|--------|-------|-------|
| **Bilibili** | bili.py | HD/VIP | Auto multi-P & season | Wbi signed, DASH merge, 4K+, multi-P / single-episode season output |
| **NetEase Music** | wangyiyun.py | MUSIC_U | Playlist/album/artist auto | Charts browser, discover, weapi AES |
| **Ximalaya** | xm.py | Paid tracks | Album (--all) | Login Mode for audio capture, mobile API pagination, auto retry with backoff (30s->30min, 24h cap), audio content validation (rejects JS/font error payloads) |
| **Dushu365** | dushu.py | No | Course (--all) | AES-256-ECB gateway API |
| **Douyin** | douyin_api.py | Optional | — | Short link resolve, aweme API (Web UI + CLI) |
| **Xiaohongshu** | xhs.py | Optional | — | __INITIAL_STATE__ parse |
| **Kuaishou** | ks_pw.py / ks.py | Optional | — | Playwright HLS capture + ffmpeg merge, page scrape fallback (Web UI + CLI) |
| **Youku** | youku.py | Required | — | Chrome/Firefox, JS inject |
| **Tencent** | tencent.py | Required | — | HLS/m3u8 merge |

## File Structure

```
downloaderVideo/
├── run.py                  # CLI entry point
├── backend/
│   └── webui.py            # Flask Web UI + REST API
├── frontend/
│   └── templates/
│       ├── base.html       # Shared layout + nav + CSS
│       ├── download.html   # Download tab
│       └── login.html      # Login tab
├── login.py                # Chrome cookie DB + Playwright login
├── cookies.py              # Unified cookie storage (cookies/*.json)
├── task_tracker.py         # Download tracking + background Baidu upload
├── upload_baidu.py         # Baidu Netdisk OAuth + file upload (small + chunked)
├── config.json             # Baidu cloud credentials
├── requirements.txt
├── platforms/
│   ├── bili.py             # Bilibili
│   ├── douyin_api.py       # Douyin
│   ├── dushu.py            # Dushu365
│   ├── ks.py / ks_pw.py    # Kuaishou
│   ├── tencent.py          # Tencent Video
│   ├── wangyiyun.py        # NetEase Music
│   ├── xhs.py              # Xiaohongshu
│   ├── xm.py               # Ximalaya
│   └── youku.py            # Youku
├── cookies/                # Per-platform cookie JSON files
├── output/                 # Downloaded media
├── logs/                   # Task logs
└── tmp/                    # Temporary browser profiles
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | / | Download page |
| GET | /login | Login page |
| GET | /api/ping | Health check + version |
| POST | /api/info | Fetch URL metadata (title, count) |
| POST | /api/download | Start download task |
| GET | /api/tasks | List all tasks |
| GET | /api/task/:id | Get task status |
| POST | /api/task/:id/pause | Pause task |
| POST | /api/task/:id/resume | Resume task |
| POST | /api/task/:id/login-confirm | Confirm interactive login |
| POST | /api/task/:id/retry | Retry task (same id, skips already-downloaded files) |
| DELETE | /api/task/:id | Delete task + files + directories |
| GET | /api/files | List downloaded files |
| GET | /api/cookies | Cookie status for all platforms |
| POST | /api/login | Trigger browser login |
| POST | /api/cookie-save | Save cookie string |
| POST | /api/urls | Parse URLs from text |
| POST | /api/upload-baidu | Upload selected files to Baidu |
