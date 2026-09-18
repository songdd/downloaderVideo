import os, re, sys, time, requests, shutil, subprocess, json, threading, queue
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":"https://v.youku.com/"}

# Anti-automation fingerprint patch (injected before every navigation).
STEALTH_JS = r"""
() => {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = window.chrome || {runtime: {}};
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    try {
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) => (
            p && p.name === 'notifications'
                ? Promise.resolve({state: Notification.permission})
                : origQuery(p));
    } catch (e) {}
    try {
        const gp = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return gp.call(this, parameter);
        };
    } catch (e) {}
    const ua = navigator.userAgent;
    Object.defineProperty(navigator, 'userAgent', {get: () => ua.replace('HeadlessChrome', 'Chrome')});
}
"""

# Force-mute all media in automated sessions: headless Chrome still outputs
# audio, and the player may unmute itself when a play button is clicked.
# Keep it light (do NOT override muted/volume getters - that broke the player).
MUTE_JS = r"""
() => {
    try {
        const origPlay = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function() {
            try { this.muted = true; this.volume = 0; } catch (e) {}
            return origPlay.apply(this, arguments);
        };
        const sweep = () => {
            document.querySelectorAll('video, audio').forEach(function(m) {
                try { m.muted = true; m.volume = 0; } catch (e) {}
            });
        };
        sweep();
        setInterval(sweep, 1000);
    } catch (e) {}
}
"""


def _mute_page(ctx):
    try:
        ctx.add_init_script(MUTE_JS)
    except Exception:
        pass

def load_cookie():
    try: from cookies import load_cookie as lc; return lc("youku")
    except: return None

def parse_url(url):
    m = re.search(r"/id_([a-zA-Z0-9=]+)(\.html)?", url)
    return m.group(1) if m else None

def _find_chrome():
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return "chrome"

# Job handles stay open for this process's lifetime; when this process exits
# (even via task-kill / crash) the OS kills every Chrome inside the job.
_job_handles = []


def _spawn_chrome(chrome_args):
    """Spawn Chrome bound to a Windows Job with KILL_ON_JOB_CLOSE so it can
    never outlive this process as an orphaned audio-playing instance."""
    proc = subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return proc
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                                ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return proc
        hproc = kernel32.OpenProcess(0x0100 | 0x0001, False, proc.pid)  # SET_QUOTA|TERMINATE
        if hproc:
            kernel32.AssignProcessToJobObject(job, hproc)
            kernel32.CloseHandle(hproc)
            _job_handles.append(job)  # keep open for this process's lifetime
    except Exception:
        pass
    return proc

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def _capture_cdp(vid, cookie=None, wait_s=120, headless=True):
    """CDP-mode capture: manually spawn real Chrome with a debug port, then
    drive it via connect_over_cdp. No Playwright launch traces, clean
    fingerprint + injected login cookie -> youku risk control does not engage.
    Headless by default (verified to pass risk control); pass headless=False
    only if a visible window is ever needed. Returns
    {"title","stream_url","vid"} or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[YOUKU-CDP] Playwright not installed.")
        return None
    chrome = _find_chrome()
    profile = os.path.join(ROOT, "tmp", "youku_cdp_profile")
    os.makedirs(profile, exist_ok=True)
    port = _free_port()
    url = "https://v.youku.com/v_show/id_" + vid + ".html"
    print("[YOUKU-CDP] Launching %sChrome (port %d)..." % ("" if headless else "visible ", port), flush=True)
    chrome_args = [chrome, "--remote-debugging-port=%d" % port,
                   "--user-data-dir=" + profile,
                   "--no-first-run", "--disable-popup-blocking",
                   "--disable-blink-features=AutomationControlled",
                   "--disable-crash-reporter", "--disable-breakpad", "--noerrdialogs",
                   "--window-size=1280,820"]
    if headless:
        chrome_args.append("--headless=new")
    chrome_args.append("about:blank")
    proc = _spawn_chrome(chrome_args)
    try:
        ready = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                if requests.get("http://127.0.0.1:%d/json/version" % port, timeout=2).status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
        if not ready:
            print("[YOUKU-CDP] Chrome debug port not ready")
            return None
        streams = []      # list of (url, kind)
        api_m3u8 = []     # m3u8 urls found inside API (mtop/ups) responses
        cdp_api_bodies = []  # full API bodies (for quality-table parsing)
        title = "youku_" + vid

        def on_response(resp):
            try:
                u = resp.url
                low = u.lower()
                ct = (resp.headers.get("content-type") or "").lower()
                if "mmstat" in u or "ykt.youku" in u:  # skip telemetry
                    return
                if ".m3u8" in low:
                    streams.append((u, "m3u8"))
                    print("[YOUKU-CDP] m3u8:", u[:110], flush=True)
                elif "video" in ct and (".mp4" in low or "/play/" in low):
                    streams.append((u, "mp4"))
                    print("[YOUKU-CDP] video:", u[:110], flush=True)
                elif "acs.youku" in low or "get.json" in low or "ups" in low or "mtop" in low:
                    if resp.status < 400:
                        try:
                            body = resp.text()[:400000]
                        except Exception:
                            return
                        m3 = re.findall(r'https?://[^"\\\s]+?\.m3u8[^"\\\s]*', body)
                        if m3:
                            api_m3u8.extend(m3)
                            if body not in cdp_api_bodies:
                                cdp_api_bodies.append(body)
                            for x in m3[:3]:
                                print("[YOUKU-CDP] m3u8 in API:", x[:110], flush=True)
            except Exception:
                pass

        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % port)
            except Exception as e:
                print("[YOUKU-CDP] connect failed: " + str(e)[:80])
                return None
            ctx = browser.contexts[0]
            _mute_page(ctx)
            if cookie:
                n = 0
                for ck in cookie.split("; "):
                    if "=" in ck:
                        try:
                            k, v = ck.split("=", 1)
                            ctx.add_cookies([{"name": k, "value": v, "domain": ".youku.com", "path": "/"}])
                            n += 1
                        except Exception:
                            pass
                print("[YOUKU-CDP] injected %d cookie pairs" % n, flush=True)
            page = ctx.new_page()
            page.on("response", on_response)
            print("[YOUKU-CDP] opening video page...", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            print("[YOUKU-CDP] if a captcha appears, complete it in the window (max %ds)" % wait_s, flush=True)
            deadline = time.time() + wait_s
            clicked = False
            while time.time() < deadline:
                page.wait_for_timeout(2500)
                try:
                    btn = page.query_selector("video, .play-btn, [class*=play], [class*=Play]")
                    if btn and not clicked:
                        btn.click(force=True)
                        clicked = True
                        print("[YOUKU-CDP] clicked play", flush=True)
                except Exception:
                    pass
                try:
                    page.evaluate("""() => {
                        var v = document.querySelector('video');
                        if (v && v.paused) { v.muted = true; v.play().catch(function(){}); }
                    }""")
                except Exception:
                    pass
                if streams or api_m3u8:
                    print("[YOUKU-CDP] captured streams: %d direct, %d in API" % (len(streams), len(api_m3u8)), flush=True)
                    break
            try:
                # youku page title: "主标题-分类-高清完整正版视频在线观看"
                raw = page.title() or ("youku_" + vid)
                title = raw.split("-")[0].strip() or ("youku_" + vid)
            except Exception:
                pass
            page.close()
            browser.close()

        # choose a stream: prefer the wanted-quality m3u8 from the playback API
        # (same quality logic as the harvester), else the player's direct m3u8.
        best = None
        try:
            cdp_items = []
            for b in cdp_api_bodies:
                cdp_items.extend(_parse_quality_items(b))
            best = _pick_quality_url(cdp_items, want=1920)
        except Exception:
            best = None
        chosen = best
        if not chosen:
            for u, kind in streams:
                if kind == "m3u8":
                    chosen = u
                    break
        if not chosen and api_m3u8:
            chosen = api_m3u8[-1]
        if not chosen and streams:
            chosen = streams[0][0]
        if not chosen:
            print("[YOUKU-CDP] no stream captured")
            return None
        print("[YOUKU-CDP] chosen: " + chosen[:120], flush=True)
        return {"title": title, "stream_url": chosen, "vid": vid}
    finally:
        try:
            proc.terminate()
            time.sleep(1)
            proc.kill()
        except Exception:
            pass

def get_video_info(vid, cookie=None, use_firefox=False):
    try: from playwright.sync_api import sync_playwright
    except ImportError: print("[YOUKU] Playwright not installed."); return None
    print("[YOUKU] Opening " + ("Firefox" if use_firefox else "Chrome") + "...")
    video_urls, title = [], "youku_" + vid
    try:
        with sync_playwright() as p:
            ctx = None
            browser = None
            if not use_firefox:
                # Reuse the real login profile (tmp/chrome_login) saved by
                # login.py / `run.py -l youku`. A real logged-in profile has a
                # consistent browser fingerprint + session, which avoids the
                # risk-control captcha that a fresh automation context triggers.
                profile = os.path.join(ROOT, "tmp", "chrome_login")
                try:
                    if os.path.isdir(profile):
                        ctx = p.chromium.launch_persistent_context(
                            user_data_dir=profile, headless=False, channel="chrome",
                            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                                  "--window-size=1100,750", "--disable-infobars", "--disable-dev-shm-usage"],
                            ignore_default_args=["--enable-automation"])
                        print("[YOUKU] Using saved login profile (tmp/chrome_login)")
                except Exception as e:
                    print("[YOUKU] Profile open failed, falling back: " + str(e)[:80])
                    ctx = None
            if ctx is None:
                if use_firefox:
                    browser = p.firefox.launch(headless=False)
                else:
                    browser = p.chromium.launch(headless=False, channel="chrome",
                        args=["--no-sandbox","--disable-blink-features=AutomationControlled","--window-size=1100,750"])
                ctx = browser.new_context(user_agent=H["User-Agent"], viewport={"width":1280,"height":720})
                if cookie:
                    for ck in cookie.split("; "):
                        if "=" in ck:
                            n, v = ck.split("=", 1)
                            try: ctx.add_cookies([{"name":n,"value":v,"domain":".youku.com","path":"/"}])
                            except: pass
            page = ctx.new_page()
            try:
                ctx.add_init_script(STEALTH_JS)
            except Exception:
                pass
            def on_response(resp):
                u = resp.url
                if any(x in u for x in [".m3u8",".ts",".mp4"]) or "video" in (resp.headers.get("content-type") or ""):
                    try: cl = int(resp.headers.get("content-length","0"))
                    except: cl = 0
                    video_urls.append((u, cl))
            page.on("response", on_response)
            page.goto("https://v.youku.com/v_show/id_" + vid + ".html", wait_until="domcontentloaded", timeout=30000)
            # Wait for the player for up to ~120s. Youku may first show a
            # risk-control captcha or an x5sec "punish" page that auto-reloads.
            # If a captcha appears, complete it in the visible window - the
            # download continues automatically afterwards.
            print("[YOUKU] If a verification window pops up, please complete it manually - script keeps waiting (max 120s)", flush=True)
            deadline = time.time() + 120
            clicked = False
            captcha_seen = False
            while time.time() < deadline:
                page.wait_for_timeout(3000)
                try:
                    # detect captcha / punish page to give clearer guidance
                    hint = page.evaluate("""() => {
                        var t = document.body ? document.body.innerText : '';
                        if (/验证|真人|punish|captcha|滑动|点击框体/.test(t)) return true;
                        return /_____tmd_____/.test(location.href);
                    }""")
                    if hint and not captcha_seen:
                        captcha_seen = True
                        print("[YOUKU] !! Verification/captcha detected - please complete it in the Chrome window now (do NOT close it)", flush=True)
                except Exception:
                    pass
                try:
                    btn = page.query_selector("video, .play-btn, [class*=play], [class*=Play]")
                    if btn and not clicked:
                        btn.click(force=True); clicked = True
                        print("[YOUKU] clicked play button", flush=True)
                except Exception: pass
                try:
                    js_url = page.evaluate("""() => {
                        var v = document.querySelector('video');
                        if (v && v.currentSrc && v.currentSrc.indexOf('http') === 0) return v.currentSrc;
                        if (v && v.src && v.src.indexOf('http') === 0) return v.src;
                        var ss = document.querySelectorAll('script');
                        for (var i = 0; i < ss.length; i++) {
                            var t = ss[i].textContent || '';
                            var m = t.match(/https?:[^"'\\s]+\\.m3u8[^"'\\s]*/);
                            if (m) return m[0];
                        }
                        return null;
                    }""")
                    if js_url:
                        print("[YOUKU] JS/video found: " + str(js_url)[:120], flush=True)
                        video_urls.append((js_url, 0))
                        break
                except Exception as e: print("[YOUKU] JS error: " + str(e))
                if video_urls:
                    print("[YOUKU] captured " + str(len(video_urls)) + " stream(s)", flush=True)
                    break
            try:
                t = page.title() or ""
                for suffix in ("-优酷", "-游戏", "-Youku"):
                    t = t.replace(suffix, "")
                title = t.strip() or title
            except: pass
            ctx.close()
            if browser: browser.close()
    except Exception as e: print("[YOUKU] PW error: " + str(e)); return None

    if not video_urls: print("[YOUKU] No streams"); return None
    print("[YOUKU] Intercepted " + str(len(video_urls)) + " URLs")
    m3u8s = [(u,s) for u,s in video_urls if ".m3u8" in u]
    if not m3u8s:
        ts = [(u,s) for u,s in video_urls if ".ts" in u]
        if ts:
            g = re.sub(r"_[0-9]+\.ts", ".m3u8", ts[0][0])
            if g != ts[0][0]: print("[YOUKU] Reconstructed M3U8: " + g[:80] + "..."); m3u8s.append((g, 0))
    if m3u8s:
        m3u8s.sort(key=lambda x: x[1], reverse=True)
        return {"title": title, "stream_url": m3u8s[0][0], "vid": vid}
    ts2 = [(u,s) for u,s in video_urls if ".ts" in u or ".mp4" in u]
    if ts2: ts2.sort(key=lambda x: x[1], reverse=True); return {"title": title, "stream_url": ts2[0][0], "vid": vid}
    return None

def _extract_audio_playlist(body):
    """Youku often serves video-only media playlists; the separate audio track
    is announced in an inline master playlist (#EXT-X-MEDIA:TYPE=AUDIO)."""
    m = re.search(r'#EXT-X-MEDIA:TYPE=AUDIO[^#]*?URI="([^"]+)"', body)
    if m and _is_stream_url(m.group(1)):
        return m.group(1)
    return None


def _merge_av(video_fp, audio_fp, out_fp):
    """Mux a separately downloaded audio track into the video file."""
    ffmpeg = "ffmpeg"
    for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
        if os.path.exists(g):
            ffmpeg = g
            break
    try:
        rr = subprocess.run([ffmpeg, "-y", "-loglevel", "error",
                             "-i", video_fp, "-i", audio_fp,
                             "-map", "0:v:0", "-map", "1:a:0",
                             "-c", "copy", out_fp],
                            capture_output=True, timeout=1800)
    except Exception as e:
        print("[YOUKU] merge error: " + str(e)[:100])
        return None
    if rr.returncode == 0 and os.path.exists(out_fp) and os.path.getsize(out_fp) > 100000:
        print("[YOUKU] audio track merged: " + out_fp)
        return out_fp
    err = (rr.stderr or b"").decode("utf-8", "ignore").strip().replace("\n", " | ")
    print("[YOUKU] audio merge failed: " + err[-160:])
    return None


def _fmp4_ok(data):
    """Quick sanity check for an fMP4 box (size-prefixed fourCC)."""
    if not data or len(data) < 16:
        return False
    try:
        size = int.from_bytes(data[0:4], "big")
    except Exception:
        return False
    fourcc = data[4:8]
    return size >= 8 and fourcc in (b"ftyp", b"moov", b"moof", b"mdat", b"styp",
                                    b"sidx", b"free", b"skip", b"emsg", b"prft")


def _download_fmp4_hls(text, m3u8_url, fp, hd):
    """Download an fMP4 HLS playlist (EXT-X-MAP init + .mp4 fragments) and
    stitch init+segments in playlist order into a playable mp4. Ad segments
    (/ad/ paths before a discontinuity) are skipped."""
    base = m3u8_url.rsplit("/", 1)[0] + "/"

    def abspath(u):
        return u if u.startswith("http") else base + u

    items = []            # ordered: ("init", url) / ("seg", url, size)
    cur_map = None
    pending_size = None
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', ln)
            if m:
                cur_map = abspath(m.group(1))
                items.append(("init", cur_map))
        elif ln.startswith("#EXT-X-PRIVINF:FILESIZE="):
            try:
                pending_size = int(ln.split("=", 1)[1])
            except Exception:
                pending_size = None
        elif not ln.startswith("#"):
            u = abspath(ln)
            items.append(("seg", u, pending_size))
            pending_size = None

    # drop ad-only material: segments whose url contains "/ad/"
    items = [it for it in items if "/ad/" not in it[1]]
    # drop init entries that belong to the skipped ad block
    cleaned = []
    for idx, it in enumerate(items):
        if it[0] == "init":
            nxt = items[idx + 1] if idx + 1 < len(items) else None
            if nxt is None or nxt[0] == "init":
                continue      # init with no following segment -> unused
        cleaned.append(it)
    items = cleaned
    if not any(it[0] == "seg" for it in items):
        print("[YOUKU] fMP4 playlist has no segments")
        return None

    n_segs = sum(1 for it in items if it[0] == "seg")
    print("[YOUKU] fMP4 HLS: %d segments + %d init -> downloading..." % (
        n_segs, sum(1 for it in items if it[0] == "init")))
    frag = fp + ".frag.mp4"
    got = 0
    failed = 0
    try:
        with open(frag, "wb") as out:
            for it in items:
                url = it[1]
                expect = it[2] if it[0] == "seg" else None
                ok = False
                for _ in range(3):
                    try:
                        sr = requests.get(url, headers=hd, timeout=60)
                        data = sr.content
                        if sr.status_code == 200 and _fmp4_ok(data) and \
                                (not expect or len(data) == expect):
                            out.write(data)
                            ok = True
                            break
                    except Exception:
                        time.sleep(2)
                if it[0] == "seg":
                    if ok:
                        got += 1
                        if got % max(1, n_segs // 5) == 0:
                            print("[YOUKU]  %d/%d" % (got, n_segs), flush=True)
                    else:
                        failed += 1
                        print("[YOUKU]   seg %d FAILED" % got, flush=True)
        if got == 0:
            print("[YOUKU] fMP4 download failed (no segments)")
            return None
        # remux fragmented mp4 into a plain mp4 for maximum compatibility
        ffmpeg = "ffmpeg"
        for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
            if os.path.exists(g):
                ffmpeg = g
                break
        rr = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", frag,
                             "-c", "copy", "-bsf:a", "aac_adtstoasc", fp],
                            capture_output=True, timeout=1800)
        if rr.returncode != 0 or not os.path.exists(fp) or os.path.getsize(fp) < 100000:
            err = (rr.stderr or b"").decode("utf-8", "ignore").strip().replace("\n", " | ")
            print("[YOUKU] remux failed (%s), keeping fragmented file" % err[-160:])
            try:
                os.replace(frag, fp)
            except Exception:
                pass
        else:
            try:
                os.remove(frag)
            except Exception:
                pass
        print("[YOUKU] Done: %s%s" % (fp, (" (%d segs failed)" % failed) if failed else ""))
        return fp
    finally:
        try:
            if os.path.exists(frag) and os.path.exists(fp):
                os.remove(frag)
        except Exception:
            pass


def _sanitize_playlist(url, text, tag="pl"):
    """Strip DRM key declarations so ffmpeg does not try to fetch skd:// keys.

    Youku playlists often carry '#EXT-X-KEY:...URI="skd://..."' while the
    segments themselves are plain, playable data (verified: hand-stitched
    segments decode fine). ffmpeg however refuses the segments when the key
    cannot be opened, so we hand it a cleaned local copy of the playlist."""
    if not text or "#EXT-X-KEY" not in text:
        return url
    clean = "\n".join(ln for ln in text.splitlines()
                      if not ln.strip().startswith("#EXT-X-KEY"))
    d = os.path.join(ROOT, "tmp", "playlists")
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, "%s_%d.m3u8" % (tag, int(time.time() * 1000)))
    try:
        with open(fn, "w", encoding="utf-8") as f:
            f.write(clean)
        print("[YOUKU] stripped DRM key line(s) from playlist -> %s" % os.path.basename(fn), flush=True)
        return fn
    except Exception:
        return url


def _ffmpeg_hls(url, fp, hd, audio_url=None, timeout=7200):
    """Let ffmpeg's HLS engine fetch the playlist(s) and write fp.

    Preferred for fMP4/master playlists: ffmpeg handles EXT-X-MAP init
    segments, EXT-X-DISCONTINUITY boundaries (a hand-stitched file with two
    moov/timelines stops playing at the discontinuity) and can mux a separate
    audio playlist in the same pass."""
    ffmpeg = "ffmpeg"
    for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
        if os.path.exists(g):
            ffmpeg = g
            break
    hdr = "Referer: %s\r\n" % (hd.get("Referer") or "https://v.youku.com/")
    if hd.get("Cookie"):
        hdr += "Cookie: %s\r\n" % hd["Cookie"]
    if hd.get("User-Agent"):
        hdr += "User-Agent: %s\r\n" % hd["User-Agent"]
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-headers", hdr,
           "-allowed_extensions", "ALL",
           "-http_persistent", "0", "-i", url]
    maps = ["-map", "0:v:0"]
    if audio_url:
        cmd += ["-headers", hdr, "-http_persistent", "0", "-i", audio_url]
        maps += ["-map", "1:a:0"]
        print("[YOUKU] ffmpeg fetching video + separate audio track...", flush=True)
    else:
        print("[YOUKU] ffmpeg fetching HLS stream...", flush=True)
    cmd += maps + ["-c", "copy", "-bsf:a", "aac_adtstoasc", fp]
    try:
        rr = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception as e:
        print("[YOUKU] ffmpeg hls error: " + str(e)[:120])
        return None
    if rr.returncode != 0 or not os.path.exists(fp) or os.path.getsize(fp) < 100000:
        err = (rr.stderr or b"").decode("utf-8", "ignore").strip().replace("\n", " | ")
        print("[YOUKU] ffmpeg hls FAILED: " + err[-300:])
        try:
            os.remove(fp)
        except Exception:
            pass
        return None
    print("[YOUKU] Done: " + fp)
    return fp


def download_m3u8(m3u8_url, fp, hd=None, audio_url=None):
    hd = hd or dict(H)
    r = requests.get(m3u8_url, headers=hd, timeout=15)
    if r.status_code != 200: return None
    text = r.text
    # master playlist (multi-bitrate / separate audio) -> ffmpeg handles it
    if "#EXT-X-STREAM-INF" in text or "#EXT-X-MEDIA:" in text:
        return _ffmpeg_hls(_sanitize_playlist(m3u8_url, text, "master"), fp, hd, audio_url=audio_url)
    # fMP4 HLS (mp4 fragments + EXT-X-MAP init): ffmpeg handles discontinuities
    # and multi-init timelines correctly; the hand-stitcher only as a fallback.
    if "#EXT-X-MAP:" in text:
        v_url = _sanitize_playlist(m3u8_url, text, "video")
        a_url = None
        if audio_url:
            try:
                at = requests.get(audio_url, headers=hd, timeout=15).text
                a_url = _sanitize_playlist(audio_url, at, "audio")
            except Exception:
                a_url = audio_url
        res = _ffmpeg_hls(v_url, fp, hd, audio_url=a_url)
        if res:
            return res
        print("[YOUKU] ffmpeg path failed, falling back to segment stitcher...")
        return _download_fmp4_hls(text, m3u8_url, fp, hd)
    lines = text.split("\n")
    # parse segment urls AND optional per-segment expected size (#EXT-X-PRIVINF:FILESIZE=)
    segs = []
    sizes = []
    pending_size = None
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("#EXT-X-PRIVINF:FILESIZE="):
            try:
                pending_size = int(ln.split("=", 1)[1])
            except Exception:
                pending_size = None
        elif ln and not ln.startswith("#"):
            segs.append(ln if ln.startswith("http") else m3u8_url.rsplit("/", 1)[0] + "/" + ln)
            sizes.append(pending_size)
            pending_size = None
    if not segs: return None
    print("[YOUKU] " + str(len(segs)) + " TS segments, downloading...")
    tmp = os.path.join(ROOT, "ts_tmp", str(int(time.time()*1000)))
    os.makedirs(tmp, exist_ok=True)
    try:
        for i, s in enumerate(segs):
            tf = os.path.join(tmp, str(i).zfill(5) + ".ts")
            if os.path.exists(tf) and os.path.getsize(tf) > 0: continue
            expect = (sizes[i] or 0) if i < len(sizes) else 0
            ok = False
            for _ in range(3):
                try:
                    sr = requests.get(s, headers=hd, timeout=30)
                    data = sr.content
                    # strict: must look like TS AND match the playlist's size when
                    # known (concurrent/network hiccups can truncate a segment)
                    if (len(data) > 500 and data[0] == 0x47 and
                            (expect <= 0 or len(data) == expect)):
                        open(tf, "wb").write(data)
                        ok = True
                        break
                except: time.sleep(2)
            if not ok:
                # keep a retry marker so the concat step can report the gap
                print("[YOUKU]   seg %d/%d DOWNLOAD FAILED (size %d)" % (i, len(segs), expect), flush=True)
            if i % max(1, len(segs)//5) == 0: print("[YOUKU]  " + str(i) + "/" + str(len(segs)))
        cf = os.path.join(tmp, "concat.txt")
        with open(cf, "w") as f:
            for i in range(len(segs)):
                p = os.path.join(tmp, str(i).zfill(5) + ".ts")
                if os.path.exists(p) and os.path.getsize(p) > 0: f.write("file " + p.replace("\\", "/") + "\n")
        ffmpeg = "ffmpeg"
        for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
            if os.path.exists(g): ffmpeg = g; break
        rr = subprocess.run([ffmpeg,"-f","concat","-safe","0","-i",cf,"-c","copy",fp,"-y"], capture_output=True, timeout=300)
        if rr.returncode != 0:
            print("[YOUKU] FFmpeg FAILED:\n" + (rr.stderr or b"").decode("utf-8","ignore")[-500:])
            missing = [i for i in range(len(segs)) if not os.path.exists(os.path.join(tmp, str(i).zfill(5)+".ts"))]
            if missing: print("[YOUKU] Missing TS: " + str(missing[:20]))
            return None
        if os.path.exists(fp) and os.path.getsize(fp) > 0: print("[YOUKU] Done: " + fp); return fp
    finally: shutil.rmtree(tmp, ignore_errors=True)

def download_direct(url, fp, hd=None):
    hd = hd or dict(H)
    r = requests.get(url, headers=hd, stream=True, timeout=120)
    total = int(r.headers.get("Content-Length",0))
    print("[YOUKU] Downloading (" + str(round(total/1024/1024,1)) + " MB)...")
    with open(fp,"wb") as f:
        with tqdm(total=total, unit="B", unit_scale=True, desc="YOUKU") as bar:
            for c in r.iter_content(1024*1024):
                if c: f.write(c); bar.update(len(c))
    return fp

def _is_stream_url(u):
    """A real m3u8 URL: starts with http, no whitespace/newlines/playlist text."""
    if not isinstance(u, str):
        return False
    u = u.strip()
    if not u.startswith("http"):
        return False
    if any(c in u for c in " \t\r\n#\"'\\"):
        return False
    if "#EXTM3U" in u or "#EXT-X-" in u:
        return False
    return ".m3u8" in u.split("?")[0].lower() or ".m3u8" in u.lower()


def _parse_quality_items(body):
    """Extract (url, width, size) for every m3u8 in a playback API body.

    Preferred path: parse the mtop jsonp JSON and walk stream objects (each has
    width/size/m3u8_url). Regex fallback for non-JSON bodies. Only real URLs are
    kept - some responses inline the whole playlist text instead of a URL."""
    out = []
    try:
        i = body.find("(")
        j = body.rfind(")")
        d = json.loads(body[i + 1:j] if 0 <= i < j else body)

        def walk(o):
            if isinstance(o, dict):
                u = o.get("m3u8_url")
                if _is_stream_url(u):
                    try:
                        out.append((u.strip(), int(o.get("width") or 0), int(o.get("size") or 0)))
                    except Exception:
                        pass
                elif isinstance(u, str) and ("#EXTM3U" in u or ".m3u8" in u):
                    # inline playlist text: pull an embedded playlist/segment URL out
                    m2 = re.search(r'https?://[^"\'\s\\]+?\.m3u8[^"\'\s\\]*', u)
                    if m2 and _is_stream_url(m2.group(0)):
                        try:
                            out.append((m2.group(0), int(o.get("width") or 0), int(o.get("size") or 0)))
                        except Exception:
                            pass
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(d)
    except Exception:
        out = []
    if not out:
        for m in re.finditer(r'https?://[^"\\\s]+?\.m3u8', body):
            url = m.group(0)
            if not _is_stream_url(url):
                continue
            seg = body[max(0, m.start() - 500):m.end() + 300]
            wm = re.search(r'"width"\s*:\s*(\d+)', seg)
            sm = re.search(r'"size"\s*:\s*(\d+)', seg)
            out.append((url, int(wm.group(1)) if wm else 0, int(sm.group(1)) if sm else 0))
    # dedupe
    seen, clean = set(), []
    for it in out:
        if it[0] not in seen:
            seen.add(it[0])
            clean.append(it)
    return clean


MIN_REAL_SIZE = 10 * 1024 * 1024  # below this a tier is a preview clip, not the episode


def _pick_quality_url(items, want=1920):
    """Pick the best m3u8 url for the wanted width (1080p by default).

    Rules learned from youku's API quirks:
      * preview clips (mp4hd*v2 with one tiny seg, ~100KB) must never be chosen;
      * never silently jump UP to a bigger tier (4K is ~1.7GB/episode) - if the
        wanted width is missing, step DOWN to the widest smaller tier and let
        the caller fall back to the player's own stream when nothing qualifies.
    """
    if not items:
        return None
    real = [i for i in items if (i[2] or 0) >= MIN_REAL_SIZE]
    pool_src = real or items
    near = [i for i in pool_src if want - 200 <= (i[1] or 0) <= want + 200]
    if near:
        pool = near
    else:
        below = [i for i in pool_src if 0 < (i[1] or 0) < want - 200]
        if not below:
            return None          # only oversized tiers (4K) -> caller falls back
        mx = max(i[1] for i in below)
        pool = [i for i in below if i[1] == mx]
    pool = sorted(pool, key=lambda x: ((x[2] or 0), (x[1] or 0)), reverse=True)
    return pool[0][0]


def _harvest_via_autoplay(first_vid, cookie=None, max_eps=300, idle_break=45, want_width=1920, on_episode=None):
    """Harvest every episode's m3u8 by letting the player auto-advance.

    Youku's player automatically switches to the next episode when the current
    one ends, so in one headless-CDP session we seek each episode to its end,
    wait for the player to fetch the next episode's stream and record it. This
    sidesteps the full-episode list which youku keeps client-side only.
    Every harvested episode is pushed to ``on_episode(dict)`` when provided
    (pipeline mode) and also returned in the final list.
    Returns (show_title, [{'seq','vid','title','m3u8'}, ...]) or None.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[YOUKU] Playwright not installed.")
        return None
    chrome = _find_chrome()
    hd_probe = dict(H)
    if cookie:
        hd_probe["Cookie"] = cookie
    profile = os.path.join(ROOT, "tmp", "youku_auto_profile")

    def _harvest_chrome_args(_port):
        return [chrome, "--remote-debugging-port=%d" % _port, "--user-data-dir=" + profile,
                "--headless=new", "--no-first-run", "--disable-popup-blocking",
                "--disable-blink-features=AutomationControlled",
                "--disable-crash-reporter", "--disable-breakpad", "--noerrdialogs",
                "--window-size=1400,950", "about:blank"]

    def _wait_ready(_port, tries=30):
        for _ in range(tries):
            time.sleep(0.5)
            try:
                if requests.get("http://127.0.0.1:%d/json/version" % _port, timeout=2).status_code == 200:
                    return True
            except Exception:
                pass
        return False

    os.makedirs(profile, exist_ok=True)
    port = _free_port()
    print("[YOUKU] Auto-advance harvest: headless Chrome (port %d)..." % port, flush=True)
    proc = _spawn_chrome(_harvest_chrome_args(port))
    eps = []
    show = "youku"
    try:
        ready = _wait_ready(port)
        if not ready:
            # a hard kill can leave a corrupted profile (singleton lock etc.):
            # reset it and retry once
            print("[YOUKU] Auto-advance: chrome not ready, resetting profile and retrying...", flush=True)
            try:
                proc.kill()
            except Exception:
                pass
            shutil.rmtree(profile, ignore_errors=True)
            os.makedirs(profile, exist_ok=True)
            port = _free_port()
            proc = _spawn_chrome(_harvest_chrome_args(port))
            ready = _wait_ready(port)
        if not ready:
            print("[YOUKU] Auto-advance: chrome not ready")
            return None
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % port)
            ctx = browser.contexts[0]
            _mute_page(ctx)
            if cookie:
                for ck in cookie.split("; "):
                    if "=" in ck:
                        try:
                            k, v = ck.split("=", 1)
                            ctx.add_cookies([{"name": k, "value": v, "domain": ".youku.com", "path": "/"}])
                        except Exception:
                            pass
            page = ctx.new_page()
            m3u8_seen = []
            m3u8_commit_idx = 0   # index into m3u8_seen at the last episode commit
            api_bodies = []  # playback API bodies (each contains its own episode's vid)
            audio_state = {"url": None}  # separate audio track (audio-only episodes)

            def on_resp(resp):
                try:
                    u = resp.url
                    low = u.lower()
                    if "mmstat" in u:
                        return
                    if ".m3u8" in low:
                        if u not in m3u8_seen:
                            m3u8_seen.append(u)
                    elif "acs.youku" in low or "un-acs.youku" in low or "appinfo" in low or "ups" in low:
                        if resp.status < 400:
                            try:
                                b = resp.text()[:800000]
                            except Exception:
                                return
                            if ".m3u8" in b and b not in api_bodies:
                                api_bodies.append(b)
                            if not audio_state["url"] and "#EXT-X-MEDIA:TYPE=AUDIO" in b:
                                au = _extract_audio_playlist(b)
                                if au:
                                    audio_state["url"] = au
                                    print("[YOUKU] separate audio track found", flush=True)
                except Exception:
                    pass

            page.on("response", on_resp)
            page.goto("https://v.youku.com/v_show/id_" + first_vid + ".html",
                      wait_until="domcontentloaded", timeout=40000)
            last_seq = 0
            seeked = False
            show_season = None     # e.g. "一" from "第一季"; None when title has no season
            pending_seq = 0       # episode we are waiting to commit
            pending_vid = ""
            pending_start = 0.0
            last_event = time.time()  # any commit/seek resets the idle clock
            deadline = time.time() + 60 * 40
            while len(eps) < max_eps and time.time() < deadline:
                time.sleep(2)
                try:
                    st = page.evaluate("""() => {
                        var v = document.querySelector('video');
                        var t = (document.title || '').split('-')[0].trim();
                        var m = t.match(/第(\\d+)集/);
                        return {title: t, seq: m ? parseInt(m[1]) : 0, dur: v ? (v.duration || 0) : 0,
                                cur: v ? (v.currentTime || 0) : 0, paused: v ? v.paused : true,
                                url: location.href};
                    }""")
                except Exception:
                    continue
                seq = st.get("seq") or 0
                # season roll-over detection. Primary: season name change in the
                # title (第一季 -> 第二季). Fallback: episode numbers reset
                # (第39集 -> 第1集 of the next season).
                t_season = None
                ms = re.search(r'第([一二三四五六七八九十百\d]+)季', st.get("title") or "")
                if ms:
                    t_season = ms.group(1)
                if show_season is not None and t_season is not None and t_season != show_season:
                    print("[YOUKU]   season boundary reached at %s, stopping" % (st.get("title") or "")[:40], flush=True)
                    break
                if last_seq > 0 and 0 < seq < last_seq:
                    print("[YOUKU]   season boundary reached at %s, stopping" % (st.get("title") or "")[:36], flush=True)
                    break
                # new episode detected -> enter pending state (wait for that
                # episode's playback API so we can pick the best quality)
                if seq > 0 and seq != last_seq and seq != pending_seq:
                    pending_seq = seq
                    pending_start = time.time()
                    try:
                        mm = re.search(r"/v_show/id_([A-Za-z0-9=]+)", page.url)
                        pending_vid = mm.group(1) if mm else ""
                    except Exception:
                        pending_vid = ""
                    last_event = time.time()
                # try to commit: matching API arrived, or timeout fallback
                if pending_seq and pending_seq != last_seq:
                    best = None
                    widths = []
                    if pending_vid:
                        for b in api_bodies:
                            if pending_vid in b:
                                items = _parse_quality_items(b)
                                widths = sorted(set(w for _, w, _ in items if w > 0))
                                best = _pick_quality_url(items, want=want_width)
                                if best:
                                    break
                    if best or (time.time() - pending_start > 8 and m3u8_seen):
                        title = st.get("title") or ("第%d集" % pending_seq)
                        if len(eps) == 0:
                            show = re.sub(r'\s*第?\s*\d+\s*集.*$', '', title).strip() or title
                            ms0 = re.search(r'第([一二三四五六七八九十百\d]+)季', title)
                            if ms0:
                                show_season = ms0.group(1)
                        # per-episode playlist snapshot: the player requests the
                        # episode's video AND audio playlists right after switching
                        cur_m3u8s = m3u8_seen[m3u8_commit_idx:]
                        m3u8_commit_idx = len(m3u8_seen)
                        # classify them: youku serves video and audio separately for
                        # some shows, and arrival order is not stable. Several
                        # playlists may carry _video_ (the ad block is one), so pick
                        # the biggest one = the actual episode.
                        vid_pl, aud_pl = None, None
                        vid_len = aud_len = 0
                        for cu in cur_m3u8s[:6]:
                            try:
                                ct = requests.get(cu, headers=hd_probe, timeout=15).text
                            except Exception:
                                continue
                            if "#EXTM3U" not in ct:
                                continue
                            if "_audio_" in ct:
                                if len(ct) > aud_len:
                                    aud_pl, aud_len = cu, len(ct)
                            elif "_video_" in ct:
                                if len(ct) > vid_len:
                                    vid_pl, vid_len = cu, len(ct)
                        if vid_pl:
                            print("[YOUKU]   ep%d playlists: video=%dKB audio=%dKB" % (
                                pending_seq, vid_len // 1024, aud_len // 1024), flush=True)
                        url = vid_pl or best or (cur_m3u8s[-1] if cur_m3u8s else None)
                        if not url:
                            continue
                        ep_item = {"seq": pending_seq, "vid": pending_vid, "title": title, "m3u8": url,
                                   "audio": aud_pl or audio_state["url"], "m3u8_all": cur_m3u8s}
                        eps.append(ep_item)
                        if on_episode:
                            try:
                                on_episode(dict(ep_item), show)
                            except Exception:
                                pass
                        print("[YOUKU]   ep%-3d %s %s -> %s" % (
                            pending_seq, title[:34],
                            ("[api %s]" % widths) if widths else "",
                            "HD" if best else "player-default"), flush=True)
                        last_seq = pending_seq
                        pending_seq = 0
                        seeked = False
                        last_event = time.time()
                elif seq == last_seq and last_seq > 0 and not seeked and st.get("dur", 0) > 10 and st.get("cur", 0) > 3:
                    # drive the current episode to its end -> auto-advance fires
                    try:
                        page.evaluate("""(d) => {
                            var v = document.querySelector('video');
                            if (!v) return;
                            v.muted = true;
                            try { v.currentTime = Math.max(0, d - 3); } catch (e) {}
                            try { v.play(); } catch (e) {}
                        }""", st["dur"])
                        seeked = True
                        last_event = time.time()
                        print("[YOUKU]     -> seek end (advance to next)", flush=True)
                    except Exception:
                        pass
                elif seq == last_seq and last_seq > 0 and not seeked and st.get("dur", 0) > 10 and st.get("cur", 0) <= 3 and st.get("paused"):
                    # video not playing yet - kick it so it can reach seek range
                    try:
                        page.evaluate("""() => {
                            var v = document.querySelector('video');
                            if (v) { v.muted = true; v.play().catch(function(){}); }
                        }""")
                    except Exception:
                        pass
                elif time.time() - last_event > idle_break:
                    # nothing happened for a while -> series finished or stuck
                    print("[YOUKU]   idle %.0fs, stopping (collected %d)" % (idle_break, len(eps)), flush=True)
                    break
            browser.close()
    finally:
        try:
            proc.terminate()
            time.sleep(1)
            proc.kill()
        except Exception:
            pass
    if not eps:
        print("[YOUKU] Auto-advance: nothing harvested")
        return None
    return (show or "youku", eps)


def _capture_episode_batch(first_vid, cookie=None, max_eps=200, page_wait=16):
    """Single headless-CDP session: walk the 'next episode' chain starting at
    first_vid, capturing every episode's m3u8 + title. Returns
    (show_title, [{'vid','seq','title','m3u8'}, ...]) or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[YOUKU] Playwright not installed.")
        return None
    chrome = _find_chrome()
    profile = os.path.join(ROOT, "tmp", "youku_batch_profile")
    os.makedirs(profile, exist_ok=True)
    port = _free_port()
    print("[YOUKU] Batch: launching headless Chrome (port %d)..." % port, flush=True)
    proc = _spawn_chrome([chrome, "--remote-debugging-port=%d" % port, "--user-data-dir=" + profile,
                          "--headless=new", "--no-first-run", "--disable-popup-blocking",
                          "--disable-blink-features=AutomationControlled",
                          "--disable-crash-reporter", "--disable-breakpad", "--noerrdialogs",
                          "--window-size=1400,950", "about:blank"])
    eps = []
    show = "youku"
    try:
        ready = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                if requests.get("http://127.0.0.1:%d/json/version" % port, timeout=2).status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
        if not ready:
            print("[YOUKU] Batch: chrome not ready")
            return None
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % port)
            ctx = browser.contexts[0]
            _mute_page(ctx)
            if cookie:
                for ck in cookie.split("; "):
                    if "=" in ck:
                        try:
                            k, v = ck.split("=", 1)
                            ctx.add_cookies([{"name": k, "value": v, "domain": ".youku.com", "path": "/"}])
                        except Exception:
                            pass
            page = ctx.new_page()
            cur = first_vid
            seen = set()
            while cur and len(eps) < max_eps:
                if cur in seen:
                    print("[YOUKU] Batch: loop detected at %s, stopping" % cur[:16], flush=True)
                    break
                seen.add(cur)
                m3u8_direct = []
                m3u8_api = []

                def on_resp(resp):
                    try:
                        u = resp.url
                        low = u.lower()
                        if "mmstat" in u:
                            return
                        if ".m3u8" in low:
                            if u not in m3u8_direct:
                                m3u8_direct.append(u)
                        elif "acs.youku" in low or "get.json" in low or "ups" in low or "appinfo" in low:
                            if resp.status < 400:
                                try:
                                    b = resp.text()[:400000]
                                except Exception:
                                    return
                                m3 = re.findall(r'https?://[^"\\\s]+?\.m3u8[^"\\\s]*', b)
                                if m3:
                                    m3u8_api.extend(m3)
                    except Exception:
                        pass

                page.on("response", on_resp)
                try:
                    page.goto("https://v.youku.com/v_show/id_" + cur + ".html",
                              wait_until="domcontentloaded", timeout=40000)
                except Exception as e:
                    print("[YOUKU]   goto failed: " + str(e)[:80], flush=True)
                    break
                # same interaction as single-episode capture: click play +
                # force video.play() so the player actually fetches the stream
                got = False
                clicked = False
                for _ in range(max(1, page_wait // 2)):
                    time.sleep(2)
                    if not clicked:
                        try:
                            btn = page.query_selector("video, .play-btn, [class*=play], [class*=Play]")
                            if btn:
                                btn.click(force=True)
                                clicked = True
                                print("[YOUKU]     clicked play", flush=True)
                        except Exception:
                            pass
                    try:
                        page.evaluate("""() => {
                            var v = document.querySelector('video');
                            if (v && v.paused) { v.muted = true; v.play().catch(function(){}); }
                        }""")
                    except Exception:
                        pass
                    if m3u8_direct or m3u8_api:
                        got = True
                        break
                title = "ep" + str(len(eps) + 1)
                nxt = None
                try:
                    js = page.evaluate("""() => {
                        var t = (document.title || '').split('-')[0].trim() || '';
                        var cands = [];
                        var seen = {};
                        document.querySelectorAll('a[href*="vid="]').forEach(function(a) {
                            var m = (a.href || '').match(/[?&]vid=([A-Za-z0-9=]+)/);
                            if (!m) return;
                            var v = m[1];
                            if (seen[v]) return;
                            seen[v] = 1;
                            var label = ((a.getAttribute('aria-label') || '') + ' ' + (a.textContent || '')).trim();
                            cands.push({vid: v, label: label.slice(0, 48)});
                        });
                        return {title: t, cands: cands};
                    }""")
                    title = js.get("title") or title
                    cands = js.get("cands") or []
                    # pick next episode: skip current vid, skip VIP ads/recommends
                    for c in cands:
                        v, lab = c.get("vid"), c.get("label", "")
                        if v == cur:
                            continue
                        if "VIP" in lab or "会员" in lab or "广告" in lab or len(lab) > 40:
                            continue
                        nxt = v
                        break
                except Exception:
                    pass
                try:
                    page.remove_listener("response", on_resp)
                except Exception:
                    pass
                if not got:
                    print("[YOUKU]   no stream on %s (%s), stopping chain" % (cur[:16], title[:26]), flush=True)
                    break
                # prefer the m3u8 the player actually fetched; else last API one
                url = m3u8_direct[-1] if m3u8_direct else (m3u8_api[-1] if m3u8_api else None)
                if not url:
                    print("[YOUKU]   no usable m3u8 on %s, stopping" % cur[:16], flush=True)
                    break
                seq = len(eps) + 1
                eps.append({"vid": cur, "seq": seq, "title": title, "m3u8": url})
                print("[YOUKU]   ep%-3d %-36s stream ok%s" % (seq, title[:36],
                      ("  next=" + nxt[:12]) if nxt else "  (end)"), flush=True)
                if seq == 1:
                    show = re.sub(r'\s*第?\s*\d+\s*集.*$', '', title).strip() or title
                cur = nxt
            browser.close()
    finally:
        try:
            proc.terminate()
            time.sleep(1)
            proc.kill()
        except Exception:
            pass
    if not eps:
        print("[YOUKU] Batch: no episodes captured")
        return None
    return (show or "youku", eps)


def _download_worker(q, holder, cookie, done_counter, results, results_lock, failed):
    """Consumer: pull harvested episodes off the queue and download them."""
    h_dl = dict(H)
    h_dl["Cookie"] = cookie
    while True:
        ep = q.get()
        if ep is None:
            q.task_done()
            return
        try:
            # output dir is created as soon as the harvester knows the show name
            if holder.get("sdir") is None:
                holder["event"].wait(timeout=60)
            sdir = holder.get("sdir") or os.path.join(ROOT, "output")
            ep_seq = ep.get("seq") or 0
            safe = re.sub(r'[<>:"/\\|?*]', '_', ep["title"])[:60].strip(" _") or ("ep%d" % ep_seq)
            fp = os.path.join(sdir, "youku_%s_%s.mp4" % (safe, time.strftime("%Y%m%d_%H%M%S")))
            result = None
            # defensive: swap if we somehow ended up with the audio playlist, and
            # pick the BIGGEST candidate playlist of each kind (ad playlists are tiny)
            try:
                _cands = [ep["m3u8"]] + [c for c in (ep.get("m3u8_all") or []) if c != ep["m3u8"]]
                _v, _vl, _a, _al = None, 0, ep.get("audio"), 0
                for cu in _cands[:6]:
                    try:
                        _ct = requests.get(cu, headers=h_dl, timeout=15).text
                    except Exception:
                        continue
                    if "#EXTM3U" not in _ct:
                        continue
                    if "_audio_" in _ct:
                        if len(_ct) > _al:
                            _a, _al = cu, len(_ct)
                    elif "_video_" in _ct:
                        if len(_ct) > _vl:
                            _v, _vl = cu, len(_ct)
                if _v:
                    if _v != ep["m3u8"]:
                        print("[YOUKU]   picked full video playlist for ep%d (%dKB)" % (ep_seq, _vl // 1024), flush=True)
                    ep["m3u8"] = _v
                if _a:
                    ep["audio"] = _a
            except Exception:
                pass
            for attempt in range(2):
                url = ep["m3u8"]
                if attempt == 1 and ep.get("vid"):  # m3u8 may have expired - re-capture
                    print("[YOUKU]   m3u8 expired for ep%d, re-capturing..." % ep_seq, flush=True)
                    info = _capture_cdp(ep["vid"], cookie, wait_s=60)
                    if not info or not info.get("stream_url"):
                        break
                    url = info["stream_url"]
                elif attempt == 1:
                    break
                print("[YOUKU]   downloading ep%d %s..." % (ep_seq, ep["title"][:40]), flush=True)
                if ".m3u8" in url:
                    try:
                        vtext = requests.get(url, headers=h_dl, timeout=15).text
                    except Exception:
                        vtext = ""
                    ffmpeg_handles_audio = ("#EXT-X-MAP:" in vtext) or ("#EXT-X-STREAM-INF" in vtext) or ("#EXT-X-MEDIA:" in vtext)
                    result = download_m3u8(url, fp, h_dl,
                                           audio_url=(ep.get("audio") if ffmpeg_handles_audio else None))
                    if result and ep.get("audio") and not ffmpeg_handles_audio:
                        # plain TS video + separate audio: mux manually
                        afp = fp + ".audio.mp4"
                        try:
                            if download_m3u8(ep["audio"], afp, h_dl):
                                merged = _merge_av(result, afp, fp + ".mux.mp4")
                                if merged:
                                    try:
                                        os.remove(result)
                                    except Exception:
                                        pass
                                    os.replace(merged, fp)
                                    result = fp
                        except Exception as e:
                            print("[YOUKU]   audio handling error: %s" % str(e)[:80], flush=True)
                        finally:
                            for p in (afp, fp + ".mux.mp4"):
                                if os.path.exists(p):
                                    try:
                                        os.remove(p)
                                    except Exception:
                                        pass
                else:
                    result = download_direct(url, fp, h_dl)
                if result:
                    break
            with results_lock:
                done_counter[0] += 1
                if result:
                    results.append(result)
                else:
                    failed.append(ep_seq)
                n_done, n_failed = done_counter[0], len(failed)
            total = holder.get("total", 0)
            if result:
                print("[YOUKU]   [%d/%s] saved ep%d" % (n_done, total or "?", ep_seq), flush=True)
            else:
                print("[YOUKU]   [%d/%s] FAILED ep%d, skipped" % (n_done, total or "?", ep_seq), flush=True)
        except Exception as e:
            print("[YOUKU]   worker error on ep: %s" % str(e)[:100], flush=True)
            with results_lock:
                done_counter[0] += 1
                failed.append(ep.get("seq"))
        finally:
            q.task_done()


def download_batch(link, out_dir=None, cookie=None, workers=4):
    """Pipeline batch download of the whole series.

    The harvester (headless-CDP autoplay walk) emits each episode as soon as
    its best-quality m3u8 is known; ``workers`` consumer threads pull them off
    a queue and download/merge concurrently, so harvesting and downloading
    overlap. Returns the list of saved files.
    """
    cookie = cookie or load_cookie()
    vid = parse_url(link)
    if not vid:
        print("[YOUKU] Cannot parse URL")
        return None
    print("[YOUKU] Batch (pipeline, %d workers) for video: %s" % (workers, vid))
    out_dir = out_dir or os.path.join(ROOT, "output")
    q = queue.Queue()
    holder = {"sdir": None, "event": threading.Event(), "total": 0, "seen": set()}
    results = []
    failed = []
    skipped = []
    lock = threading.Lock()
    done_counter = [0]

    def on_episode(ep, show):
        if not holder["event"].is_set():
            sdir = os.path.join(out_dir, re.sub(r'[<>:"/\\|?*]', '_', (show or "youku"))[:60].strip(" _") or "youku")
            os.makedirs(sdir, exist_ok=True)
            holder["sdir"] = sdir
            holder["event"].set()
            # index episodes already on disk so a re-run only downloads what is missing
            try:
                for fn in os.listdir(sdir):
                    mm = re.search(r"第(\d+)集", fn)
                    if mm:
                        holder["seen"].add(int(mm.group(1)))
            except Exception:
                pass
            print("[YOUKU] output dir: %s\\ (%d episode(s) already present)" % (sdir, len(holder["seen"])), flush=True)
        if ep.get("seq") in holder["seen"]:
            skipped.append(ep.get("seq"))
            print("[YOUKU]   ep%d already downloaded, skipped" % ep["seq"], flush=True)
            return
        q.put(ep)

    threads = [threading.Thread(target=_download_worker,
                                args=(q, holder, cookie, done_counter, results, lock, failed),
                                daemon=True) for _ in range(max(1, workers))]
    for t in threads:
        t.start()

    # producer: harvest episodes; each one is queued the moment it is known
    batch = _harvest_via_autoplay(vid, cookie, on_episode=on_episode)
    if batch:
        holder["total"] = len(batch[1])
        print("[YOUKU] harvest done: %d episodes found" % len(batch[1]), flush=True)
    else:
        print("[YOUKU] Auto-advance harvest failed", flush=True)
    for _ in range(max(1, workers)):
        q.put(None)  # one sentinel per worker
    for t in threads:
        t.join()
    sdir = holder.get("sdir") or os.path.join(out_dir, "youku_batch")
    if not batch:
        return None
    print("\n[YOUKU] Batch done: %d/%d downloaded%s%s -> %s" % (
        len(results), len(batch[1]),
        (" (%d failed)" % len(failed)) if failed else "",
        (" (%d skipped)" % len(skipped)) if skipped else "", sdir))
    return results


def download(link, out_dir=None, cookie=None, download_all=False):
    cookie = cookie or load_cookie()
    if download_all:
        return download_batch(link, out_dir, cookie)
    if cookie: print("[YOUKU] Using saved login cookie")
    print("[YOUKU] Input: " + link)
    vid = parse_url(link)
    if not vid: print("[YOUKU] Cannot parse URL"); return None
    print("[YOUKU] Video ID: " + vid)
    use_firefox = "--firefox" in sys.argv
    # CDP mode first: manually-spawned real Chrome -> no automation detection,
    # no captcha. Fall back to the classic Playwright browser window.
    info = None
    if not use_firefox:
        try:
            info = _capture_cdp(vid, cookie)
        except Exception as e:
            print("[YOUKU] CDP mode failed, falling back: " + str(e)[:100])
    if not info:
        print("[YOUKU] Falling back to classic Playwright window...")
        info = get_video_info(vid, cookie, use_firefox=use_firefox)
    if not info: return None
    print("[YOUKU] Title: " + info["title"])
    stream = info.get("stream_url","")
    if not stream: print("[YOUKU] No stream URL"); return None
    out_dir = out_dir or os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]','_',info["title"])[:50]
    fp = os.path.join(out_dir, "youku_" + safe + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4")
    h_dl = dict(H); h_dl["Cookie"] = cookie
    if ".m3u8" in stream: result = download_m3u8(stream, fp, h_dl)
    else: result = download_direct(stream, fp, h_dl)
    if result: print("[YOUKU] Saved: " + result)
    else: print("[YOUKU] Failed")
    return result

if __name__ == "__main__":
    use_firefox = "--firefox" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    link = args[0] if args else input("Youku link: ").strip()
    download(link)
