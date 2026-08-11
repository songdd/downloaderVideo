import os, re, sys, json, time, requests
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

def _reload_cookie():
    global _COOKIE
    ck = load_cookie()
    if ck and ck != _COOKIE:
        _COOKIE = ck
        H["Cookie"] = ck
        return True
    return False

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
    tracks = []
    seen = set()

    # Strategy 1: mobile API
    page_id = 1
    while page_id <= 50:
        url = "https://mobile.ximalaya.com/mobile/v1/album/track?albumId={}&pageId={}&pageSize={}".format(album_id, page_id, page_size)
        try:
            r = requests.get(url, headers=H, timeout=30)
            data = r.json()
            if data.get("ret") != 0:
                break
            d = data.get("data", {})
            for t in d.get("list", []):
                tid = str(t.get("trackId", ""))
                if tid and tid not in seen:
                    seen.add(tid)
                    tracks.append({"track_id": tid, "title": t.get("title", ""), "index": t.get("orderNo", 0), "duration": t.get("duration", 0)})
            mp = d.get("maxPageId", 1)
            if page_id >= mp: break
            page_id += 1; time.sleep(0.2)
        except: break

    if tracks: return tracks

    # Strategy 2: web revision API
    print("[XM] Mobile API unavailable, trying web fallback...")
    for rev_page in [1, 2, 3]:
        try:
            r = requests.get("https://www.ximalaya.com/revision/album?albumId={}&pageNum={}&pageSize={}".format(album_id, rev_page, page_size), headers=H, timeout=30)
            data = r.json()
            if data.get("ret") != 200: break
            pt = data.get("data", {}).get("tracksInfo", {}).get("tracks", [])
            if not pt: break
            nc = 0
            for t in pt:
                tid = str(t.get("trackId", ""))
                if tid and tid not in seen:
                    seen.add(tid)
                    tracks.append({"track_id": tid, "title": t.get("title", ""), "index": t.get("index", 0), "duration": t.get("duration", 0)})
                    nc += 1
            if nc == 0: break
            time.sleep(0.3)
        except: break

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

def _get_album_name(album_id):
    try:
        r = requests.get(
            "https://www.ximalaya.com/revision/album?albumId={}".format(album_id),
            headers=H, timeout=10)
        if r.status_code == 200:
            d = r.json()
            name = d.get("data", {}).get("mainInfo", {}).get("albumTitle", "")
            if not name:
                name = d.get("data", {}).get("tracksInfo", {}).get("tracks", [{}])[0].get("albumTitle", "")
            if not name:
                # Try mobile API
                r2 = requests.get(
                    "https://mobile.ximalaya.com/mobile/v1/album?albumId={}".format(album_id),
                    headers=H, timeout=10)
                if r2.status_code == 200:
                    name = r2.json().get("data", {}).get("album", {}).get("title", "")
            return name
    except Exception:
        pass
    return ""


# ---- retry with backoff ----
_RETRY_WAIT = 30       # seconds, doubles on each failure
_RETRY_MAX_WAIT = 1800  # max 30 minutes

def _retry_wait(reset=False):
    global _RETRY_WAIT
    if reset:
        _RETRY_WAIT = 30
        return
    w = _RETRY_WAIT
    _RETRY_WAIT = min(_RETRY_WAIT * 2, _RETRY_MAX_WAIT)
    return w

class _RetryBudget:
    """Per-track retry backoff: 30s start, doubles to 30min, 24h overall cap."""

    def __init__(self, start=30, max_wait=1800, max_total=86400):
        self._start = start
        self._max_wait = max_wait
        self._max_total = max_total
        self.reset()

    def next_wait(self):
        w = self._wait
        self._wait = min(self._wait * 2, self._max_wait)
        return w

    def reset(self):
        self._wait = self._start
        self._first_fail = 0.0

    def elapsed(self):
        if not self._first_fail:
            self._first_fail = time.time()
        return time.time() - self._first_fail

    def give_up(self):
        return self.elapsed() > self._max_total


def _is_valid_audio(fp):
    """Check file header is a real audio format (not JS/HTML/font error content)."""
    try:
        with open(fp, "rb") as f:
            head = f.read(12)
    except Exception:
        return False
    if len(head) < 12:
        return False
    # M4A / MP4: 'ftyp' at offset 4
    if head[4:8] == b"ftyp":
        return True
    # MP3 with ID3 tag
    if head[:3] == b"ID3":
        return True
    # MP3 / AAC: MPEG sync frame 0xFF Ex/Fx
    if head[0] == 0xFF and (head[1] & 0xF0) == 0xF0:
        return True
    # FLAC / OGG / WAV
    if head[:4] == b"fLaC" or head[:4] == b"OggS":
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return True
    return False


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
        if actual < 10000 or not _is_valid_audio(fp):
            print("[XM] INVALID AUDIO ({} bytes, not playable), removing: {}".format(actual, fp))
            try: os.remove(fp)
            except: pass
            return None
        print("[XM] Saved: " + fp + " (" + str(round(actual/1024/1024,1)) + " MB)")
        return fp
    except Exception as e:
        print("[XM] Download failed: " + str(e))
        try: os.remove(fp)
        except: pass
        return None

def _count_effective(tracks, start_from=1, to=None, tracks_str=""):
    """How many tracks pass start_from/to/tracks filters (for progress display)."""
    track_set = None
    if tracks_str:
        try:
            track_set = set(int(x.strip()) for x in tracks_str.split(",") if x.strip().isdigit())
        except:
            pass
    n = 0
    for i, t in enumerate(tracks):
        idx = i + 1
        if idx < start_from:
            continue
        if to and idx > to:
            break
        if track_set is not None and idx not in track_set:
            continue
        n += 1
    return n


def download(link, output_dir=None, download_all=False, start_from=1, progress_callback=None, to=None, tracks=""):
    _reload_cookie()
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
        track_set = None
        if tracks:
            try: track_set = set(int(x.strip()) for x in tracks.split(",") if x.strip().isdigit())
            except: pass
        eff_total = _count_effective(tracks, start_from, to, tracks)

        for i, t in enumerate(tracks):
            idx = i + 1
            if idx < start_from:
                continue
            if to and idx > to:
                break
            if track_set is not None and idx not in track_set:
                continue
            # Check if already downloaded
            safe = lambda s: "".join(c2 if c2.isalnum() or c2 in " .-_" else "_" for c2 in s)[:50].strip(" _")
            album_name = _get_album_name(album_id)
            out_dir = output_dir or os.path.join(ROOT, "output")
            if album_name:
                safe_name = re.sub(r'[<>:"/\\|?*]', "_", album_name)[:40].strip(" _")
                out_dir = os.path.join(out_dir, safe_name)
            existing = [f for f in (os.listdir(out_dir) if os.path.exists(out_dir) else []) if safe(t["title"])[:30] in f]
            if existing:
                skipped_existing += 1
                continue
            track_attempt = 0
            budget = _RetryBudget()
            while True:
                track_attempt += 1
                if track_attempt > 1:
                    if budget.give_up():
                        elapsed = budget.elapsed()
                        print(f"[XM] Giving up on track {t['track_id']} after {elapsed/3600:.1f}h (max 24h)")
                        results.append(None)
                        budget.reset()
                        break
                    w = budget.next_wait()
                    elapsed = budget.elapsed()
                    print(f"[XM] Track {t['track_id']} failed ({elapsed/60:.0f}m elapsed), waiting {w}s before retry {track_attempt}...")
                    if progress_callback:
                        progress_callback({"event": "retry", "track": t["title"][:30], "wait": w, "attempt": track_attempt})
                    time.sleep(w)

                print(f"\n[XM] [{i+1}/{total}] Track {t['track_id']}: {t['title'][:40]}")
                info = get_track_info(t["track_id"])
                if not info:
                    continue
                if not info.get("audio_url"):
                    continue
                ext = info.get("ext", "")
                if not ext:
                    au = info.get("audio_url", "")
                    for known in [".m4a", ".mp3", ".aac"]:
                        if known in au.split("?")[0]:
                            ext = known; break
                    if not ext: ext = ".m4a"
                fn = "xm_" + safe_fn(info["title"]) + "_" + ts + ext
                r = download_audio(info["audio_url"], fn, out_dir)
                if r:
                    results.append(r)
                    if progress_callback:
                        progress_callback({"event": "progress", "current": i + 1, "total": eff_total, "file": r, "title": t["title"]})
                    budget.reset()
                    if i < total - 1:
                        time.sleep(3)
                    break
                print(f"[XM]   Download failed for track {t['track_id']}, will retry after delay...")
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


def _interactive_login_and_download(link, output_dir=None, download_all=True, start_from=1, progress_callback=None, web_mode=False):
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

    # Check for Baidu upload
    upload_to_baidu = "--upload-baidu" in sys.argv
    if upload_to_baidu:
        try:
            from task_tracker import TaskTracker
        except: upload_to_baidu = False

    print("=" * 50)
    if web_mode:
        print("[XM] Opening Chrome for interactive download...")
    else:
        print("[XM] Opening Chrome. Log in, then press Enter.")
    print("=" * 50)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=False, channel="chrome",
            args=["--start-maximized", "--no-first-run", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"], viewport=None)
        page = ctx.new_page()
        page.add_init_script("""() => {
            Object.defineProperty(navigator, "webdriver", {get: () => undefined});
            Object.defineProperty(navigator, "plugins", {get: () => [1,2,3,4,5]});
        }""")
        page.goto("https://www.ximalaya.com/", wait_until="domcontentloaded", timeout=30000)
        if not web_mode:
            input("Press Enter after logging in...")

        # Get track list via API first
        print("[XM] Getting track list via API...")
        tracks = get_album_tracks(album_id) if album_id else []

        # If API gives less than expected, try scraping from the album page
        if album_id:
            # Check total count from revision API
            try:
                r_check = requests.get(
                    f"https://www.ximalaya.com/revision/album?albumId={album_id}",
                    headers=H, timeout=10)
                total_api = r_check.json().get("data", {}).get("tracksInfo", {}).get("trackTotalCount", 0)
            except: total_api = 0

            if total_api > len(tracks):
                print(f"[XM] API returned {len(tracks)}/{total_api} tracks. Scraping album page...")
                page_tracks = _scrape_tracks_from_page(page, link, total_api)
                if page_tracks:
                    # Merge and dedup
                    seen_ids = {t["track_id"] for t in tracks}
                    for pt in page_tracks:
                        if pt["track_id"] not in seen_ids:
                            seen_ids.add(pt["track_id"])
                            tracks.append(pt)
                    print(f"[XM] After scraping: {len(tracks)} tracks total")

        if not tracks:
            print("[XM] No tracks found.")
            ctx.close()
            return None

        # Create output subdirectory
        album_name = _get_album_name(album_id) if album_id else ""
        output = output_dir or os.path.join(ROOT, "output")
        if album_name:
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", album_name)[:40].strip(" _")
            output = os.path.join(output, safe_name)
        os.makedirs(output, exist_ok=True)
        print("[XM] Output dir: " + output)

        # Start Baidu upload tracker
        tracker = None
        if upload_to_baidu:
            bd_dir = "/apps/downloaderVideo"
            try:
                idx = sys.argv.index("--baidu-dir")
                bd_dir = sys.argv[idx + 1]
            except: pass
            try:
                from task_tracker import TaskTracker
                tracker = TaskTracker(remote_dir=bd_dir)
                tracker.start_upload()
            except Exception as e:
                print("[BAIDU] Upload init failed: " + str(e)[:60])

        total = len(tracks)
        if progress_callback:
            progress_callback({"event": "init", "total": eff_total})
        print("[XM] {} tracks. Capturing and downloading...".format(total))
        ts = time.strftime("%Y%m%d_%H%M%S")
        results = []
        ok = 0
        skip = 0

        track_set = None
        if tracks:
            try: track_set = set(int(x.strip()) for x in tracks.split(",") if x.strip().isdigit())
            except: pass
        eff_total = _count_effective(tracks, start_from, to, tracks)

        for i, t in enumerate(tracks):
            idx = i + 1
            if idx < start_from:
                continue
            if to and idx > to:
                break
            if track_set is not None and idx not in track_set:
                continue
            tid = t["track_id"]
            track_retry_count = 0
            title = t["title"]
            print("\r  [{}/{}] {} ... ".format(i+1, total, title[:30]), end="")

            au = None
            captured = []
            def on_resp(resp):
                u = resp.url
                ct = resp.headers.get("content-type", "")
                if "audio" in ct or any(e in u for e in [".m4a", ".mp3", ".aac"]):
                    if "xmcdn.com" in u or "audiopay" in u:
                        captured.append(u)
            page.on("response", on_resp)

            try:
                page.goto("https://www.ximalaya.com/sound/{}".format(tid),
                          wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                page.evaluate("""() => {
                    var sels = ['[class*="play-btn"]', '[class*="playButton"]', '.play-btn', 'button[class*="play"]', '.sound-play'];
                    for (var i = 0; i < sels.length; i++) {
                        var el = document.querySelector(sels[i]);
                        if (el) { el.click(); return 'ok'; }
                    }
                    return 'no btn';
                }""")
                page.wait_for_timeout(4000)
            except Exception:
                try: page.evaluate("() => window.stop()")
                except: pass

            page.remove_listener("response", on_resp)

            if captured:
                au = captured[0]
            else:
                try:
                    au = page.evaluate("""() => {
                        var a = document.querySelector('audio[src]');
                        if (a && a.src && a.src.startsWith('http')) return a.src;
                        return '';
                    }""")
                except: pass

            if au and au.startswith("http"):
                ext = ".m4a"
                for e in [".m4a", ".mp3", ".aac"]:
                    if e in au.rsplit("?", 1)[0]:
                        ext = e; break
                safe = lambda s: "".join(c2 if c2.isalnum() or c2 in " .-_" else "_" for c2 in s)[:50].strip(" _")
                fn = "xm_" + safe(title) + "_" + ts + ext
                r = download_audio(au, fn, output)
                if r:
                    results.append(r); ok += 1
                    if tracker: tracker.record(r)
                    if progress_callback:
                        progress_callback({"event": "progress", "current": i + 1, "total": eff_total, "file": r, "title": title})
                    _retry_wait(reset=True)
                else:
                    if track_retry_count >= 5:
                        print(f"[XM]   Track {tid} failed 5 times, skipping")
                        skip += 1
                        _retry_wait(reset=True)
                        break
                    print(f"[XM]   Download failed for track {tid}, will retry after delay...")
                    track_retry_count += 1
                    time.sleep(30)
                    continue  # retry this track
            else:
                if track_retry_count >= 5:
                    print(f"[XM]   No audio captured for track {tid} after 5 attempts, skipping")
                    skip += 1
                    _retry_wait(reset=True)
                    break
                print(f"[XM]   No audio captured for track {tid}, will retry after delay...")
                track_retry_count += 1
                time.sleep(30)
                continue  # retry this track

            if (i + 1) % 50 == 0:
                print("\n  --- {}/{} done, {} downloaded, {} skipped ---".format(i+1, total, ok, skip))
            time.sleep(10.0)

            print("\n\n[XM] Done: {} downloaded, {} skipped (no audio)".format(ok, skip))
        if progress_callback:
            progress_callback({"event": "done", "downloaded": ok, "total": eff_total, "skipped": skip})
        if tracker:
            tracker.wait()
            tracker.save_log()
        ctx.close()
    return results


def _scrape_tracks_from_page(page, album_url, expected_total):
    """Use Playwright to click through pagination and scrape track IDs."""
    tracks = []
    seen_ids = set()
    try:
        page.goto(album_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(5000)
        for pg in range(20):
            items = page.evaluate("""() => {
                var results = [];
                var links = document.querySelectorAll('a[href*="/sound/"]');
                links.forEach(function(a) {
                    var href = a.getAttribute("href");
                    var parts = href.split("/sound/");
                    if (parts.length > 1) {
                        var tid = parts[1].split("?")[0].split("#")[0];
                        if (tid && /^[0-9]+$/.test(tid)) {
                            var title = a.textContent.trim() || a.getAttribute("title") || "";
                            results.push({trackId: tid, title: title});
                        }
                    }
                });
                return results;
            }""")
            for it in items:
                tid = str(it["trackId"])
                if tid and tid != "None" and tid not in seen_ids:
                    seen_ids.add(tid)
                    tracks.append({"track_id": tid, "title": it.get("title", "")[:60], "index": len(tracks)+1, "duration": 0})
            if pg % 2 == 0:
                print("  [scrape] page " + str(pg+1) + ": " + str(len(tracks)) + " tracks so far")
            try:
                next_btn = page.locator(".page-next:not(.disabled) .page-link, [class*=next]:not([class*=disabled]) a").first
                if next_btn:
                    next_btn.click()
                    page.wait_for_timeout(3000)
                else:
                    break
            except:
                break
            if len(tracks) >= expected_total:
                break
    except Exception as e:
        print("  [scrape] error: " + str(e)[:60])
    return tracks
