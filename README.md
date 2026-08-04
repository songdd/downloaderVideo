# Multi-Platform Media Downloader

Video and audio downloader supporting 9 Chinese platforms, with optional Baidu Netdisk upload.

## Quick Start

```powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Download from URL

```powershell
python run.py <url>                    # Single item
python run.py --all <url>              # Batch: all episodes/tracks in album/season
python run.py --all --start-from 10 <url>   # Start from episode 10
python run.py --file urls.txt          # Batch from file (one URL per line, # for comments)
```

Files save to `output/`. Already-downloaded files are automatically skipped.

### Login (save cookies)

```powershell
python run.py -l <platform>            # Auto-extract from Chrome, or interactive window
python run.py -s                       # Show cookie status for all platforms
```

### Baidu Netdisk Upload

```powershell
# First time: authorize once
python upload_baidu.py --auth

# Upload after download
python run.py --upload-baidu <url>
python run.py --file urls.txt --upload-baidu

# Custom remote directory
python run.py --upload-baidu --baidu-dir "/music/排行榜" <url>
```

Credentials in `config.json`. Upload runs in background while downloading continues.

## Supported Platforms

| Platform | Module | Cookie | Batch | Special |
|----------|--------|--------|-------|---------|
| **Douyin** | `douyin_api.py` | Optional | None | Short link resolve |
| **Xiaohongshu** | `xhs.py` | Optional | None | `__INITIAL_STATE__` parse |
| **Kuaishou** | `ks_pw.py` / `ks.py` | Optional | None | Playwright primary, page scrape fallback |
| **Bilibili** | `bili.py` | Login for HD | Auto-detect season | 4K~360P, DASH merge, `--start-from` |
| **Youku** | `youku.py` | Required | None | Chrome/Firefox, JS inject |
| **Tencent** | `tencent.py` | Required | Playlist (`--login --playlist`) | HLS/m3u8 merge, auto-advance |
| **Dushu365** | `dushu.py` | Optional | Course (`--all`) | AES-256-ECB API, book+course audio |
| **Ximalaya** | `xm.py` | Optional | Album (`--all`) | Mobile API pagination, `--login` interactive |
| **NetEase Music** | `wangyiyun.py` | MUSIC_U for VIP | Auto for playlist/album/artist | Charts, discover, pagination |

## Platform Details

### Bilibili (哔哩哔哩)

```powershell
python run.py https://www.bilibili.com/video/BVxxxxxx
python run.py --all https://www.bilibili.com/bangumi/play/ep327107
python run.py --all --start-from 6 https://www.bilibili.com/bangumi/play/ep327339
```

Logged-in users get 1080P/4K. Multi-threaded (4 threads). DASH video+audio auto-merged.

### NetEase Music (网易云音乐)

```powershell
python run.py https://music.163.com/#/song?id=1210496        # Single song
python run.py https://music.163.com/#/playlist?id=8055396278  # Playlist (auto-batch)
python run.py https://music.163.com/#/album?id=123456         # Album (auto-batch)
python run.py https://music.163.com/#/artist?id=9712          # Artist hot songs (auto-batch)

# Browse
python run.py https://music.163.com/#/discover/toplist        # List all 63 charts
python run.py https://music.163.com/#/discover/playlist        # Discover playlists
python run.py https://music.163.com/#/discover/playlist --cat 古风 --page 2
```

Auto-detects playlist/album/artist and downloads all tracks. Output goes to named subdirectories (e.g., `output/热歌榜/`). VIP-only songs are skipped with a message.

### Ximalaya (喜马拉雅)

```powershell
python run.py 72982155                                         # Single track by ID
python run.py --all https://www.ximalaya.com/album/13396678    # Full album
python run.py --all --start-from 62 https://www.ximalaya.com/album/81107159
python run.py --login --all https://www.ximalaya.com/album/81107159  # Interactive login
```

Free tracks use direct API. `--login` opens visible Chrome for manual login (needed for paid tracks).

### Dushu365 (读书365 / 帆书)

```powershell
python run.py https://www.dushu365.com/book/400138922           # Single book
python run.py https://www.dushu365.com/course/400000044/200002994  # Course episode
python run.py --all https://www.dushu365.com/course/400000044/200002994  # All episodes
python dushu.py --list                                           # List available books
```

Pure SSR — no cookie needed. Course audio via AES-256-ECB encrypted Gateway API.

### Tencent Video (腾讯视频)

```powershell
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login
python run.py "https://v.qq.com/x/cover/xxx/xxx.html" --login --playlist
```

Opens visible Chrome for login. 2x playback collects TS segments, merged via ffmpeg.

## Common Flags

| Flag | Applies To | Description |
|------|-----------|-------------|
| `--all` | Bilibili, Dushu365, Ximalaya, NetEase | Download entire season/album/course/playlist |
| `--start-from N` | Bilibili, Ximalaya | Start downloading from episode N |
| `--login` | Tencent, Ximalaya | Interactive browser login |
| `--file path` | All | Batch download from URL list file |
| `--upload-baidu` | All | Upload files to Baidu Netdisk after download |
| `--baidu-dir path` | All | Custom Baidu Netdisk upload directory |
| `--cat name` | NetEase Music | Filter discover playlists by category |
| `--page N` | NetEase Music | Browse discover playlists page N |
| `-l <platform>` | All | Save login cookie for a platform |
| `-s` | All | Show cookie status |

## File Structure

```
downloaderVideo/
├── run.py              # Entry point — auto-detect platform
├── login.py            # Login helper (Chrome cookie DB + Playwright)
├── cookies.py          # Unified cookie storage
├── task_tracker.py     # Download task tracking + background Baidu upload
├── upload_baidu.py     # Baidu Netdisk OAuth + file upload
├── config.json         # Baidu cloud credentials
├── requirements.txt    # Python dependencies
├── platforms/          # Platform-specific downloaders
│   ├── bili.py         #   Bilibili
│   ├── douyin_api.py   #   Douyin
│   ├── dushu.py        #   Dushu365
│   ├── ks.py           #   Kuaishou (page scrape)
│   ├── ks_pw.py        #   Kuaishou (Playwright)
│   ├── tencent.py      #   Tencent Video
│   ├── wangyiyun.py    #   NetEase Music
│   ├── xhs.py          #   Xiaohongshu
│   ├── xm.py           #   Ximalaya
│   └── youku.py        #   Youku
├── cookies/            # Cookie JSON files per platform
├── output/             # Downloaded media
├── logs/               # Task logs (created by --upload-baidu)
└── tmp/                # Temporary browser profiles
```
