# -*- coding: utf-8 -*-
"""Kuaishou video downloader using Playwright headless browser.
Intercepts CDN video requests from the rendered page.
"""

import os, re, sys, time, requests
from tqdm import tqdm

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Referer": "https://www.kuaishou.com/",
}


def get_video_url(share_link):
    """Use Playwright to render Kuaishou page and capture video CDN URL"""
    print(f"[KS-PW] Opening: {share_link}")

    video_urls = []
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 390, "height": 844},
            )
            page = context.new_page()

            # Intercept network requests to find video URLs
            def on_response(response):
                url = response.url
                content_type = response.headers.get("content-type", "")
                if (
                    "video" in content_type
                    or ".mp4" in url
                    or "txmov2" in url
                    or "yximgs.com" in url
                    or "ks-cdn" in url.lower()
                ):
                    if url not in [v for v, _ in video_urls]:
                        cl = response.headers.get("content-length", "0")
                        try:
                            cl_int = int(cl)
                        except ValueError:
                            cl_int = 0
                        video_urls.append((url, cl_int))
                        print(f"[KS-PW] Captured: {url[:80]}... ({cl_int / 1024 / 1024:.1f} MB)")

            page.on("response", on_response)

            # Navigate to share link
            page.goto(share_link, wait_until="domcontentloaded", timeout=30000)

            # Wait for page to fully render and video requests to fire
            print("[KS-PW] Waiting for page to render...")
            page.wait_for_timeout(8000)  # Wait 8s for JS to load video

            # Try clicking play button if exists
            try:
                play_btn = page.query_selector('[class*="play"], [class*="video"], video, .player-btn')
                if play_btn:
                    play_btn.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            browser.close()
    except Exception as e:
        print(f"[KS-PW] Playwright error: {e}")
        return None

    if not video_urls:
        print("[KS-PW] No video URLs captured")
        return None

    # Pick the largest video (highest quality)
    video_urls.sort(key=lambda x: x[1], reverse=True)
    best_url, best_size = video_urls[0]
    print(f"[KS-PW] Selected: {best_url[:80]}... ({best_size / 1024 / 1024:.1f} MB)")
    return best_url


def download_video(video_url, filename=None, output_dir=None):
    """Download video from URL"""
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    filename = filename or f"ks_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    filepath = os.path.join(output_dir, filename)

    headers = dict(HEADERS)
    headers["Referer"] = "https://www.kuaishou.com/"
    try:
        r = requests.get(video_url, headers=headers, stream=True, timeout=120)
        total = int(r.headers.get("Content-Length", 0))
        print(f"[KS-PW] Downloading ({total / 1024 / 1024:.1f} MB)...")
        with open(filepath, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="KS") as bar:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        print(f"[KS-PW] Saved: {filepath}")
        return filepath
    except Exception as e:
        print(f"[KS-PW] Download failed: {e}")
        return None


def download(share_link, output_dir=None):
    """Main entry: download Kuaishou video using Playwright"""
    video_url = get_video_url(share_link)
    if not video_url:
        return None
    return download_video(video_url, output_dir=output_dir)


if __name__ == "__main__":
    link = sys.argv[1] if len(sys.argv) > 1 else input("KS share link: ").strip()
    download(link)