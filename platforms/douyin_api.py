# -*- coding: utf-8 -*-
"""Douyin (抖音) video downloader.

Flow:
  1. Resolve short link (v.douyin.com/xxx) -> video modal_id
  2. Get play URL: try the public web APIs first (fast path, no browser).
     Douyin's risk control frequently blocks plain requests (empty API
     responses, slider captcha middle page, CDN 403). When that happens,
     fall back to a real browser (Playwright) which executes the JS
     signing (a_bogus / msToken / ttwid) and can surface the slider
     captcha for manual completion. Browser cookies are saved so the
     final CDN download is accepted.
  3. Download via requests with a full browser User-Agent + saved cookies.
"""

import os, re, sys, time, requests
from tqdm import tqdm

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_DIR = os.path.join(ROOT, "output")

FULL_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

MEDIA_URL_RE = re.compile(r"\.(mp4|m3u8)(\?|$)|/video/tos/", re.I)
MEDIA_HOST_RE = re.compile(r"(365yg\.com|douyinvod\.com|bytecdn\.cn|zjcdn\.com|ixigua\.com|douyin\.com/video/tos)", re.I)
VIDEO_CT = ("video", "mp4", "mpeg")


def sanitize_filename(title):
    return re.sub(r'[<>:"/\\|?*]', "_", str(title or "douyin"))[:80].strip(" _") or "douyin"


def _load_cookie():
    try:
        from cookies import load_cookie
        return load_cookie("douyin") or ""
    except Exception:
        return ""


def _save_cookie(cookie_str):
    try:
        from cookies import save_cookie
        save_cookie("douyin", cookie_str)
    except Exception:
        pass


def _headers(referer=None, cookie_str=None):
    h = {"User-Agent": FULL_UA, "Referer": referer or "https://www.douyin.com/"}
    if cookie_str:
        h["Cookie"] = cookie_str
    return h


def download_video(url, title, cookie_str=None, referer=None):
    """Download the video stream to output/douyin_<timestamp>.mp4."""
    if referer is None:
        m = re.search(r"/video/(\d+)", url or "")
        referer = "https://www.douyin.com/video/%s" % m.group(1) if m else "https://www.douyin.com/"
    if cookie_str is None:
        cookie_str = _load_cookie()
    headers = _headers(referer=referer, cookie_str=cookie_str)
    r = requests.get(url, headers=headers, stream=True, timeout=(30, 300))
    cl = r.headers.get('Content-Length', '?')
    print('[DOWNLOAD] HTTP %s, Content-Length: %s' % (r.status_code, cl))
    os.makedirs(VIDEO_DIR, exist_ok=True)
    if r.status_code != 200:
        print('[DOWNLOAD] Failed: HTTP %s (CDN rejected the request; retry once browser cookies are saved)' % r.status_code)
        return None
    total = int(r.headers.get('Content-Length', 0) or 0)
    video_path = os.path.join(VIDEO_DIR, 'douyin_%s.mp4' % time.strftime("%Y%m%d_%H%M%S"))
    with open(video_path, 'wb') as f:
        with tqdm(total=total, unit='B', unit_scale=True, desc='Download') as bar:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    if os.path.getsize(video_path) == 0:
        print('[DOWNLOAD] Empty file, failed')
        try:
            os.remove(video_path)
        except Exception:
            pass
        return None
    print('[DOWNLOAD] Saved: %s (%d bytes)' % (video_path, os.path.getsize(video_path)))
    return video_path


def _api_get_play_url(modal_id, cookie_str):
    """Try the public web APIs. Returns play URL or None."""
    apis = [
        ('iesdouyin', 'https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=%s' % modal_id),
        ('aweme', 'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=%s' % modal_id),
    ]
    for name, api_url in apis:
        print('[API] Trying %s' % name)
        try:
            r = requests.get(api_url, headers=_headers(cookie_str=cookie_str), timeout=15)
            print('[API] Status: %s (len=%s)' % (r.status_code, len(r.text)))
            if r.status_code != 200 or len(r.text) < 50:
                continue
            data = r.json()
            items = data.get('item_list') or [data.get('aweme_detail')]
            for item in items:
                if not item:
                    continue
                video = item.get('video', {})
                for addr_key in ('play_addr', 'play_addr_h264', 'download_addr'):
                    addr = video.get(addr_key, {})
                    urls = addr.get('url_list', [])
                    if isinstance(urls, str):
                        urls = [urls]
                    for u in urls:
                        u = u.replace('playwm', 'play')
                        if u.startswith('http'):
                            print('[API] Got URL from %s: %s...' % (name, u[:80]))
                            return u
            print('[API] %s: no playable URL' % name)
        except Exception as e:
            print('[API] %s failed: %s' % (name, e))
    print('[FATAL] All APIs failed')
    return None


def _verify_play_url(url, cookie_str):
    """Confirm the CDN accepts a candidate URL before we commit to it."""
    h = _headers(cookie_str=cookie_str)
    try:
        r = requests.head(url, headers=h, timeout=15)
        if r.status_code in (200, 206):
            return True
    except Exception:
        pass
    try:
        h2 = dict(h)
        h2["Range"] = "bytes=0-0"
        r = requests.get(url, headers=h2, timeout=15)
        if r.status_code in (200, 206):
            return True
    except Exception:
        pass
    return False


def _browser_capture(modal_id, headless=True):
    """Open the video page in a real browser and capture the CDN play URL.

    Douyin's JS signing runs in the browser, so this bypasses the risk
    control that blocks plain requests. If a slider captcha appears, the
    headful retry lets the user complete it manually.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[DOUYIN] Playwright not installed (pip install playwright) - cannot bypass douyin risk control')
        return None

    video_url = 'https://www.douyin.com/video/' + modal_id
    profile = os.path.join(ROOT, 'tmp', 'douyin_profile')
    os.makedirs(profile, exist_ok=True)
    captured = {}

    def on_response(resp):
        try:
            u = resp.url
            ct = (resp.headers.get('content-type') or '').lower()
            if (u.startswith('http') and
                    (MEDIA_URL_RE.search(u.split('?')[0]) or any(k in ct for k in VIDEO_CT) or MEDIA_HOST_RE.search(u))):
                try:
                    cl = int(resp.headers.get('content-length') or 0)
                except Exception:
                    cl = 0
                captured.setdefault(u, cl)
                print('[CAPTURE] %s... (%d KB)' % (u[:90], cl // 1024), flush=True)
        except Exception:
            pass

    def run_once(headless):
        captured.clear()
        browser = None
        ctx = None
        with sync_playwright() as p:
            try:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=profile, headless=headless, channel='chrome',
                    args=['--disable-blink-features=AutomationControlled', '--no-first-run',
                          '--disable-infobars', '--disable-dev-shm-usage', '--disable-gpu'],
                    ignore_default_args=['--enable-automation'],
                    viewport={'width': 1280, 'height': 800})
            except Exception as e:
                print('[DOUYIN] persistent context failed (%s), using regular launch' % str(e)[:60], flush=True)
                browser = p.chromium.launch(headless=headless, channel='chrome',
                                            args=['--disable-blink-features=AutomationControlled', '--no-sandbox'])
                ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
            try:
                page = ctx.new_page()
                page.on('response', on_response)
                print('[DOUYIN] Opening %s (headless=%s)...' % (video_url, headless), flush=True)
                page.goto(video_url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(3000)
                # Force the <video> element to start so the CDN request is made
                try:
                    page.evaluate('''() => {
                        var v = document.querySelector('video');
                        if (v) { v.muted = true; v.play().catch(function(){}); }
                        var s = document.querySelector('video source');
                        return s ? s.src : null;
                    }''')
                except Exception:
                    pass
                js_url = None
                deadline = time.time() + (12 if headless else 30)
                while time.time() < deadline:
                    page.wait_for_timeout(2000)
                    try:
                        js_url = page.evaluate('''() => {
                            var v = document.querySelector('video');
                            if (v && v.currentSrc) return v.currentSrc;
                            var s = document.querySelector('video source');
                            return s ? s.src : null;
                        }''')
                        if js_url and js_url.startswith('http'):
                            print('[DOUYIN] video src: %s...' % js_url[:90], flush=True)
                            break
                    except Exception:
                        pass
                    if captured:
                        print('[DOUYIN] captured %d media responses' % len(captured), flush=True)
                        break
                # Save browser cookies so the CDN download (requests) is accepted
                ck_str = ""
                try:
                    cks = ['%s=%s' % (c['name'], c['value']) for c in ctx.cookies() if 'douyin' in c.get('domain', '')]
                    if cks:
                        ck_str = '; '.join(cks)
                        _save_cookie(ck_str)
                        print('[DOUYIN] saved %d browser cookies for CDN download' % len(cks), flush=True)
                except Exception:
                    pass
                # Prefer URLs on the real video CDN (douyinvod/365yg/...) over
                # static app assets (douyinstatic etc.), and verify reachability.
                best = None
                if captured:
                    vhost = {u: cl for u, cl in captured.items() if MEDIA_HOST_RE.search(u)}
                    other = {u: cl for u, cl in captured.items() if u not in vhost}
                    for pool in (vhost, other):
                        pos = [(u, cl) for u, cl in pool.items() if cl > 0]
                        cands = [u for u, _ in sorted(pos, key=lambda kv: -kv[1])] or list(pool)
                        for u in cands:
                            if _verify_play_url(u, ck_str):
                                best = u
                                print('[DOUYIN] verified play URL: %s...' % u[:90], flush=True)
                                break
                        if best:
                            break
                return best
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    for hd, label in ((headless, 'headless'), (not headless, 'visible')):
        try:
            best = run_once(hd)
        except Exception as e:
            print('[DOUYIN] browser error (%s): %s' % (label, str(e)[:100]), flush=True)
            best = None
        if best:
            print('[DOUYIN] final play URL: %s...' % best[:90], flush=True)
            return best
        if not hd:
            print('[DOUYIN] headless failed, opening a visible window - complete the slider captcha if shown', flush=True)
    print('[DOUYIN] browser capture failed - open the video in Chrome and save cookies via the Login tab', flush=True)
    return None


def get_video_url(url, headless=True):
    """Get the play URL for a douyin page URL (user/self?modal_id=... or /video/<id>)."""
    m = re.search(r'modal_id=(\d+)', url or '')
    if not m:
        m = re.search(r'/video/(\d+)', url or '')
    if not m:
        print('[ERROR] Cannot extract video ID from: %s' % (url or ''))
        return None
    modal_id = m.group(1)
    cookie_str = _load_cookie()
    play = _api_get_play_url(modal_id, cookie_str)
    if play:
        return play
    print('[DOUYIN] APIs blocked by risk control, trying real browser...')
    return _browser_capture(modal_id, headless=headless)


def get_modalid_from_share_link(share_link):
    """Resolve a v.douyin.com short link (or direct /video/<id> link) to the video id."""
    m = re.search(r'https://v\.douyin\.com/[\w\-]+/?', share_link)
    if not m:
        m2 = re.search(r'/video/(\d+)', share_link)
        if m2:
            print('[STEP1] modal_id=%s (direct link)' % m2.group(1))
            return m2.group(1), share_link
        print('[STEP1] Invalid share link format')
        return None, None
    url = m.group()
    try:
        r = requests.get(url, headers=_headers(), allow_redirects=True, timeout=20)
        mm = re.search(r'https://www\.douyin\.com/video/(\d+)', r.url)
        if mm:
            modal_id = mm.group(1)
            print('[STEP1] modal_id=%s' % modal_id)
            return modal_id, r.url
        print('[STEP1] Redirect failed: %s' % r.url)
        return None, None
    except Exception as e:
        print('[STEP1] Request failed: %s' % e)
        return None, None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python douyin_api.py <douyin_share_link>')
        sys.exit(1)
    share_link = sys.argv[1]
    modal_id, video_url = get_modalid_from_share_link(share_link)
    if not modal_id:
        print('Invalid share link')
    else:
        page_url = 'https://www.douyin.com/user/self?showTab=post&modal_id=%s' % modal_id
        play_url = get_video_url(page_url)
        if play_url:
            download_video(play_url, play_url.split('/')[-1])
        else:
            print('Failed: could not extract play URL')
    sys.exit(0)
