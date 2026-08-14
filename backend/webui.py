# -*- coding: utf-8 -*-
"""Web UI for Multi-Platform Downloader - v2.2"""

import os, sys, json, time, queue, threading, re, glob as _glob, requests, subprocess
from flask import Flask, render_template, request, jsonify, send_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TASK_FILE = os.path.join(ROOT, "logs", "tasks.json")

def _load_tasks():
    if os.path.exists(TASK_FILE):
        try:
            with open(TASK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def _save_tasks():
    os.makedirs(os.path.dirname(TASK_FILE), exist_ok=True)
    # Only keep running + recent done tasks
    clean = {}
    now = time.time()
    for tid, t in TASKS.items():
        if t.get("status") == "running":
            clean[tid] = t
        elif t.get("status") in ("done", "error") and now - t.get("_updated", 0) < 600:
            clean[tid] = t
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)

TASKS = _load_tasks()
TASKS = {int(k): v for k, v in TASKS.items()}
TASK_ID = max(TASKS.keys()) if TASKS else 0

# Thread references live OUTSIDE TASKS so task dicts stay JSON-serializable
THREADS = {}

app = Flask(__name__, template_folder=os.path.join(ROOT, "frontend", "templates"))
VERSION = "2.7"

PLATFORMS = {
    "douyin": ["douyin.com", "iesdouyin.com"],
    "xhs": ["xiaohongshu.com", "xhslink.com"],
    "kuaishou": ["kuaishou.com", "kuaishou"],
    "bilibili": ["bilibili.com", "b23.tv"],
    "youku": ["youku.com", "v.youku.com"],
    "tencent": ["v.qq.com"],
    "dushu": ["dushu365.com"],
    "ximalaya": ["ximalaya.com"],
    "wangyiyun": ["music.163.com"],
}

def _build_cli_cmd(url, platform, flags=None, total=0):
    """Build equivalent CLI command for a download task."""
    flags = flags or {}
    parts = ["python run.py", url]
    batch = flags.get("all") or platform in ("ximalaya", "wangyiyun") or total > 1
    if batch:
        parts.append("--all")
    if flags.get("login"):
        parts.append("--login")
    if flags.get("start_from", 1) > 1:
        parts.append("--start-from " + str(flags.get("start_from", 1)))
    if flags.get("to"):
        parts.append("--to " + str(flags.get("to")))
    if flags.get("tracks"):
        parts.append("--tracks " + str(flags.get("tracks")))
    return " ".join(parts)


def _get_task_name(url, platform):
    name, _ = _get_url_info(url, platform)
    return name


def _get_url_info(url, platform):
    try:
        if platform == "bilibili":    return _get_bili_info(url)
        if platform == "wangyiyun":   return _get_wyy_info(url)
        if platform == "ximalaya":    return _get_xm_info(url)
        if platform == "dushu":       return _get_dushu_info(url)
        if platform == "douyin":      return ("douyin_video", 0)
        if platform == "xhs":         return _get_xhs_info(url)
        if platform == "kuaishou":    return ("kuaishou_video", 0)
        return (platform, 0)
    except: return (platform, 0)


def _get_bili_info(url):
    from platforms import bili
    if "b23.tv" in url:
        url = bili.get_redirect(url) or url
    p = bili.parse_url(url)
    if not p: return ("bilibili_video", 0)
    if p["type"] in ("ep", "ss"):
        info = bili.get_bangumi_info(ep_id=p["id"] if p["type"]=="ep" else None,
                                     ss_id=p["id"] if p["type"]=="ss" else None)
        if info:
            return (info.get("title","")[:60], len(info.get("all_episodes",[])))
        return ("bilibili_bangumi", 0)
    else:
        info = bili.get_video_info(p["id"])
        if info:
            pages = info.get("pages", [])
            total = len(pages) if len(pages) > 1 else (1 if pages else 0)
            return (info.get("title","bilibili")[:60], total)
        return ("bilibili_video", 0)


def _get_wyy_info(url):
    from platforms import wangyiyun as wyy
    parsed = wyy.parse_url(url)
    if not parsed: return ("wangyiyun", 0)
    ptype, pid = parsed
    if ptype == "toplist": return ("NetEase Charts", 0)
    if ptype == "discover_playlist": return ("NetEase Discover", 0)
    if ptype == "song":
        session = wyy._create_session()
        info = wyy.get_song_info(pid, session)
        if info:
            name = info.get("title","")
            artists = info.get("artists","")
            display = name + " - " + artists if artists else name
            return (display[:80], 0)
        return ("wangyiyun_song", 0)
    if ptype == "playlist":
        session = wyy._create_session()
        tracks = wyy.get_playlist_tracks(pid, session)
        name = wyy._get_batch_name("playlist", pid, session) or "Playlist"
        return (name[:60], len(tracks))
    if ptype == "album":
        session = wyy._create_session()
        tracks = wyy.get_album_tracks(pid, session)
        name = wyy._get_batch_name("album", pid, session) or "Album"
        return (name[:60], len(tracks))
    if ptype == "artist":
        session = wyy._create_session()
        name = wyy._get_batch_name("artist", pid, session) or "Artist"
        return (name[:60], 0)
    return ("wangyiyun", 0)


def _get_xm_info(url):
    from platforms import xm
    parsed = xm.parse_url(url)
    if not parsed:
        if url.strip().isdigit(): parsed = ("track", None, url.strip())
        else: return ("ximalaya", 0)
    ptype = parsed[0]
    if ptype == "album" or (ptype == "track" and len(parsed) > 2 and parsed[1]):
        album_id = parsed[1] if parsed[1] else parsed[2]
        name = xm._get_album_name(album_id) or "Album"
        tracks = xm.get_album_tracks(album_id)
        return (name[:60], len(tracks))
    elif ptype == "track":
        track_id = parsed[2] if len(parsed) > 2 else parsed[1]
        info = xm.get_track_info(track_id)
        if info: return (info.get("title","ximalaya")[:60], 0)
        return ("ximalaya_track", 0)
    return ("ximalaya", 0)


def _get_dushu_info(url):
    from platforms import dushu
    parsed = dushu.parse_url_type(url)
    if not parsed: return ("dushu365", 0)
    pt, id1 = parsed[0], parsed[1]
    if pt == "course":
        programs = dushu.get_course_programs(id1)
        name = "dushu_course"
        if programs:
            name = programs[0].get("albumName","") or name
            return (name[:60], len(programs))
        return (name[:60], 0)
    elif pt == "book":
        info = dushu.get_page_info("book", id1, None)
        if info: return (info.get("title","dushu365")[:60], 0)
        return ("dushu365_book", 0)
    return ("dushu365", 0)


def _get_xhs_info(url):
    try:
        from platforms import xhs
        if "xhslink.com" in url:
            full_url = xhs.get_redirect_url(url)
            if full_url: url = full_url
        note_id = xhs.extract_note_id(url)
        if note_id: return ("xhs_" + note_id[:12], 0)
        return ("xiaohongshu", 0)
    except: return ("xiaohongshu", 0)



def detect_platform(url):
    url = url.split("#")[0]
    for name, domains in PLATFORMS.items():
        for d in domains:
            if d in url.lower():
                return name
    return None

def run_download(task_id, url, flags):
    global TASKS
    platform = detect_platform(url)
    name = platform + "_" + str(int(time.time()))
    try: name = _get_task_name(url, platform)
    except: pass
    TASKS[task_id]["status"] = "running"
    TASKS[task_id]["name"] = name
    TASKS[task_id]["platform"] = platform
    TASKS[task_id]["_updated"] = time.time()
    _save_tasks()
    def cb(data):
        if data.get("event") == "init":
            TASKS[task_id]["total"] = data.get("total", 0)
            quality = data.get("quality", "")
            if quality:
                TASKS[task_id]["name"] = TASKS[task_id]["name"] + " [" + quality + "]"
            if TASKS[task_id]["total"] > 0:
                TASKS[task_id]["name"] = TASKS[task_id]["name"] + " (" + str(TASKS[task_id]["total"]) + " eps)"
            TASKS[task_id]["_updated"] = time.time()
        elif data.get("event") == "progress":
            fp = data.get("file", "")
            if fp and fp not in TASKS[task_id]["files"]:
                TASKS[task_id]["files"].append(fp)
                TASKS[task_id]["count"] = len(TASKS[task_id]["files"])
            # Update quality in task name (first file's quality)
            quality = data.get("quality", "")
            if quality and "[{0}]".format(quality) not in TASKS[task_id]["name"]:
                TASKS[task_id]["name"] = TASKS[task_id]["name"].split(" (")[0] + " [{0}]".format(quality)
                if TASKS[task_id]["total"] > 0:
                    TASKS[task_id]["name"] += " (" + str(TASKS[task_id]["total"]) + " eps)"
            # Clear byte-level progress since this file is done
            TASKS[task_id]["dl_bytes"] = 0
            TASKS[task_id]["dl_total"] = 0
            TASKS[task_id]["retry_track"] = ""
            TASKS[task_id]["retry_wait"] = 0
            TASKS[task_id]["_updated"] = time.time()
        elif data.get("event") == "retry":
            TASKS[task_id]["retry_track"] = data.get("track", "")
            TASKS[task_id]["retry_wait"] = data.get("wait", 0)
            TASKS[task_id]["_updated"] = time.time()
            return  # skip _save_tasks for retry events
        elif data.get("event") == "download_progress":
            TASKS[task_id]["dl_bytes"] = data.get("current", 0)
            TASKS[task_id]["dl_total"] = data.get("total", 0)
            TASKS[task_id]["_updated"] = time.time()
            return  # skip _save_tasks for byte-level events (too frequent)
        elif data.get("event") == "done":
            TASKS[task_id]["status"] = "done"
            TASKS[task_id]["downloaded"] = data.get("downloaded", 0)
            TASKS[task_id]["dl_bytes"] = 0
            TASKS[task_id]["dl_total"] = 0
            quality = data.get("quality", "")
            if quality and "[{0}]".format(quality) not in TASKS[task_id]["name"]:
                TASKS[task_id]["name"] = TASKS[task_id]["name"].split(" (")[0] + " [{0}]".format(quality)
                if TASKS[task_id]["total"] > 0:
                    TASKS[task_id]["name"] += " (" + str(TASKS[task_id]["total"]) + " eps)"
            TASKS[task_id]["_updated"] = time.time()
        _save_tasks()
        # Check for pause
        while TASKS[task_id].get("status") == "paused":
            time.sleep(1)
            TASKS[task_id]["_updated"] = time.time()
        if TASKS[task_id].get("status") == "cancelled":
            raise Exception("Task cancelled")

    try:
        platform = detect_platform(url)

        if platform == "ximalaya":
            from platforms import xm
            if flags.get("login"):
                try:
                    from playwright.sync_api import sync_playwright
                except ImportError:
                    TASKS[task_id]["status"] = "error"
                    TASKS[task_id]["output"] = "Playwright not installed"
                    TASKS[task_id]["_updated"] = time.time()
                    _save_tasks()
                    return
                album_id = None
                am = re.search(r"/album/(\d+)", url)
                if am: album_id = str(am.group(1))
                profile_dir = os.path.join(ROOT, "tmp", f"xm_login_{int(time.time())}")
                os.makedirs(profile_dir, exist_ok=True)
                try:
                  with sync_playwright() as p:
                    # Try persistent context, fallback to regular launch
                    ctx = None
                    for attempt in range(2):
                        try:
                            ctx = p.chromium.launch_persistent_context(
                                user_data_dir=profile_dir, headless=False, channel="chrome",
                                args=["--start-maximized", "--disable-blink-features=AutomationControlled", "--no-first-run"],
                                ignore_default_args=["--enable-automation"], viewport=None)
                            break
                        except Exception as e2:
                            if attempt == 0:
                                print(f"[XM] Persistent context failed ({e2}), trying regular launch...", flush=True)
                                import shutil
                                try: shutil.rmtree(profile_dir, ignore_errors=True)
                                except: pass
                    if ctx is None:
                        browser = p.chromium.launch(headless=False, channel="chrome",
                            args=["--start-maximized", "--disable-blink-features=AutomationControlled", "--no-sandbox"])
                        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
                    page = ctx.new_page()
                    page.goto("https://www.ximalaya.com/", wait_until="domcontentloaded", timeout=30000)
                    # Wait for user to confirm login on frontend first
                    TASKS[task_id]["status"] = "waiting_login"
                    TASKS[task_id]["_updated"] = time.time()
                    _save_tasks()
                    print("[XM] Waiting for user to confirm login...", flush=True)
                    while TASKS[task_id].get("status") == "waiting_login":
                        time.sleep(1)
                        if TASKS[task_id].get("status") == "cancelled":
                            print("[XM] Task cancelled, closing browser...", flush=True)
                            ctx.close()
                            return
                    if TASKS[task_id].get("status") != "login_confirmed":
                        print("[XM] Login not confirmed, closing browser...", flush=True)
                        ctx.close()
                        return
                    print("[XM] Login confirmed, starting download...", flush=True)
                    TASKS[task_id]["status"] = "running"
                    TASKS[task_id]["_updated"] = time.time()
                    _save_tasks()
                    # Get tracks (API first, then scrape page if needed)
                    tracks = xm.get_album_tracks(album_id) if album_id else []
                    if album_id:
                        try:
                            r_check = requests.get(f"https://www.ximalaya.com/revision/album?albumId={album_id}",
                                headers=xm.H, timeout=10)
                            total_api = r_check.json().get("data", {}).get("tracksInfo", {}).get("trackTotalCount", 0)
                        except: total_api = 0
                        if total_api > len(tracks):
                            page_tracks = xm._scrape_tracks_from_page(page, url, total_api)
                            if page_tracks:
                                seen_ids = {t["track_id"] for t in tracks}
                                for pt in page_tracks:
                                    if pt["track_id"] not in seen_ids:
                                        seen_ids.add(pt["track_id"])
                                        tracks.append(pt)
                    if not tracks:
                        TASKS[task_id]["status"] = "error"
                        TASKS[task_id]["output"] = "No tracks found"
                        TASKS[task_id]["_updated"] = time.time()
                        _save_tasks()
                        ctx.close()
                        return
                    total = len(tracks)
                    eff_total = xm._count_effective(tracks, flags.get("start_from", 1), flags.get("to"), flags.get("tracks", ""))
                    if cb:
                        cb({"event": "init", "total": eff_total})
                    TASKS[task_id]["total"] = eff_total
                    TASKS[task_id]["name"] = TASKS[task_id]["name"] + " (" + str(eff_total) + " eps)"
                    # Create output directory
                    album_name = xm._get_album_name(album_id) if album_id else ""
                    output = os.path.join(ROOT, "output")
                    if album_name:
                        safe_name = re.sub(r'[<>:"/\\|?*]', "_", album_name)[:40].strip(" _")
                        output = os.path.join(output, safe_name)
                    os.makedirs(output, exist_ok=True)
                    results = []
                    audio_urls = {}

                    def on_response(resp):
                        ct = (resp.headers.get("content-type") or "").lower()
                        u = resp.url
                        uq = u.split("?")[0].lower()
                        is_audio = (
                            "audio" in ct or "mpeg" in ct or "mp2t" in ct or
                            ".m4a" in uq or ".mp3" in uq or ".aac" in uq or ".flac" in uq or
                            ".m3u8" in uq or ".ts" in uq or ".ogg" in uq or ".wav" in uq or
                            "xmcdn.com" in u or "audio.xmcdn" in u or "audiopay" in u
                        )
                        if is_audio and u not in audio_urls:
                            try: cl = int(resp.headers.get("content-length","0"))
                            except: cl = 0
                            # Don't require content-length - paid audio CDN often omits it
                            audio_urls[u] = max(cl, 1)
                            print(f"[XM] Captured: {u[:80]}... ({cl/1024:.0f} KB)" if cl else f"[XM] Captured: {u[:80]}...", flush=True)
                    page.on("response", on_response)
                    # Parse track filter
                    track_set = None
                    tracks_str = flags.get("tracks", "")
                    track_to = flags.get("to")
                    if tracks_str:
                        try:
                            track_set = set(int(x.strip()) for x in tracks_str.split(",") if x.strip().isdigit())
                        except: pass
                    for i, t in enumerate(tracks):
                        if TASKS[task_id].get("status") == "cancelled":
                            print("[XM]   Task cancelled, stopping...", flush=True)
                            ctx.close()
                            return
                        idx = i + 1
                        if idx < flags.get("start_from", 1):
                            continue
                        if track_to and idx > track_to:
                            break
                        if track_set is not None and idx not in track_set:
                            continue
                        # Match CLI behavior: per-track 24h retry budget (Ximalaya rate-limits
                        # the play API after ~150 downloads, needs long backoff to recover)
                        budget = xm._RetryBudget()
                        while True:
                            print(f"\n[XM] [{i+1}/{total}] Track {t['track_id']}: {t['title'][:40]}", flush=True)
                            audio_urls.clear()
                            page.goto(f"https://www.ximalaya.com/sound/{t['track_id']}", wait_until="domcontentloaded", timeout=15000)
                            page.wait_for_timeout(2000)
                            clicked = False
                            for sel in [".play-btn", "[class*=\"play-btn\"]", "[class*=\"playButton\"]",
                                        "[class*=\"sound-play\"]", ".sound-operate button",
                                        "button[class*=\"play\"]", ".sound-play", "[class*=\"play\"]"]:
                                try:
                                    btn = page.query_selector(sel)
                                    if btn:
                                        btn.scroll_into_view_if_needed(timeout=2000)
                                        btn.click()
                                        print(f"[XM]   clicked: {sel}", flush=True)
                                        clicked = True
                                        break
                                except: pass
                            if not clicked:
                                try:
                                    page.evaluate("""() => {
                                        var sels = ['[class*="play-btn"]','[class*="playButton"]','.play-btn','[class*="sound-play"]','button[class*="play"]','.sound-play'];
                                        for (var i = 0; i < sels.length; i++) {
                                            var el = document.querySelector(sels[i]);
                                            if (el) { el.scrollIntoView({block:'center'}); el.click(); return 'ok'; }
                                        }
                                        var a = document.querySelector('audio,[class*=player]');
                                        if (a) { a.click(); return 'audio-fallback'; }
                                        return 'none';
                                    }""")
                                    print("[XM]   JS click fallback", flush=True)
                                except: pass
                            # Wait for audio response OR an <audio> element with a real src
                            for _ in range(10):
                                page.wait_for_timeout(1000)
                                if audio_urls:
                                    break
                                try:
                                    js_url = page.evaluate("()=>{var a=document.querySelector('audio');return a&&a.src&&a.src.indexOf('http')===0?a.src:null}")
                                    if js_url:
                                        audio_urls.setdefault(js_url, 100000)
                                        print(f"[XM]   JS extracted: {js_url[:80]}", flush=True)
                                        break
                                except: pass
                            downloaded_ok = False
                            last_fail = ""
                            if audio_urls:
                                # Prefer real audio files over generic xmcdn assets (JS/CSS have no audio ext)
                                audio_cands = [u for u in audio_urls if re.search(r'\.(m4a|mp3|aac|flac|m3u8|ts|ogg|wav)(\?|$)', u.split("?")[0].lower())]
                                m3u8s = [u for u in audio_cands if ".m3u8" in u.split("?")[0].lower()]
                                if m3u8s:
                                    au = m3u8s[0]
                                elif audio_cands:
                                    au = max(audio_cands, key=audio_urls.get)
                                else:
                                    au = max(audio_urls, key=audio_urls.get)
                                print(f"[XM]   downloading {au[:80]}...", flush=True)
                                safe_fn = lambda s: re.sub(r'[<>:"/\\|?*]', "_", s)[:60].strip(" _")
                                fn = "xm_" + safe_fn(t["title"]) + "_" + time.strftime("%Y%m%d_%H%M%S") + ".m4a"
                                fp = os.path.join(output, fn)
                                sz = 0
                                try:
                                    h = dict(xm.H)
                                    try:
                                        cks = [f"{c['name']}={c['value']}" for c in ctx.cookies() if "ximalaya" in c.get("domain", "")]
                                        if cks: h["Cookie"] = "; ".join(cks)
                                    except: pass
                                    if ".m3u8" in au.split("?")[0].lower():
                                        ff = os.path.join(ROOT, "bin", "ffmpeg.exe")
                                        # http_persistent 0 avoids 416 range errors on HLS CDN connection reuse
                                        r = subprocess.run([ff, "-y", "-loglevel", "error", "-http_persistent", "0",
                                                            "-i", au, "-c", "copy", fp],
                                                           capture_output=True, timeout=600)
                                        if os.path.exists(fp): sz = os.path.getsize(fp)
                                        if r.returncode != 0 or sz <= 10000 or not xm._is_valid_audio(fp):
                                            last_fail = "HLS merge failed"
                                            print(f"[XM]   HLS merge failed: {r.stderr.decode('utf-8','ignore')[-120:]}", flush=True)
                                        else:
                                            downloaded_ok = True
                                    else:
                                        ar = requests.get(au, headers=h, stream=True, timeout=120)
                                        st = ar.status_code
                                        ct_r = ar.headers.get("content-type", "")
                                        with open(fp, "wb") as wf:
                                            for chunk in ar.iter_content(1024*1024):
                                                if chunk: wf.write(chunk)
                                        sz = os.path.getsize(fp)
                                        if st != 200:
                                            last_fail = f"HTTP {st} {ct_r}"
                                        elif sz <= 10000:
                                            last_fail = f"content too small ({sz} B)"
                                        elif not xm._is_valid_audio(fp):
                                            last_fail = f"invalid content ({sz} B)"
                                        else:
                                            downloaded_ok = True
                                        if not downloaded_ok:
                                            try: os.remove(fp)
                                            except: pass
                                    if downloaded_ok:
                                        results.append(fp)
                                        TASKS[task_id]["retry_track"] = ""
                                        TASKS[task_id]["retry_wait"] = 0
                                        print(f"[XM]   saved: {fn} ({sz/1024:.0f} KB)", flush=True)
                                        if cb:
                                            cb({"event": "progress", "current": i+1, "total": eff_total, "file": fp, "title": t["title"]})
                                except Exception as e:
                                    last_fail = "download error: " + str(e)[:60]
                                    print(f"[XM]   download error: {e}, will retry...", flush=True)
                            else:
                                last_fail = "no audio captured"
                                print(f"[XM]   no audio captured, will retry...", flush=True)
                            if not downloaded_ok:
                                if budget.give_up():
                                    elapsed = budget.elapsed()
                                    print(f"[XM]   Giving up on track {t['track_id']} after {elapsed/3600:.1f}h (max 24h)", flush=True)
                                    TASKS[task_id]["output"] = f"[{idx}] {t['title'][:22]} 已跳过: 24h重试耗尽"
                                    TASKS[task_id]["_updated"] = time.time()
                                    _save_tasks()
                                    break  # next track
                                w = budget.next_wait()
                                TASKS[task_id]["retry_track"] = t["title"][:30]
                                TASKS[task_id]["retry_wait"] = w
                                TASKS[task_id]["retry_reason"] = last_fail
                                TASKS[task_id]["output"] = f"[{idx}] {t['title'][:22]} 失败, 等待{w}s重试: {last_fail}"
                                TASKS[task_id]["_updated"] = time.time()
                                _save_tasks()
                                print(f"[XM]   ({last_fail}) Waiting {w}s before retrying track {t['track_id']}...", flush=True)
                                # Cancellable wait
                                deadline = time.time() + w
                                while time.time() < deadline:
                                    st_now = TASKS[task_id].get("status")
                                    if st_now == "cancelled":
                                        print("[XM]   Cancelled during retry wait, exiting...", flush=True)
                                        ctx.close()
                                        return
                                    if st_now == "paused":
                                        while TASKS[task_id].get("status") == "paused":
                                            time.sleep(1)
                                        if TASKS[task_id].get("status") == "cancelled":
                                            print("[XM]   Cancelled while paused, exiting...", flush=True)
                                            ctx.close()
                                            return
                                        deadline = time.time() + w
                                    time.sleep(min(5, max(0.5, deadline - time.time())))
                                TASKS[task_id]["retry_track"] = ""
                                TASKS[task_id]["retry_wait"] = 0
                            if downloaded_ok:
                                time.sleep(2)
                                break  # success - next track
                    if cb:
                        cb({"event": "done", "downloaded": sum(1 for r in results if r), "total": total})
                    ctx.close()
                except Exception as e:
                    print(f"[XM-LOGIN] Error: {e}", flush=True)
                    import traceback; traceback.print_exc()
                    TASKS[task_id]["status"] = "error"
                    TASKS[task_id]["output"] = "Login download error: " + str(e)[:150]
                    TASKS[task_id]["_updated"] = time.time()
                    _save_tasks()
            else:
                result = xm.download(url, download_all=True, start_from=flags.get("start_from", 1), progress_callback=cb, to=flags.get("to"), tracks=flags.get("tracks", ""))
                if result is None:
                    TASKS[task_id]["status"] = "error"
                    TASKS[task_id]["output"] = "Download failed - API may be rate-limited, try again later"
                    TASKS[task_id]["_updated"] = time.time()
                    _save_tasks()
                    return
        elif platform == "wangyiyun":
            from platforms import wangyiyun
            wangyiyun.download(url, download_all=True, progress_callback=cb)
        elif platform == "bilibili":
            from platforms import bili
            result = bili.download(url, start_from=flags.get("start_from", 1), progress_callback=cb)
            if result is None:
                TASKS[task_id]["status"] = "error"
                TASKS[task_id]["output"] = "Download failed - check cookie (bilibili) or video may be restricted"
                TASKS[task_id]["_updated"] = time.time()
                _save_tasks()
                return
        elif platform == "dushu":
            from platforms import dushu
            dushu.download(url, download_all=True, progress_callback=cb)
        elif platform == "kuaishou":
            result = None
            try:
                from platforms import ks_pw
                result = ks_pw.download(url)
            except Exception as e:
                print(f"[KS] Playwright path error: {e}", flush=True)
            if not result:
                try:
                    from platforms import ks
                    result = ks.download(url)
                except Exception as e:
                    print(f"[KS] Page scrape path error: {e}", flush=True)
            if not result:
                TASKS[task_id]["status"] = "error"
                TASKS[task_id]["output"] = "Kuaishou download failed - JS-rendered page or HLS capture failed"
                TASKS[task_id]["_updated"] = time.time()
                _save_tasks()
                return
            # Record the downloaded file so the task card shows the real count
            if isinstance(result, str):
                result = [result]
            for fp in result:
                if fp and fp not in TASKS[task_id]["files"]:
                    TASKS[task_id]["files"].append(fp)
            TASKS[task_id]["count"] = len(TASKS[task_id]["files"])
            TASKS[task_id]["downloaded"] = len(TASKS[task_id]["files"])
            TASKS[task_id]["_updated"] = time.time()
            _save_tasks()
        elif platform == "douyin":
            from platforms import douyin_api
            modal_id, _ = douyin_api.get_modalid_from_share_link(url)
            if not modal_id:
                TASKS[task_id]["status"] = "error"
                TASKS[task_id]["output"] = "Douyin: cannot extract video ID from link"
                TASKS[task_id]["_updated"] = time.time()
                _save_tasks()
                return
            play_url = douyin_api.get_video_url(
                f"https://www.douyin.com/user/self?showTab=post&modal_id={modal_id}")
            if not play_url:
                TASKS[task_id]["status"] = "error"
                TASKS[task_id]["output"] = "Douyin: could not get play URL (try saving douyin cookie)"
                TASKS[task_id]["_updated"] = time.time()
                _save_tasks()
                return
            result = douyin_api.download_video(play_url, play_url.split("/")[-1])
            if not result:
                TASKS[task_id]["status"] = "error"
                TASKS[task_id]["output"] = "Douyin: download failed"
                TASKS[task_id]["_updated"] = time.time()
                _save_tasks()
                return
            TASKS[task_id]["files"].append(result)
            TASKS[task_id]["count"] = 1
            TASKS[task_id]["downloaded"] = 1
            TASKS[task_id]["_updated"] = time.time()
            _save_tasks()
        else:
            TASKS[task_id]["status"] = "error"
            TASKS[task_id]["output"] = "Not supported in web UI: " + str(platform)
            TASKS[task_id]["status"] = "error"
            TASKS[task_id]["_updated"] = time.time()
            _save_tasks()
            return
        if TASKS[task_id]["status"] == "running":
            TASKS[task_id]["status"] = "done"
            TASKS[task_id]["_updated"] = time.time()
            _save_tasks()
    except Exception as e:
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["output"] = str(e)[:200]
        TASKS[task_id]["_updated"] = time.time()
        _save_tasks()

@app.route("/")
def index():
    return render_template("download.html", page="download")

@app.route("/login")
def login_page():
    return render_template("login.html", page="login")


@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True, "version": VERSION})

@app.route("/api/info", methods=["POST"])
def api_info():
    """Get metadata for a URL before downloading."""
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url: return jsonify({"error": "No URL"}), 400
    platform = detect_platform(url)
    if not platform: return jsonify({"error": "Unknown platform"}), 400
    name, total = _get_url_info(url, platform)
    return jsonify({"platform": platform, "name": name, "total": total, "url": url})


@app.route("/api/download", methods=["POST"])
def api_download():
    global TASK_ID
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url: return jsonify({"error": "No URL"}), 400
    TASK_ID += 1
    tid = TASK_ID
    platform = detect_platform(url) or "unknown"
    name = _get_task_name(url, platform)
    flags = {"start_from": data.get("start_from", 1), "login": data.get("login", False),
             "all": data.get("all", False), "to": data.get("to"), "tracks": data.get("tracks", "")}
    cmd = _build_cli_cmd(url, platform, flags)
    TASKS[tid] = {"status": "pending", "url": url, "files": [], "count": 0, "total": 0,
                  "name": name, "platform": platform, "_updated": time.time(),
                  "login": data.get("login", False), "start_from": data.get("start_from", 1),
                  "to": data.get("to"), "tracks": data.get("tracks", ""), "cmd": cmd}
    _dl_thread = threading.Thread(target=run_download, args=(tid, url, flags), daemon=True)
    THREADS[tid] = _dl_thread
    _dl_thread.start()
    return jsonify({"task_id": tid, "platform": platform, "name": name})

@app.route("/api/tasks")
def api_tasks():
    """Return all active tasks (for page refresh)."""
    return jsonify({str(k): v for k, v in TASKS.items()})


@app.route("/api/task/<int:task_id>")
def api_task(task_id):
    if task_id not in TASKS: return jsonify({"error": "Not found"}), 404
    return jsonify(TASKS[task_id])

@app.route("/api/task/<int:task_id>/pause", methods=["POST"])
def api_task_pause(task_id):
    if task_id not in TASKS: return jsonify({"error": "Not found"}), 404
    TASKS[task_id]["status"] = "paused"
    TASKS[task_id]["_updated"] = time.time()
    _save_tasks()
    return jsonify({"ok": True})

@app.route("/api/task/<int:task_id>/resume", methods=["POST"])
def api_task_resume(task_id):
    if task_id not in TASKS: return jsonify({"error": "Not found"}), 404
    if TASKS[task_id].get("status") == "paused":
        TASKS[task_id]["status"] = "running"
        TASKS[task_id]["_updated"] = time.time()
        _save_tasks()
    return jsonify({"ok": True})

@app.route("/api/task/<int:task_id>/login-confirm", methods=["POST"])
def api_task_login_confirm(task_id):
    if task_id not in TASKS: return jsonify({"error": "Not found"}), 404
    if TASKS[task_id].get("status") == "waiting_login":
        TASKS[task_id]["status"] = "login_confirmed"
        TASKS[task_id]["_updated"] = time.time()
        _save_tasks()
    return jsonify({"ok": True})

@app.route("/api/task/<int:task_id>", methods=["DELETE"])
def api_task_delete(task_id):
    if task_id not in TASKS: return jsonify({"error": "Not found"}), 404
    delete_files = request.args.get("delete_files", "0") == "1"
    # Cancel the task first, and wait for its thread to stop writing files
    TASKS[task_id]["status"] = "cancelled"
    TASKS[task_id]["_updated"] = time.time()
    _save_tasks()
    t = THREADS.get(task_id)
    if t and t.is_alive():
        t.join(timeout=15)
    out_root = os.path.join(ROOT, "output")
    files_deleted = 0
    dirs_cleaned = 0
    if delete_files:
        # Delete ONLY this task's recorded files plus their temp/partial
        # artifacts. Never delete unrelated files in the same directory:
        # other tasks may share it (e.g. single videos in output/, or a
        # re-downloaded album dir).
        dirs_touched = set()
        for fp in TASKS[task_id].get("files", []):
            if not fp or not os.path.exists(fp):
                continue
            try:
                os.remove(fp)
                files_deleted += 1
                dirs_touched.add(os.path.dirname(fp))
            except: pass
            base = fp
            for pat in [base + ".audio.m4s", base + ".merged.mp4"] + \
                       [base + ".part" + str(i) for i in range(16)]:
                if os.path.exists(pat):
                    try:
                        os.remove(pat)
                        files_deleted += 1
                    except: pass
        # Clean up directories that became empty (deepest first)
        all_dirs = set()
        for d in dirs_touched:
            p = d
            while p and p != out_root and os.path.commonpath([p, out_root]) == out_root:
                all_dirs.add(p)
                p = os.path.dirname(p)
        for d in sorted(all_dirs, key=lambda x: -len(x)):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
                    dirs_cleaned += 1
            except: pass
    THREADS.pop(task_id, None)
    del TASKS[task_id]
    _save_tasks()
    return jsonify({"ok": True, "files_deleted": files_deleted, "dirs_cleaned": dirs_cleaned})


@app.route("/api/task/<int:task_id>/retry", methods=["POST"])
def api_task_retry(task_id):
    if task_id not in TASKS:
        return jsonify({"error": "Not found"}), 404
    old = TASKS[task_id]
    url = old.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL in task"}), 400
    # Ximalaya in web UI always requires login mode
    login = True if old.get("platform", "") == "ximalaya" else old.get("login", False)
    # Count already downloaded files for start_from
    start_from = old.get("start_from", 1)
    album_match = re.search(r"/album/(\d+)", url)
    if album_match:
        album_name = ""
        try:
            from platforms import xm
            album_name = xm._get_album_name(album_match.group(1))
        except:
            pass
        out_dir = os.path.join(ROOT, "output")
        if album_name:
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", album_name)[:40].strip(" _")
            out_dir = os.path.join(out_dir, safe_name)
        if os.path.exists(out_dir):
            valid_files = [f for f in os.listdir(out_dir)
                          if f.endswith((".m4a", ".mp3", ".aac"))
                          and os.path.getsize(os.path.join(out_dir, f)) > 10000]
            if valid_files:
                start_from = len(valid_files) + 1
                # Add existing file paths to task so progress bar includes them
                existing_fps = [os.path.join(out_dir, f) for f in valid_files]
                print(f"[RETRY] Found {len(valid_files)} existing files in {out_dir}, starting from #{start_from}")
    # Cancel old download thread if still running
    old_status = TASKS[task_id].get("status", "")
    old_thread = THREADS.get(task_id)
    if old_status in ("running", "pending", "paused", "waiting_login", "login_confirmed") or (old_thread and old_thread.is_alive()):
        print(f"[RETRY] Cancelling old thread (was {old_status}, alive={old_thread.is_alive() if old_thread else '?'}), waiting for cleanup...", flush=True)
        TASKS[task_id]["status"] = "cancelled"
        _save_tasks()
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=15)  # wait up to 15s for old thread to exit
        else:
            time.sleep(3)
    # Reuse same task_id - reset progress, keep metadata
    TASKS[task_id].update({
        "status": "pending",
        "files": [],
        "count": 0,
        "dl_bytes": 0,
        "dl_total": 0,
        "downloaded": 0,
        "output": "",
        "login": login,
        "_updated": time.time()
    })
    # Pre-populate files list with already-downloaded files for correct progress display
    try:
        for fp in existing_fps:
            if fp not in TASKS[task_id]["files"]:
                TASKS[task_id]["files"].append(fp)
        TASKS[task_id]["count"] = len(TASKS[task_id]["files"])
        TASKS[task_id]["total"] = old.get("total", 0)  # preserve total from original task
    except NameError:
        pass  # no existing_fps (not ximalaya or no files)
    _save_tasks()
    print(f"[RETRY] task {task_id} platform={old.get('platform','?')} login={login} url={url[:80]}", flush=True)
    flags = {"start_from": start_from, "login": login, "to": old.get("to"), "tracks": old.get("tracks")}
    TASKS[task_id]["cmd"] = _build_cli_cmd(url, old.get("platform", ""), flags, old.get("total", 0))
    _save_tasks()
    t = threading.Thread(target=run_download, args=(task_id, url, flags), daemon=True)
    THREADS[task_id] = t
    t.start()
    return jsonify({"task_id": task_id, "platform": old.get("platform", ""), "name": old.get("name", ""),
                    "message": "Retrying - already downloaded files will be skipped"})

@app.route("/api/files")
def api_files():
    out = os.path.join(ROOT, "output")
    files = []
    if os.path.exists(out):
        for root, dirs, fnames in os.walk(out):
            for fn in fnames:
                if fn.endswith((".mp3",".mp4",".m4a",".aac",".flac",".m4s")):
                    fp = os.path.join(root, fn)
                    files.append({"name": fn, "path": os.path.relpath(fp, out),
                                  "size": os.path.getsize(fp), "mtime": os.path.getmtime(fp)})
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(files[:100])

@app.route("/api/cookies")
def api_cookies():
    cdir = os.path.join(ROOT, "cookies")
    platforms = [
        "douyin","xhs","kuaishou","bilibili","youku","tencent","dushu","ximalaya","wangyiyun"
    ]
    return jsonify([{"name": p, "has_cookie": os.path.exists(os.path.join(cdir, p + ".json"))} for p in platforms])

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    platform = (data.get("platform") or "").strip()
    if not platform: return jsonify({"error": "No platform"}), 400
    try:
        from login import login_platform
        login_platform(platform, force_interactive=True)
        return jsonify({"ok": True, "platform": platform})
    except Exception as e:
        return jsonify({"error": str(e)[:100]}), 500

@app.route("/api/cookie-save", methods=["POST"])
def api_cookie_save():
    data = request.json or {}
    platform = (data.get("platform") or "").strip()
    cookie = (data.get("cookie") or "").strip()
    if not platform or not cookie: return jsonify({"error": "Need platform and cookie"}), 400
    from cookies import save_cookie
    save_cookie(platform, cookie)
    return jsonify({"ok": True, "platform": platform})

@app.route("/api/urls", methods=["POST"])
def api_urls():
    text = (request.json or {}).get("text", "")
    urls = re.findall(r"https?://[^\s]+", text)
    return jsonify([{"url": u, "platform": detect_platform(u)} for u in urls if detect_platform(u)])

@app.route("/api/output/<path:filepath>")
def serve_file(filepath):
    fp = os.path.join(ROOT, "output", filepath)
    if os.path.exists(fp): return send_file(fp, as_attachment=True)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/upload-baidu", methods=["POST"])
def api_upload_baidu():
    data = request.json or {}
    paths = data.get("paths", [])
    remote_dir = data.get("baidu_dir", "")
    try:
        from upload_baidu import upload_file, load_config
        cfg = load_config()
        if not cfg or not cfg.get("access_token"):
            return jsonify({"error": "Not authorized"}), 400
        ok = sum(1 for p in paths if os.path.exists(os.path.join(ROOT, "output", p))
                 and upload_file(os.path.join(ROOT, "output", p), cfg, remote_dir=remote_dir, verbose=False))
        return jsonify({"uploaded": ok, "total": len(paths)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    import webbrowser, threading
    print("Web UI: http://localhost:5000")
    def ob():import time;time.sleep(1);webbrowser.open("http://localhost:5000")
    threading.Thread(target=ob,daemon=True).start()
    app.run(host="0.0.0.0",port=5000,debug=False,threaded=True)
