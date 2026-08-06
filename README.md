# Multi-Platform Media Downloader

Video and audio downloader supporting 9 Chinese platforms, with Web UI, cookie management, and Baidu Netdisk upload.

## Quick Start

``powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium
``

## Web UI (Recommended)

``powershell
python backend\webui.py
``

Opens at [http://localhost:5000](http://localhost:5000). Chrome auto-launches on startup.

### Tabs

| Tab | What it does |
|-----|-------------|
| **Download** | Paste URL → auto-detect platform → fetch metadata → download. Multi-P videos / albums auto-batch. Task cards with live progress, pause/resume, copy details. URL history saved locally (last 10). |
| **Login** | Cookie status table. One-click Chrome login per platform. Paste raw cookies from DevTools (auto-detects domain, filters to essential keys). Manual cookie string input. |

### Download Features

- Auto-detect platform from URL
- Pre-fetch metadata (title, episode count) before download starts
- Multi-P Bilibili videos download all parts into a named subdirectory
- Bilibili Wbi API signing (automatic key rotation)
- Ximalaya Login Mode: opens Chrome, wait for user to scan QR, confirm via UI button, then capture audio streams
- Task progress: real-time progress bar, pause/resume, cancel + clean up files
- Delete task: stops download, removes all files and auto-created directories

## CLI Usage

### Download

``powershell
python run.py <url>                        # Single item
python run.py --all <url>                  # Batch: all episodes in album/season
python run.py --all --start-from 10 <url>  # Start from episode 10
python run.py --file urls.txt              # Batch from file (one URL per line)
``

### Login

``powershell
python run.py -l <platform>    # Auto-extract from Chrome or interactive window
python run.py -s               # Show cookie status
``

### Baidu Netdisk

``powershell
python upload_baidu.py --auth                                         # One-time OAuth
python run.py --upload-baidu <url>                                    # Upload after download
python run.py --upload-baidu --baidu-dir "/music/排行榜" <url>         # Custom dir
``

## Supported Platforms

| Platform | Module | Cookie | Batch | Notes |
|----------|--------|--------|-------|-------|
| **Bilibili** | ili.py | HD/VIP | Auto multi-P & season | Wbi signed, DASH merge, 4K+, subdirectory output |
| **NetEase Music** | wangyiyun.py | MUSIC_U | Playlist/album/artist auto | Charts browser, discover, weapi AES |
| **Ximalaya** | xm.py | Paid tracks | Album (--all) | Login Mode for audio capture, mobile API pagination |
| **Dushu365** | dushu.py | No | Course (--all) | AES-256-ECB gateway API |
| **Douyin** | douyin_api.py | Optional | — | Short link resolve, dual API fallback |
| **Xiaohongshu** | xhs.py | Optional | — | __INITIAL_STATE__ parse |
| **Kuaishou** | ks_pw.py / ks.py | Optional | — | Playwright primary, page scrape fallback |
| **Youku** | youku.py | Required | — | Chrome/Firefox, JS inject |
| **Tencent** | 	encent.py | Required | — | HLS/m3u8 merge |

## File Structure

``
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
``

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
| DELETE | /api/task/:id | Delete task + files + directories |
| GET | /api/files | List downloaded files |
| GET | /api/cookies | Cookie status for all platforms |
| POST | /api/login | Trigger browser login |
| POST | /api/cookie-save | Save cookie string |
| POST | /api/urls | Parse URLs from text |
| POST | /api/upload-baidu | Upload selected files to Baidu |
