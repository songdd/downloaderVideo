# Video Downloader - Multi-Platform

Batch video download tool supporting Douyin, Xiaohongshu, Kuaishou, Bilibili, and Youku.

## Quick Start

```powershell
cd D:\code\downloaderVideo
pip install -r requirements.txt
playwright install chromium    # only needed for Kuaishou + Youku
```

## Usage

### Download a video

```powershell
python run.py "https://v.douyin.com/xxxx/"
python run.py "http://xhslink.com/xxxx"
python run.py "https://v.kuaishou.com/xxxx"
python run.py "https://b23.tv/xxxx"
python run.py "https://v.youku.com/v_show/id_XXXXX.html"
```

The tool auto-detects the platform from the URL. Files are saved to `output/`.

### Login (save cookies)

```powershell
python run.py --login bilibili         # auto-extract from Chrome DB
python run.py --login bilibili --new   # interactive Chrome login window
python run.py --status                 # check all platform cookies
```

## Supported Platforms

| Platform | Module | Method | Cookie | Quality |
|---|---|---|---|---|
| **Douyin** | `douyin_api.py` | API + Cookie | Required | Highest available |
| **Xiaohongshu** | `xhs.py` | Page scrape | Optional | Original |
| **Kuaishou** | `ks_pw.py` | Playwright intercept | Optional | Max captured |
| **Bilibili** | `bili.py` | API + multi-thread | Optional (higher quality with login) | 4K~360P auto-select |
| **Youku** | `youku.py` | Playwright intercept | Required | Intercepted stream |

## File Structure

```
downloaderVideo/
├── run.py              # Entry point - auto-detect platform
├── run.bat             # Windows double-click launcher
├── login.py            # Login helper (Chrome cookie DB + Playwright)
├── cookies.py          # Unified cookie storage
├── requirements.txt    # Python dependencies
├── cookies/            # Cookie JSON files
│   ├── account.json    # Douyin
│   ├── bilibili.json   # Bilibili
│   └── youku.json      # Youku
└── output/             # Downloaded videos
```

## Bilibili Features

- **Auto quality**: tries 4K > 1080P60 > 1080P > 720P > 360P, picks highest available
- **Season batch**: `ss` or multi-episode links auto-download all episodes to subfolder
- **Multi-threaded**: 4 concurrent threads via HTTP Range requests for large files
- **Cookie check**: validates login status and reports membership level

## Installation

```powershell
pip install requests tqdm playwright
```

`playwright` is only required for Kuaishou (`ks_pw.py`) and Youku (`youku.py`). Douyin, XHS, and Bilibili work with just `requests` + `tqdm`.

## Notes

- **Douyin**: needs `account.json` in `cookies/`. Cookie expires ~1-3 months.
- **Kuaishou**: needs Playwright. The `ks.py` fallback (page scraping) is broken because Kuaishou uses CSR.
- **Bilibili**: free accounts limited to 360P/720P. Login unlocks 1080P/4K. SESSDATA cookie lasts months.
- **Youku**: needs Playwright + login cookie. DRM content (premium shows) cannot be downloaded. Free accounts may only get preview clips.