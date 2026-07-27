# -*- coding: utf-8 -*-
"""Xiaohongshu (小红书) video downloader.
Usage: from xhs import download; download("http://xhslink.com/xxxx")
"""

import os, re, sys, json, time, requests
from tqdm import tqdm

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.xiaohongshu.com/",
}


def get_redirect_url(short_link):
    """Follow XHS short link redirect to get full URL"""
    try:
        r = requests.get(short_link, headers=HEADERS, allow_redirects=True, timeout=15)
        return r.url
    except Exception as e:
        print(f"[XHS] Redirect failed: {e}")
        return None


def extract_note_id(url):
    """Extract note_id from XHS URL"""
    patterns = [
        r"/discovery/item/([a-zA-Z0-9]+)",
        r"/explore/([a-zA-Z0-9]+)",
        r"note_id=([a-zA-Z0-9]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def _load_xhs_cookie():
    try:
        from cookies import load_cookie
        return load_cookie("xhs")
    except Exception:
        return None

def get_video_url(url):
    """Extract video URL from XHS page data"""
    note_id = extract_note_id(url)
    if not note_id:
        print("[XHS] Cannot extract note_id from URL")
        return None
    print(f"[XHS] Note ID: {note_id}")

    cookie = _load_xhs_cookie()
    h = dict(HEADERS)
    if cookie:
        h["Cookie"] = cookie
    try:
        r = requests.get(url, headers=h, timeout=15)
        if r.status_code != 200:
            print(f"[XHS] HTTP {r.status_code}")
            return None
    except Exception as e:
        print(f"[XHS] Request failed: {e}")
        return None

    # Try __INITIAL_STATE__ in script tag
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>", r.text, re.DOTALL)
    if not m:
        # Try replacing unicode escapes first
        text = r.text.replace("\\u002F", "/").replace("\\u003D", "=").replace("\\u0026", "&")
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>", text, re.DOTALL)

    if m:
        try:
            data_str = m.group(1)
            data_str = data_str.replace("undefined", "null")
            data = json.loads(data_str)
            note = data.get("note", {}).get("noteDetailMap", {}).get(note_id, {}).get("note", {})
            if not note:
                note = data.get("note", {}).get("noteDetailMap", {}).get(note_id, {}).get("note", {})
            # Try different paths to find video
            for path in [note, data.get("note", {})]:
                if not path:
                    continue
                video = path.get("video", {})
                media = video.get("media", {})
                stream = media.get("stream", {})
                for key in ("h264", "h265", "h266", "av1"):
                    master = stream.get(key, [])
                    if master:
                        return master[0].get("masterUrl", "")
                # Try different key structure
                for key in ("h264", "h265"):
                    streams = video.get(key, [])
                    if streams:
                        return streams[0].get("masterUrl", "")
                    streams = video.get("stream", {}).get(key, [])
                    if streams:
                        return streams[0].get("masterUrl", "")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[XHS] JSON parse failed: {e}")

    # Try video tag in HTML
    m = re.search(r'<video[^>]+src="([^"]+)"', r.text)
    if m:
        return m.group(1)

    # Try raw search for video URLs
    m = re.search(r'"masterUrl"\s*:\s*"([^"]+)"', r.text)
    if m:
        return m.group(1).replace("\\u002F", "/")

    print("[XHS] Could not find video URL in page")
    return None


def download_video(video_url, filename=None, output_dir=None):
    """Download video from URL"""
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    if filename is None:
        filename = f"xhs_{time.strftime('%Y%m%d_%H%M%S')}.mp4"

    headers = dict(HEADERS)
    headers["Referer"] = "https://www.xiaohongshu.com/"
    try:
        r = requests.get(video_url, headers=headers, stream=True, timeout=60)
        total = int(r.headers.get("Content-Length", 0))
        filepath = os.path.join(output_dir, filename)
        print(f"[XHS] Downloading ({total / 1024 / 1024:.1f} MB)...")
        with open(filepath, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="XHS") as bar:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        print(f"[XHS] Saved: {filepath}")
        return filepath
    except Exception as e:
        print(f"[XHS] Download failed: {e}")
        return None


def download(share_link, output_dir=None):
    """Main entry: download XHS video from share link"""
    print(f"[XHS] Input: {share_link}")
    url = share_link
    if "xhslink.com" in share_link or "xhslink" in share_link:
        url = get_redirect_url(share_link)
        if not url:
            return None
        print(f"[XHS] Redirect: {url}")
    video_url = get_video_url(url)
    if not video_url:
        return None
    print(f"[XHS] Video URL: {video_url[:80]}...")
    return download_video(video_url, output_dir=output_dir)


if __name__ == "__main__":
    link = sys.argv[1] if len(sys.argv) > 1 else input("XHS share link: ").strip()
    download(link)