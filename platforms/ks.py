# -*- coding: utf-8 -*-
"""Kuaishou (快手) video downloader.
Usage: from ks import download; download("https://v.kuaishou.com/xxxx")
"""

import os, re, sys, json, time, requests
from tqdm import tqdm

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Referer": "https://www.kuaishou.com/",
}


def _load_ks_cookie():
    try:
        from cookies import load_cookie
        return load_cookie("kuaishou")
    except Exception:
        return None

def get_video_url(share_link):
    """Extract video URL from Kuaishou share link"""
    print(f"[KS] Input: {share_link}")

    # Step 1: Follow short link redirect
    try:
        cookie = _load_ks_cookie()
        h = dict(HEADERS)
        if cookie:
            h["Cookie"] = cookie
        r = requests.get(share_link, headers=h, allow_redirects=True, timeout=15)
        url = r.url
        print(f"[KS] Redirect: {url}")
    except Exception as e:
        print(f"[KS] Redirect failed: {e}")
        return None

    # Step 2: Extract photo/video ID
    patterns = [
        r"/short-video/([a-zA-Z0-9]+)",
        r"/fw/photo/([a-zA-Z0-9]+)",
        r"videoId=([a-zA-Z0-9]+)",
        r"photoId=([a-zA-Z0-9]+)",
    ]
    video_id = None
    for p in patterns:
        m = re.search(p, url)
        if m:
            video_id = m.group(1)
            break

    if not video_id:
        # Try from the original share link path
        m = re.search(r"v\.kuaishou\.com/([a-zA-Z0-9]+)", share_link)
        if m:
            video_id = m.group(1)
    if not video_id:
        print("[KS] Cannot extract video ID")
        return None
    print(f"[KS] Video ID: {video_id}")

    # Step 3: Try page scraping
    try:
        mobile_url = f"https://www.kuaishou.com/short-video/{video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        }
        r = requests.get(mobile_url, headers=headers, timeout=15)
        if r.status_code == 200:
            text = r.text

            # Try __INITIAL_STATE__ or __NEXT_DATA__ in page
            m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>", text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1).replace("undefined", "null"))
                    # Navigate nested structure to find video URL
                    photo = data.get("video", {}).get("info", {})
                    if not photo:
                        photo = data.get("photo", {}).get("info", {})
                    urls = []
                    if isinstance(photo, dict):
                        urls.append(photo.get("photoUrl", ""))
                        urls.append(photo.get("videoUrl", ""))
                        urls.append(photo.get("srcNoMark", ""))
                        urls.append(photo.get("src", ""))
                    for u in urls:
                        if u and u.startswith("http"):
                            return u
                except (json.JSONDecodeError, TypeError):
                    pass

            # Try regex for video URLs directly
            patterns = [
                r'"photoUrl"\s*:\s*"([^"]+)"',
                r'"srcNoMark"\s*:\s*"([^"]+)"',
                r'"src"\s*:\s*"([^"]+)"',
                r'<source\s+src="([^"]+)"',
                r'<video[^>]+src="([^"]+)"',
            ]
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    raw = m.group(1).replace("\\u002F", "/")
                    if raw.startswith("http"):
                        return raw
    except Exception as e:
        print(f"[KS] Page scraping failed: {e}")

    print("[KS] Page is React SSR - needs browser rendering. Try a video share link instead of photo.")
    return None
    return None


def download_video(video_url, filename=None, output_dir=None):
    """Download video from URL"""
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(output_dir, exist_ok=True)

    if filename is None:
        filename = f"ks_{time.strftime('%Y%m%d_%H%M%S')}.mp4"

    headers = dict(HEADERS)
    headers["Referer"] = "https://www.kuaishou.com/"
    try:
        r = requests.get(video_url, headers=headers, stream=True, timeout=60)
        total = int(r.headers.get("Content-Length", 0))
        filepath = os.path.join(output_dir, filename)
        print(f"[KS] Downloading ({total / 1024 / 1024:.1f} MB)...")
        with open(filepath, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="KS") as bar:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        print(f"[KS] Saved: {filepath}")
        return filepath
    except Exception as e:
        print(f"[KS] Download failed: {e}")
        return None


def download(share_link, output_dir=None):
    """Main entry: download Kuaishou video from share link"""
    video_url = get_video_url(share_link)
    if not video_url:
        return None
    print(f"[KS] Video URL: {video_url[:80]}...")
    return download_video(video_url, output_dir=output_dir)


if __name__ == "__main__":
    link = sys.argv[1] if len(sys.argv) > 1 else input("KS share link: ").strip()
    download(link)