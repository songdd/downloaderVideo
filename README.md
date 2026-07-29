# Video Downloader - Multi-Platform

Batch video download tool supporting Douyin, Xiaohongshu, Kuaishou, Bilibili, Youku, and Tencent Video.

## Quick Start

```powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium    # needed for Kuaishou, Youku, Tencent
```

> Tencent Video also requires `ffmpeg` in `bin/ffmpeg.exe` (included).

## Usage

### Download a video

```powershell
python run.py "https://v.douyin.com/xxxx/"
python run.py "http://xhslink.com/xxxx"
python run.py "https://v.kuaishou.com/xxxx"
python run.py "https://b23.tv/xxxx"
python run.py "https://v.youku.com/v_show/id_XXXXX.html"
python run.py "https://v.qq.com/x/page/xxxxx.html"
```

The tool auto-detects the platform from the URL. Files are saved to `output/`.

### Login (save cookies)

```powershell
python run.py --login bilibili         # auto-extract from Chrome DB
python run.py --login bilibili --new   # interactive Chrome login window
python run.py --status                 # check all platform cookies
```

### Tencent Video - Interactive Login

Tencent Video uses interactive login via visible Chrome window for best quality.

```powershell
# Single episode download (interactive login)
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login

# Playlist mode: auto-download all episodes
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login --playlist

# Headless mode (no visible window)
python run.py "https://v.qq.com/x/page/xxx.html" --headless
```

**Interactive login flow:**

1. Open Chrome → login page → you log in (scan QR code or password)
2. Press Enter in terminal → auto-navigate to video page
3. Video plays at 2x speed → close browser when finished
4. Segments are collected and merged via ffmpeg

**Playlist mode (`--playlist`):**

- Detects when the video auto-advances to the next episode (URL change)
- Saves current episode, clears storage, reloads for fresh start
- Background thread downloads each episode as it's collected
- Close the browser to stop and download remaining episodes

## Supported Platforms

| Platform | Module | Method | Cookie | Quality |
|---|---|---|---|---|
| **Douyin** | `douyin_api.py` | API + Cookie | Required | Highest available |
| **Xiaohongshu** | `xhs.py` | Page scrape | Optional | Original |
| **Kuaishou** | `ks_pw.py` | Playwright intercept | Optional | Max captured |
| **Bilibili** | `bili.py` | API + multi-thread | Optional | 4K~360P auto-select |
| **Youku** | `youku.py` | Playwright intercept | Required | Intercepted stream |
| **Tencent Video** | `tencent.py` | Playwright + segment collection | Login recommended | Login: 1080P SDR via segment merge |

## File Structure

```
downloaderVideo/
├── run.py              # Entry point - auto-detect platform
├── run.bat             # Windows double-click launcher
├── login.py            # Login helper (Chrome cookie DB + Playwright)
├── cookies.py          # Unified cookie storage
├── requirements.txt    # Python dependencies
├── bin/
│   └── ffmpeg.exe      # ffmpeg for TS segment merging
├── cookies/            # Cookie JSON files
├── output/             # Downloaded videos
└── tmp/                # Browser profiles (auto-created)
```

## Tencent Video Features

- **Interactive login**: visible Chrome window for real session, no cookie injection needed
- **Playlist mode**: auto-detect episode changes, download entire season
- **Segment collection**: captures all TS segments during playback, merges with ffmpeg
- **Quality best-effort**: downloads at the quality set in the player
- **Resume position reset**: clears IndexedDB/localStorage to force start from beginning
- **Auto-advance detection**: monitors page URL changes to track episode transitions
- **Background download**: episodes are merged in background threads while next episode plays

## Installation

```powershell
pip install requests tqdm playwright
```

`playwright` is required for Kuaishou (`ks_pw.py`), Youku (`youku.py`), and Tencent Video (`tencent.py`).

## Notes

- **Douyin**: needs `account.json` in `cookies/`. Cookie expires ~1-3 months.
- **Kuaishou**: needs Playwright. The `ks.py` fallback (page scraping) is broken because Kuaishou uses CSR.
- **Bilibili**: free accounts limited to 360P/720P. Login unlocks 1080P/4K. SESSDATA cookie lasts months.
- **Youku**: needs Playwright + login cookie. DRM content (premium shows) cannot be downloaded.
- **Tencent Video**: requires Playwright + `bin/ffmpeg.exe`. Free content uses HLS direct download. VIP content requires `--login` for interactive segment collection. Speed is limited to real-time playback at 2x (wait time ~10 min per episode). Playlist mode `--playlist` can auto-collect consecutive episodes.