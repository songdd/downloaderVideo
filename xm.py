import os, re, sys, json, time, requests
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
CHROME_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA",""), "Google", "Chrome", "User Data")
USE_CHROME = "--use-chrome" in sys.argv
_CHROME_LOCKED = False
_PW_FAIL_COUNT = 0
_MAX_PW_FAIL = 3

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "Referer": "https://www.ximalaya.com/"}

def load_cookie():
    try:
        p = os.path.join(ROOT, "cookies", "ximalaya.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f).get("cookie", "")
    except Exception:
        pass
    return ""

_COOKIE = load_cookie()
if _COOKIE:
    H["Cookie"] = _COOKIE

def parse_url(url):
    """Parse Ximalaya URL. Returns (type, id1, id2) or None."""
    m = re.search(r"/album/(\d+)", url)
    if m:
        # Check for /album/ID/sound/TRACKID
        m2 = re.search(r"/album/\d+/sound/(\d+)", url)
        if m2:
            return ("track", m.group(1), m2.group(1))
        return ("album", m.group(1))
    m = re.search(r"/sound/(\d+)", url)
    if m:
        return ("track", None, m.group(1))
    # Try just a plain ID
    m = re.search(r"^(\d+)$", url.strip())
    if m:
        return ("track", None, m.group(1))
    return None



def _pw_get_paid_audio(track_id):
    """Use CDP to connect to running Chrome and get paid track audio URL."""
    global _CHROME_LOCKED, _PW_FAIL_COUNT
    if _CHROME_LOCKED or _PW_FAIL_COUNT >= _MAX_PW_FAIL:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            if browser.contexts:
                ctx = browser.contexts[0]
            else:
                ctx = browser.new_context()
            page = ctx.new_page()
            audio_urls = []
            def on_req(req):
                url = req.url
                if "xmcdn.com" in url and (".m4a" in url or ".mp3" in url or ".aac" in url):
                    audio_urls.append(url)
            page.on("request", on_req)
            page.goto("https://www.ximalaya.com/sound/" + str(track_id),
                      wait_until="load", timeout=20000)
            page.wait_for_timeout(6000)
            try:
                page.evaluate("""() => {
                    var b = document.querySelector('[class*="play"]') || document.querySelector("button");
                    if (b) b.click();
                }""")
                page.wait_for_timeout(5000)
            except:
                pass
            page.close()
            return audio_urls[0] if audio_urls else None
    except Exception as e:
        msg = str(e).lower()
        if "econnrefused" in msg or "connect" in msg:
            _CHROME_LOCKED = True
            _PW_FAIL_COUNT = _MAX_PW_FAIL
            print("[XM] Cannot connect to Chrome. Start Chrome with --remote-debugging-port=9222.")
        elif "target closed" in msg or "browser closed" in msg:
            _CHROME_LOCKED = True
            _PW_FAIL_COUNT = _MAX_PW_FAIL
            print("[XM] Chrome closed. Reopen with --remote-debugging-port=9222.")
        else:
            _PW_FAIL_COUNT += 1
            if _PW_FAIL_COUNT >= _MAX_PW_FAIL:
                print("[XM] CDP failed repeatedly, skipping remaining paid tracks.")
            else:
                print("[XM] CDP error: " + str(e)[:80])
        return None


def get_album_tracks(album_id, page_size=30):
    """Get ALL tracks from an album using mobile API with pageId pagination."""
    tracks = []
    seen = set()
    page_id = 1
    while True:
        url = f"https://mobile.ximalaya.com/mobile/v1/album/track?albumId={album_id}&pageId={page_id}&pageSize={page_size}"
        try:
            r = requests.get(url, headers=H, timeout=30)
            data = r.json()
            if data.get("ret") != 0:
                break
            d = data.get("data", {})
            page_tracks = d.get("list", [])
            if not page_tracks:
                break
            for t in page_tracks:
                tid = str(t.get("trackId", ""))
                if tid and tid not in seen:
                    seen.add(tid)
                    tracks.append({
                        "track_id": tid,
                        "title": t.get("title", ""),
                        "index": t.get("orderNo", 0),
                        "duration": t.get("duration", 0),
                    })
            max_page = d.get("maxPageId", 1)
            if page_id >= max_page:
                break
            page_id += 1
            time.sleep(5.0)
        except Exception as e:
            print(f"[XM] Album API error: {e}")
            break
    return tracks

def get_track_info(track_id):
    """Get track audio URL and metadata. Resolves redirect to real CDN URL."""
    url = f"https://mobile.ximalaya.com/mobile/v1/track/baseInfo?trackId={track_id}"
    try:
        r = requests.get(url, headers=H, timeout=30)
        data = r.json()
        if data.get("ret") != 0:
            print(f"[XM] Track API error: {data.get('msg','')}")
            return None
        # Pick best quality audio (may be a redirect URL)
        redir = (data.get("playPathAacv224") or data.get("playUrl64") or
                 data.get("playPathAacv164") or data.get("playUrl32") or "")
        if not redir:
            if data.get("isPaid") and USE_CHROME:
                pw_url = _pw_get_paid_audio(track_id)
                if pw_url:
                    return {"track_id": track_id, "title": data.get("title",""), "paid": True,
                            "album_title": data.get("albumTitle",""), "duration": data.get("duration",0),
                            "audio_url": pw_url, "ext": ".m4a"}
            if data.get("isPaid"):
                return {"track_id": track_id, "title": data.get("title",""), "paid": True,
                        "album_title": data.get("albumTitle",""), "duration": data.get("duration",0),
                        "audio_url": "", "ext": ""}
            return None
        # Resolve redirect to get real CDN URL
        real_url = redir
        real_ext = ""
        if redir and "redirect" in redir:
            try:
                rh = requests.head(redir, headers=H, allow_redirects=True, timeout=15)
                real_url = rh.url
                ct = rh.headers.get("content-type", "")
                if ".m4a" in real_url or "m4a" in ct: real_ext = ".m4a"
                elif ".mp3" in real_url or "mpeg" in ct: real_ext = ".mp3"
                elif ".aac" in real_url or "aac" in ct: real_ext = ".aac"
            except Exception as e:
                print(f"[XM] Redirect resolve failed: {e}")
        return {
            "track_id": track_id,
            "title": data.get("title", ""),
            "album_title": data.get("albumTitle", ""),
            "duration": data.get("duration", 0),
            "audio_url": real_url,
            "ext": real_ext,
            "paid": data.get("isPaid", False),
            "play_url64": data.get("playUrl64", ""),
            "play_url32": data.get("playUrl32", ""),
        }
    except Exception as e:
        print(f"[XM] Track API error: {e}")
        return None

def download_audio(media_url, filename, output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    fp = os.path.join(output_dir, filename)
    headers = dict(H)
    try:
        r = requests.get(media_url, headers=headers, stream=True, timeout=120)
        total = int(r.headers.get("Content-Length", 0))
        if total > 0: print("[XM] Downloading (" + str(round(total/1024/1024,1)) + " MB)...")
        else: print("[XM] Downloading (size unknown)...")
        with open(fp, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="XM") as bar:
                for chunk in r.iter_content(1024*1024):
                    if chunk: f.write(chunk); bar.update(len(chunk))
        actual = os.path.getsize(fp)
        print("[XM] Saved: " + fp + " (" + str(round(actual/1024/1024,1)) + " MB)")
        return fp
    except Exception as e:
        print("[XM] Download failed: " + str(e))
        try: os.remove(fp)
        except: pass
        return None

def download(link, output_dir=None, download_all=False, start_from=1):
    print("[XM] Input: " + link)
    parsed = parse_url(link)
    if not parsed:
        # Try plain track ID
        if link.strip().isdigit():
            parsed = ("track", None, link.strip())
        else:
            print("[XM] Cannot parse URL")
            return None

    ptype = parsed[0]
    safe_fn = lambda s: re.sub(r"""[<>:"/\\|?*]""", "_", s)[:60].strip(" _")
    ts = time.strftime("%Y%m%d_%H%M%S")

    if ptype == "album" or (ptype == "track" and download_all and parsed[1]):
        # Album / batch mode
        album_id = parsed[1] if parsed[1] else parsed[2]
        if ptype == "track" and download_all and parsed[1]:
            album_id = parsed[1]

        print("[XM] Fetching album tracks...")
        tracks = get_album_tracks(album_id)
        if not tracks:
            print("[XM] No tracks found")
            return None

        total = len(tracks)
        print(f"[XM] Found {total} tracks:")
        for t in tracks[:5]:
            print(f"  [{t['index']}] {t['title'][:50]} ({t['duration']}s)")
        if total > 5:
            print(f"  ... and {total - 5} more")

        results = []
        skipped_existing = 0
        for i, t in enumerate(tracks):
            if i + 1 < start_from:
                continue
            # Check if already downloaded
            safe = lambda s: "".join(c2 if c2.isalnum() or c2 in " .-_" else "_" for c2 in s)[:50].strip(" _")
            out_dir = output_dir or os.path.join(ROOT, "output")
            existing = [f for f in (os.listdir(out_dir) if os.path.exists(out_dir) else []) if safe(t["title"])[:30] in f]
            if existing:
                skipped_existing += 1
                continue
            print(f"\n[XM] [{i+1}/{total}] Track {t['track_id']}: {t['title'][:40]}")
            info = get_track_info(t["track_id"])
            if not info:
                results.append(None)
                continue
            if not info.get("audio_url"):
                if info.get("paid"):
                    print("[XM]   (paid track, skipping)")
                results.append(None)
                continue
            ext = info.get("ext", "")
            if not ext:
                au = info.get("audio_url", "")
                for known in [".m4a", ".mp3", ".aac"]:
                    if known in au.split("?")[0]:
                        ext = known; break
                if not ext: ext = ".m4a"
            fn = "xm_" + safe_fn(info["title"]) + "_" + ts + ext
            results.append(download_audio(info["audio_url"], fn, output_dir))
            if i < total - 1:
                time.sleep(10)
        ok = sum(1 for r in results if r)
        msg = f"\n[XM] Done: {ok}/{total} downloaded"
        if skipped_existing > 0:
            msg += f", {skipped_existing} already existed"
        print(msg)
        return results

    else:
        # Single track
        track_id = parsed[2]
        print("[XM] Track ID: " + track_id)
        info = get_track_info(track_id)
        if not info:
            return None
        print("[XM] Title: " + info["title"])
        print("[XM] Album: " + info["album_title"])
        print("[XM] Duration: " + str(info["duration"]) + "s")
        ext = info.get("ext", "")
        if not ext:
            au = info.get("audio_url", "")
            for known in [".m4a", ".mp3", ".aac"]:
                if known in au.split("?")[0]: ext = known; break
            if not ext: ext = ".m4a"
        fn = "xm_" + safe_fn(info["title"]) + "_" + ts + ext
        return download_audio(info["audio_url"], fn, output_dir)


def _interactive_login_and_download(link, output_dir=None, download_all=True, start_from=1):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[XM] Playwright not installed.")
        return None

    profile_dir = os.path.join(ROOT, "tmp", "xm_login_profile")
    os.makedirs(profile_dir, exist_ok=True)

    album_id = None
    am = re.search(r"/album/(\d+)", link)
    if am: album_id = str(am.group(1))

    print("=" * 50)
    print("[XM] Opening Chrome. Log in, then press Enter.")
    print("=" * 50)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=False, channel="chrome",
            args=["--start-maximized", "--no-first-run", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"], viewport=None)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.add_init_script("""() => {
            Object.defineProperty(navigator, "webdriver", {get: () => undefined});
            Object.defineProperty(navigator, "plugins", {get: () => [1,2,3,4,5]});
        }""")
        page.goto("https://www.ximalaya.com/", wait_until="domcontentloaded", timeout=30000)
        input()

        if album_id:
            print("[XM] Getting track list via API...")
            tracks = get_album_tracks(album_id)
        else:
            tracks = []
        if not tracks:
            print("[XM] No tracks found.")
            ctx.close(); return None

        total = len(tracks)
        print("[XM] {} tracks. Capturing and downloading...".format(total))
        output = output_dir or os.path.join(ROOT, "output")
        os.makedirs(output, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        results = []
        ok = 0
        skip = 0

        _out_dir = output_dir or os.path.join(ROOT, "output")
        for i, t in enumerate(tracks):
            if i + 1 < start_from:
                continue
            tid = t["track_id"]
            title = t["title"]
            # Check if already downloaded
            _safe = lambda s: "".join(c2 if c2.isalnum() or c2 in " .-_" else "_" for c2 in s)[:50].strip(" _")
            _existing = [f for f in (os.listdir(_out_dir) if os.path.exists(_out_dir) else []) if _safe(title)[:30] in f]
            if _existing:
                skip += 1
                continue
            print("\r  [{}/{}] {} ... ".format(i+1, total, title[:30]), end="")

            urls = []
            def handler(req):
                u = req.url
                if "audiopay.cos" in u or ("xmcdn.com" in u and any(e in u for e in [".m4a", ".mp3", ".aac"])):
                    urls.append(u)
            page.on("request", handler)

            try:
                page.goto("https://www.ximalaya.com/sound/{}".format(tid),
                          wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(2500)
                page.evaluate("""() => {
                    var b = document.querySelector("[class*=\\"play\\"]") || document.querySelector("button");
                    if (b) b.click();
                }""")
                page.wait_for_timeout(3000)
            except Exception:
                pass

            page.remove_listener("request", handler)

            if urls:
                au = urls[0]
                ext = ".m4a"
                for e in [".m4a", ".mp3", ".aac"]:
                    if e in au.split("?")[0]:
                        ext = e; break
                safe = lambda s: "".join(c2 if c2.isalnum() or c2 in " .-_" else "_" for c2 in s)[:50].strip(" _")
                fn = "xm_" + safe(title) + "_" + ts + ext
                r = download_audio(au, fn, output)
                if r:
                    results.append(r)
                    ok += 1
            else:
                skip += 1

            if (i + 1) % 50 == 0:
                print("\n  --- {}/{} done, {} downloaded, {} skipped ---".format(i+1, total, ok, skip))
            time.sleep(10.0)

        print("\n\n[XM] Done: {} downloaded, {} skipped (no audio)".format(ok, skip))
        ctx.close()
    return results



if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Ximalaya audio downloader")
    ap.add_argument("link", nargs="?", help="Album/sound URL or track ID")
    ap.add_argument("--all", action="store_true", help="Download all tracks in album")
    ap.add_argument("--use-chrome", action="store_true", help="Use Chrome profile for paid tracks")
    ap.add_argument("--output", "-o", default=None, help="Output dir")
    args = ap.parse_args()
    if args.link:
        link = args.link
        if not link.startswith("http") and not link.isdigit():
            link = "https://www.ximalaya.com/sound/" + link
        download(link, output_dir=args.output, download_all=args.all, start_from=args.start_from)
    else:
        link = input("Ximalaya URL or track ID: ").strip()
        if link:
            if not link.startswith("http") and not link.isdigit():
                link = "https://www.ximalaya.com/sound/" + link
            download(link)
