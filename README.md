# Multi-Platform Media Downloader

Video and audio downloader supporting 8 Chinese platforms.

## Quick Start

```powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Download from URL

```powershell
python run.py <url>
```

The tool auto-detects the platform. Files are saved to `output/`.

### Batch download all episodes

```powershell
python run.py --all <url>           # All episodes in an album/season
python run.py --all --start-from 10 <url>  # Start from episode 10
```

Already-downloaded files are automatically skipped.

### Login (save cookies)

```powershell
python run.py -l bilibili           # Auto-extract from Chrome, or interactive window
python run.py -s                    # Show cookie status for all platforms
```

## Supported Platforms

| Platform | Module | Method | Cookie | Batch | Features |
|----------|--------|--------|--------|-------|----------|
| **Douyin** | `douyin_api.py` | API | Optional | None | Short link resolve, play URL extraction |
| **Xiaohongshu** | `xhs.py` | Page scrape | Optional | None | Short link redirect, `__INITIAL_STATE__` parse |
| **Kuaishou** | `ks_pw.py` / `ks.py` | Playwright / page scrape | Optional | None | Playwright intercept as primary, page scrape as fallback |
| **Bilibili** | `bili.py` | API + multi-thread | Login for HD | Season (`--all`) | 4K~360P auto-select, DASH audio merge, `--start-from` |
| **Youku** | `youku.py` | Playwright intercept | Required | None | Chrome/Firefox dual browser, JS inject extract |
| **Tencent** | `tencent.py` | Playwright + segment collect | Login recommended | Playlist (`--all --playlist`) | Interactive login, HLS/m3u8 merge, auto-advance detect |
| **Dushu365** | `dushu.py` | SSR parse + AES API | Optional | Course (`--all`) | Book & course audio, AES-256-ECB decryption |
| **Ximalaya** | `xm.py` | API + CDP fallback | Optional | Album (`--all`) | Mobile API pagination, redirect resolve, `--login` interactive |

## Platform Details

### Douyin (抖音)

```powershell
python run.py https://v.douyin.com/xxxx/
python run.py -l douyin              # First time: save login cookie
```

Cookie stored in `cookies/douyin.json` via unified `cookies.py`. Without cookie, video quality may be limited.

### Bilibili (哔哩哔哩)

```powershell
# Single video
python run.py https://www.bilibili.com/video/BVxxxxxx

# Full season (番剧)
python run.py --all https://www.bilibili.com/bangumi/play/ep327107

# Continue from episode 6
python run.py --all --start-from 6 https://www.bilibili.com/bangumi/play/ep327339
```

- Logged-in users get 1080P/4K; free users limited to 720P/480P
- Multi-threaded download (4 threads) with auto-retry
- DASH video+audio separated streams auto-merged via ffmpeg
- Cookie valid for months (`SESSDATA`)

### Dushu365 (读书365 / 帆书)

```powershell
# Single book audio
python run.py https://www.dushu365.com/book/400138922

# Single course episode
python run.py https://www.dushu365.com/course/400000044/200002994

# All episodes in a course
python run.py --all https://www.dushu365.com/course/400000044/200002994

# List all available books
python dushu.py --list
```

- Pure SSR page with `__NEXT_DATA__` JSON — no cookie needed
- Course audio via gateway API with AES-256-ECB encryption

### Ximalaya (喜马拉雅)

```powershell
# Single track by ID
python run.py 72982155

# Full album
python run.py --all https://www.ximalaya.com/album/13396678

# From episode N
python run.py --all --start-from 62 https://www.ximalaya.com/album/81107159

# Interactive login (for paid tracks, opens visible Chrome)
python run.py --login --all https://www.ximalaya.com/album/81107159
```

- Free tracks: direct API, no login needed
- Paid tracks: require `--login` mode (visible Chrome + manual login)
- Audio redirect URLs auto-resolved to real CDN addresses
- `--start-from` and skip-existing supported

### Tencent Video (腾讯视频)

```powershell
# Interactive login (recommended for VIP content)
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login

# Playlist mode
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login --playlist
```

- Opens visible Chrome for real session login
- 2x speed playback to collect TS segments, merged via ffmpeg
- Playlist mode detects episode auto-advance for sequential download

## File Structure

```
downloaderVideo/
├── run.py              # Entry point — auto-detect platform
├── login.py            # Login helper (Chrome cookie DB + Playwright fallback)
├── cookies.py          # Unified cookie storage (JSON files)
├── requirements.txt    # Python dependencies
├── platforms/          # Platform-specific downloaders
│   ├── bili.py         #   Bilibili
│   ├── douyin_api.py   #   Douyin
│   ├── xhs.py          #   Xiaohongshu
│   ├── ks.py           #   Kuaishou (page scrape)
│   ├── ks_pw.py        #   Kuaishou (Playwright)
│   ├── youku.py        #   Youku
│   ├── tencent.py      #   Tencent Video
│   ├── dushu.py        #   Dushu365 audio
│   └── xm.py           #   Ximalaya audio
├── cookies/            # Cookie JSON files per platform
├── output/             # Downloaded media
└── tmp/                # Temporary browser profiles
```

## Common Flags

| Flag | Description |
|------|-------------|
| `--all` | Download all episodes/tracks in album/season |
| `--start-from N` | Start downloading from episode N (Bilibili, Ximalaya) |
| `--login` | Interactive browser login (Tencent, Ximalaya) |
| `--list` | List available content (Dushu365) |
| `-l <platform>` | Save login cookie for a platform |
| `-s` | Show cookie status for all platforms |
