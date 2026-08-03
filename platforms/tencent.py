# -*- coding: utf-8 -*-
"""Tencent Video (v.qq.com) downloader.
Usage: from tencent import download; download("https://v.qq.com/x/page/x1234abcd.html")
"""

import os, re, sys, time, requests, shutil, subprocess, threading
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":"https://v.qq.com/"}


def load_cookie():
    try: from cookies import load_cookie as lc; return lc("tencent")
    except: return None


def parse_url(url):
    m = re.search(r"/x/(?:page|cover)/(?:[a-zA-Z0-9]+/)?([a-zA-Z0-9]+)\.html", url)
    if m:
        return m.group(1)
    m = re.search(r"vid=([a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    return None


def get_video_info(vid, cookie=None, original_url=None, headless=False, interactive_login=False, playlist=False):
    """Use Playwright to render page and capture video stream URLs."""
    try: from playwright.sync_api import sync_playwright
    except ImportError:
        print("[TENCENT] Playwright not installed. pip install playwright")
        return None

    print("[TENCENT] Opening Chrome...")
    stream_urls = []
    title = "tencent_" + vid
    if original_url:
        page_url = original_url
    else:
        page_url = "https://v.qq.com/x/page/" + vid + ".html"

    try:
        with sync_playwright() as p:
            if interactive_login:
                profile_dir = os.path.join(ROOT, "tmp", "tencent_profile")
                os.makedirs(profile_dir, exist_ok=True)
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    channel="chrome",
                    args=["--no-sandbox", "--disable-infobars", "--disable-dev-shm-usage", "--disable-cache", "--disk-cache-size=0"],
                    ignore_default_args=["--enable-automation"],
                    user_agent=H["User-Agent"],
                    viewport={"width": 1280, "height": 720},
                    locale="zh-CN",
                )
                page = ctx.new_page()
                print("[TENCENT] Opening https://v.qq.com/ - please log in...")
                page.goto("https://v.qq.com/", wait_until="domcontentloaded", timeout=15000)
                print("[TENCENT] ========================================")
                print("[TENCENT] Log in, then press Enter")
                print("[TENCENT] ========================================")
                input()
                print("[TENCENT] Login confirmed, waiting for redirects to settle...")
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    pass
                print("[TENCENT] Navigating to video...")
            else:
                browser = p.chromium.launch(
                    headless=headless,
                    channel="chrome",
                    args=["--no-sandbox", "--disable-infobars", "--disable-cache", "--disk-cache-size=0"],
                )
                ctx = browser.new_context(
                    user_agent=H["User-Agent"],
                    viewport={"width": 1280, "height": 720},
                )
                if cookie:
                    for ck in cookie.split("; "):
                        if "=" in ck:
                            n, v = ck.split("=", 1)
                            try:
                                ctx.add_cookies([{"name": n, "value": v, "domain": ".qq.com", "path": "/"}])
                            except:
                                pass
                page = ctx.new_page()

            api_bodies = []

            def on_response(resp):
                u = resp.url
                ct = resp.headers.get("content-type", "")
                if ".m3u8" in u or ".mp4" in u or "video" in ct or ".ts" in u:
                    try: cl = int(resp.headers.get("content-length", "0"))
                    except: cl = 0
                    stream_urls.append((u, cl))
                    print("[TENCENT] Captured: " + u[:100] + "...")
                # Capture proxyhttp/vinfo response bodies for API-based extraction
                if "proxyhttp" in u or "vinfo_proxy" in u:
                    try:
                        body = resp.text()
                        if body and len(body) > 200:
                            api_bodies.append((u, body))
                            print("[TENCENT] API body captured: " + u[:80])
                    except:
                        pass

            # Intercept requests to see proxyhttp parameters
            def on_request(req):
                u = req.url
                if "proxyhttp" in u or "getvinfo" in u or "getplayurl" in u:
                    try:
                        post_data = req.post_data
                        if post_data:
                            print("[TENCENT] REQ " + u[:60] + " POST=" + post_data[:200])
                        else:
                            print("[TENCENT] REQ " + u[:120])
                    except:
                        pass

            page.on("request", on_request)
            page.on("response", on_response)
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)  # Let API calls complete

            if interactive_login:
                # Capture title early before long wait
                try:
                    title = page.title().rstrip("腾讯视频").rstrip("*-_ ").replace("*", "-").strip()
                except:
                    pass
                print("[TENCENT] Clearing all storage (IndexedDB+localStorage) and reloading from beginning...")
                try:
                    page.evaluate("indexedDB.databases&&indexedDB.databases().then(function(d){d.forEach(function(x){indexedDB.deleteDatabase(x.name)})});localStorage.clear();sessionStorage.clear();")
                except:
                    pass
                stream_urls.clear()
                api_bodies.clear()
                page.reload(wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                try:
                    page.evaluate("""() => {
                        var v = document.querySelector('video');
                        if (v) {
                            v.currentTime = 0;
                            v.playbackRate = 2.0;
                            v.play();
                            v.onended = function(e) { e.preventDefault(); v.pause(); };
                        }
                    }""")
                    print("[TENCENT] Playing from 0, auto-advance blocked")
                    # Discard streams captured before seek (homepage/preview artifacts)
                    stream_urls.clear()
                    api_bodies.clear()
                    print("[TENCENT] Now collecting video segments...")
                except Exception as e:
                    print("[TENCENT] Seek failed: " + str(e)[:80])
                print("[TENCENT] ========================================")
                print("[TENCENT] Playing at 2x speed. Wait until finished,")
                print("[TENCENT] then close this browser window.")
                print("[TENCENT] ========================================")
                # Wait while checking page URL - if it changes, auto-advance detected
                episodes = []
                initial_url = page.url
                print("[TENCENT] Monitoring URL: " + initial_url[:80])
                for _ in range(300):  # max 300 * 2s = 10 min
                    try:
                        page.wait_for_timeout(2000)
                        current = page.url
                        if page.url != initial_url:
                            print("[TENCENT] URL changed: " + page.url[:80])
                            if playlist:
                                # Save current episode, continue to next
                                episode_streams = list(stream_urls)
                                episodes.append({"title": title, "url": initial_url, "streams": episode_streams})
                                print("[TENCENT] Episode saved (" + str(len(episode_streams)) + " streams), downloading in background...")
                                # Start background download
                                ep_copy = {"title": title, "streams": episode_streams}
                                threading.Thread(target=_download_episode, args=(ep_copy, cookie), daemon=True).start()
                                stream_urls.clear()
                                initial_url = page.url
                                # Clear storage and reload for fresh start each episode
                                try:
                                    page.evaluate('indexedDB.databases&&indexedDB.databases().then(function(d){d.forEach(function(x){indexedDB.deleteDatabase(x.name)})});localStorage.clear();sessionStorage.clear();')
                                    page.reload(wait_until='domcontentloaded', timeout=30000)
                                    page.wait_for_timeout(5000)
                                    stream_urls.clear()
                                    title = page.title().rstrip("腾讯视频").rstrip("*-_ ").replace("*", "-").strip()
                                    page.evaluate('var v=document.querySelector("video");if(v){v.currentTime=0;v.playbackRate=2.0;v.play();v.onended=function(e){e.preventDefault();v.pause();}}')
                                    print("[TENCENT] Next episode from 0: " + title[:40])
                                except Exception as e:
                                    print("[TENCENT] Ep transition error: " + str(e)[:80])
                    except:
                        print("[TENCENT] Browser closed, proceeding...")
                        if playlist:
                            eps = list(stream_urls)
                            episodes.append({"title": title, "url": initial_url, "streams": eps})
                            print("[TENCENT] Final episode saved (" + str(len(eps)) + " streams)")
                        break
            else:
                page.wait_for_timeout(60000)
                try:
                    btn = page.query_selector("video, .txp_btn_play, [class*=play]")
                    if btn:
                        btn.click()
                        page.wait_for_timeout(30000)
                except:
                    pass

            try:
                title = page.title().rstrip("\u817e\u8baf\u89c6\u9891").rstrip("*-_ ").replace("*", "-").strip()
            except:
                pass

            try:
                ctx.close()
            except:
                try:
                    browser.close()
                except:
                    pass

    except Exception as e:
        print("[TENCENT] Browser session ended: " + str(e)[:100])
        # Fall through to process captured streams
        # Save whatever was collected before crash
        try:
            if playlist and stream_urls:
                eps = list(stream_urls)
                episodes.append({"title": title, "url": initial_url, "streams": eps})
                print("[TENCENT] Saved partial episode (" + str(len(eps)) + " streams)")
        except:
            pass

    if not stream_urls:
        print("[TENCENT] No streams captured")
        return None

    # Parse ALL captured API bodies for stream URLs
    if interactive_login and api_bodies:
        print("[TENCENT] Parsing " + str(len(api_bodies)) + " API bodies for stream URLs...")
        for api_url, body in api_bodies:
            try:
                import json as _json
                data = _json.loads(body)
                vinfo_str = data.get("vinfo") or data.get("vinfop", "")
                if vinfo_str:
                    vinfo = _json.loads(vinfo_str)
                    fl = vinfo.get("fl", {})
                    fi_list = fl.get("fi", [])
                    if not fi_list and isinstance(fl, dict):
                        fi_list = [{"name": k, **v} for k, v in fl.items() if isinstance(v, dict)]
                    for fi in fi_list:
                        name = fi.get("name", "?")
                        print("[TENCENT]   format: " + name + " keys=" + str(list(fi.keys())[:10]))
                        stream_url = fi.get("url", "") or fi.get("play_url", "") or fi.get("m3u8", "")
                        if not stream_url:
                            # Check nested fs/sl arrays
                            for arr_key in ["fs", "sl"]:
                                for item in fi.get(arr_key, []):
                                    stream_url = item.get("url", "") or item.get("play_url", "")
                                    if stream_url:
                                        break
                                if stream_url:
                                    break
                        if stream_url:
                            print("[TENCENT]   -> stream URL: " + name + " " + stream_url[:120])
                            stream_urls.append((stream_url, 0))
                # Also check flat fields
                for key in ["playUrl", "play_url", "url", "videoUrl", "m3u8"]:
                    val = data.get(key, "")
                    if val and isinstance(val, str) and val.startswith("http"):
                        print("[TENCENT]   flat " + key + ": " + val[:120])
            except Exception as e:
                pass

    # If no stream URLs found via parsing, try direct API call with browser cookies
    if interactive_login and not any(u for u, s in stream_urls if ".m3u8" in u):
        print("[TENCENT] Trying direct getvinfo API...")
        try:
            # Extract format IDs from captured API bodies
            format_ids = []
            for api_url, body in api_bodies:
                try:
                    import json
                    data = json.loads(body)
                    vinfo_str = data.get("vinfo", "")
                    if vinfo_str:
                        vinfo = json.loads(vinfo_str)
                        for fi in vinfo.get("fl", {}).get("fi", []):
                            fid = fi.get("id")
                            if fid:
                                format_ids.append(str(fid))
                except:
                    pass
            if format_ids:
                # Get cookies from browser
                try:
                    browser_cookies = ctx.cookies()
                    cookie_str = "; ".join([c["name"] + "=" + c["value"] for c in browser_cookies if c.get("value")])
                except:
                    cookie_str = cookie or ""
                # Try getvinfo for each format
                headers = dict(H)
                headers["Cookie"] = cookie_str
                headers["Content-Type"] = "application/json"
                for fid in format_ids[:3]:
                    params = {
                        "buid": "getvinfo",
                        "vid": vid,
                        "format_id": fid,
                        "otype": "json",
                        "platform": "10201",
                        "charge": "0",
                        "sphttps": "1",
                        "sphls": "2",
                        "defnpayver": "3",
                    }
                    try:
                        r = requests.post("https://vd.l.qq.com/proxyhttp", json=params, headers=headers, timeout=15)
                        if r.status_code == 200:
                            text = r.text
                            print("[TENCENT] getvinfo(" + str(fid) + "): " + text[:200])
                            # Search for m3u8 URLs in response
                            m = __import__("re").search(r"https?:[^""]+\.m3u8[^""]*", text)
                            if m:
                                m3u = m.group(0)
                                print("[TENCENT] getvinfo m3u8: " + m3u[:120])
                                stream_urls.append((m3u, 0))
                                break
                    except Exception as e:
                        print("[TENCENT] getvinfo failed: " + str(e)[:80])
        except Exception as e:
            print("[TENCENT] getvinfo error: " + str(e)[:80])

    print("[TENCENT] Intercepted " + str(len(stream_urls)) + " URLs:")
    for u, s in stream_urls:
        sz = str(round(s/1024/1024,2)) + "MB" if s > 0 else "?MB"
        print("[TENCENT]   size=" + sz + "  " + u[:120] + "...")

    # Find the best m3u8: probe each, count segments, pick the one with most
    m3u8s = [(u, s) for u, s in stream_urls if ".m3u8" in u or "mpegurl" in u.lower()]
    if not m3u8s:
        m3u8s = [(u, s) for u, s in stream_urls if s > 0 and s < 5 * 1024 * 1024 and ".mp4" not in u]
    if m3u8s:
        def _base_path(url):
            return url.rsplit("/", 1)[0] if "/" in url else url
        seen = set()
        deduped = []
        for u, s in sorted(m3u8s, key=lambda x: x[1], reverse=True):
            bp = _base_path(u)
            if bp not in seen:
                seen.add(bp)
                deduped.append((u, s))
        best_url, best_seg_count = None, 0
        for u, s in deduped[:8]:
            try:
                r = requests.get(u, headers=H, timeout=10)
                if r.status_code == 200 and r.text.strip().startswith("#EXTM3U"):
                    seg_count = len([l for l in r.text.split("\n") if l.strip() and not l.startswith("#")])
                    print("[TENCENT]   m3u8: " + str(seg_count) + " segments  " + u[:100])
                    if seg_count >= 20 and seg_count > best_seg_count:
                        best_seg_count = seg_count
                        best_url = u
            except:
                pass
        if best_url:
            print("[TENCENT] Selected m3u8: " + str(best_seg_count) + " segments")
            return {"title": title, "stream_url": best_url, "vid": vid}

    # If no m3u8 and interactive mode, collect all TS segments
    if interactive_login:
        segs = []
        seen = set()
        for u, s in stream_urls:
            if u not in seen and ".m3u8" not in u and "blob:" not in u:
                seen.add(u)
                segs.append(u)
        if len(segs) >= 3:
            print("[TENCENT] No playlist - merging " + str(len(segs)) + " TS segments instead")
            return {"title": title, "stream_url": "", "vid": vid, "segments": segs, "episodes": episodes if playlist else []}

    mp4s = [(u, s) for u, s in stream_urls if ".mp4" in u]
    if mp4s:
        mp4s.sort(key=lambda x: x[1], reverse=True)
        print("[TENCENT] Selected mp4: " + mp4s[0][0][:120])
        return {"title": title, "stream_url": mp4s[0][0], "vid": vid}

    return None




def _download_episode(ep, cookie):
    out = os.path.join(ROOT, "output")
    os.makedirs(out, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "_", ep.get("title", "ep"))[:40]
    fp = os.path.join(out, "tencent_" + safe + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4")
    hd = dict(H)
    if cookie:
        hd["Cookie"] = cookie
    segs = ep.get("streams", [])
    if len(segs) < 3:
        return
    result = download_segments(segs, fp, hd)
    if result:
        print("[TENCENT]   Background download complete: " + result)


def download_segments(seg_urls, output_fp, hd=None):
    hd = hd or dict(H)
    tmp_dir = os.path.join(ROOT, "ts_tmp", str(int(time.time() * 1000)))
    os.makedirs(tmp_dir, exist_ok=True)
    total = len(seg_urls)
    print("[TENCENT] Downloading " + str(total) + " TS segments...")
    ts_files = []
    for idx, url in enumerate(seg_urls):
        tf = os.path.join(tmp_dir, str(idx).zfill(5) + ".ts")
        ts_files.append(tf)
        if os.path.exists(tf) and os.path.getsize(tf) > 1000:
            continue
        for _ in range(3):
            try:
                r = requests.get(url, headers=hd, timeout=60)
                if r.status_code == 200 and len(r.content) > 500:
                    with open(tf, "wb") as f:
                        f.write(r.content)
                    break
            except:
                time.sleep(2)
        if idx % max(1, total // 10) == 0:
            print("[TENCENT]   " + str(idx) + "/" + str(total))

    concat_file = os.path.join(tmp_dir, "concat.txt")
    with open(concat_file, "w") as f:
        for tf in ts_files:
            if os.path.exists(tf) and os.path.getsize(tf) > 1000:
                f.write("file " + tf.replace("\\", "/") + "\n")

    ffmpeg = "ffmpeg"
    for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
        if os.path.exists(g):
            ffmpeg = g
            break
    rr = subprocess.run(
        [ffmpeg, "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", output_fp, "-y"],
        capture_output=True, timeout=600,
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if rr.returncode != 0:
        print("[TENCENT] Stream copy failed, retrying with re-encode...")
        rr2 = subprocess.run(
            [ffmpeg, "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_file, "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", output_fp, "-y"],
            capture_output=True, timeout=900,
        )
        if rr2.returncode != 0:
            print("[TENCENT] Re-encode also FAILED: " + (rr2.stderr or b"").decode("utf-8", "ignore")[-200:])
            # Try to use the original failed output file if it exists
            if os.path.exists(output_fp) and os.path.getsize(output_fp) > 1024*1024:
                print("[TENCENT] Using partial output: " + str(round(os.path.getsize(output_fp)/1024/1024)) + " MB")
                return output_fp
            return None
        if os.path.exists(output_fp) and os.path.getsize(output_fp) > 0:
            sz = str(round(os.path.getsize(output_fp) / 1024 / 1024))
            print("[TENCENT] Re-encoded: " + output_fp + " (" + sz + " MB)")
            return output_fp
    if os.path.exists(output_fp) and os.path.getsize(output_fp) > 0:
        sz = str(round(os.path.getsize(output_fp) / 1024 / 1024))
        print("[TENCENT] Merged: " + output_fp + " (" + sz + " MB)")
        return output_fp
    return None


def download_m3u8(m3u8_url, fp, hd=None):
    hd = hd or dict(H)
    r = requests.get(m3u8_url, headers=hd, timeout=15)
    if r.status_code != 200:
        print("[TENCENT] Failed to fetch m3u8: HTTP " + str(r.status_code))
        return None

    lines = r.text.split("\n")
    base = m3u8_url.rsplit("/", 1)[0] + "/"
    segs = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    segs = [s if s.startswith("http") else base + s for s in segs]
    if not segs:
        return None

    print("[TENCENT] " + str(len(segs)) + " TS segments, downloading...")
    tmp = os.path.join(ROOT, "ts_tmp", str(int(time.time() * 1000)))
    os.makedirs(tmp, exist_ok=True)

    for i, s in enumerate(segs):
        tf = os.path.join(tmp, str(i).zfill(5) + ".ts")
        if os.path.exists(tf) and os.path.getsize(tf) > 0:
            continue
        for _ in range(3):
            try:
                sr = requests.get(s, headers=hd, timeout=30)
                if len(sr.content) > 500 and sr.content[0] == 0x47:
                    with open(tf, "wb") as f:
                        f.write(sr.content)
                    break
            except:
                time.sleep(2)
        if i % max(1, len(segs)//5) == 0:
            print("[TENCENT]  " + str(i) + "/" + str(len(segs)))

    cf = os.path.join(tmp, "concat.txt")
    with open(cf, "w") as f:
        for i in range(len(segs)):
            p = os.path.join(tmp, str(i).zfill(5) + ".ts")
            if os.path.exists(p):
                f.write("file " + p.replace("\\", "/") + "\n")

    ffmpeg = "ffmpeg"
    for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
        if os.path.exists(g):
            ffmpeg = g
            break
    rr = subprocess.run(
        [ffmpeg, "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", cf, "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", fp, "-y"],
        capture_output=True, timeout=300,
    )
    shutil.rmtree(tmp, ignore_errors=True)

    if rr.returncode != 0:
        print("[TENCENT] Stream copy failed: " + (rr.stderr or b"").decode("utf-8", "ignore")[-200:])
        if os.path.exists(fp) and os.path.getsize(fp) > 1024*1024:
            print("[TENCENT] Using partial output: " + str(round(os.path.getsize(fp)/1024/1024)) + " MB")
            return fp
        return None
    return fp if os.path.exists(fp) else None


def download_direct(url, fp, hd=None):
    hd = hd or dict(H)
    r = requests.get(url, headers=hd, stream=True, timeout=120)
    total = int(r.headers.get("Content-Length", 0))
    print("[TENCENT] Downloading (" + str(round(total/1024/1024,1)) + " MB)...")
    with open(fp, "wb") as f:
        with tqdm(total=total, unit="B", unit_scale=True, desc="TENCENT") as bar:
            for chunk in r.iter_content(1024*1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    return fp


def download(link, out_dir=None, cookie=None, headless=True, interactive_login=None, playlist=None):
    cookie = cookie or load_cookie()

    if cookie:
        print("[TENCENT] Using saved login cookie")

    print("[TENCENT] Input: " + link)
    vid = parse_url(link)
    if not vid:
        print("[TENCENT] Cannot parse URL")
        return None
    print("[TENCENT] Video ID: " + vid)
    if interactive_login is None:
        interactive_login = "--login" in sys.argv
    if playlist is None:
        playlist = "--playlist" in sys.argv
    if interactive_login:
        headless = False
    print("[TENCENT] Mode: " + ("headless" if headless else "visible browser") + (" + login" if interactive_login else ""))

    info = get_video_info(vid, cookie, original_url=link, headless=headless, interactive_login=interactive_login, playlist=playlist)
    if not info:
        return None

    episodes = info.get("episodes", [])
    print("[TENCENT] Title: " + info["title"])
    stream = info.get("stream_url", "")
    segments = info.get("segments", [])
    if not stream and not segments:
        return None

    out_dir = out_dir or os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "_", info["title"])[:50]
    fp = os.path.join(out_dir, "tencent_" + safe + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4")

    h_dl = dict(H)
    if cookie:
        h_dl["Cookie"] = cookie

    if episodes:
        print("[TENCENT] Downloading " + str(len(episodes) + 1) + " episodes...")
        # Download current episode first
        if segments:
            result = download_segments(segments, fp, h_dl)
        if result:
            print("[TENCENT]   Episode 1/" + str(len(episodes)+1) + ": " + result)
        # Download saved episodes
        for idx, ep in enumerate(episodes, 2):
            ep_title = ep.get("title", "ep" + str(idx))
            ep_segs = ep.get("streams", [])
            if len(ep_segs) < 3:
                print("[TENCENT]   Episode " + str(idx) + ": too few streams (" + str(len(ep_segs)) + "), skipping")
                continue
            safe_ep = re.sub(r'[<>:"/\\|?*]', "_", ep_title)[:40]
            ep_fp = os.path.join(out_dir, "tencent_" + safe_ep + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4")
            ep_result = download_segments(ep_segs, ep_fp, h_dl)
            if ep_result:
                print("[TENCENT]   Episode " + str(idx) + "/" + str(len(episodes)+1) + ": " + ep_result)
        return result
    elif segments:
        result = download_segments(segments, fp, h_dl)
    elif ".m3u8" in stream:
        result = download_m3u8(stream, fp, h_dl)
    else:
        result = download_direct(stream, fp, h_dl)

    if result:
        print("[TENCENT] Saved: " + result)
    else:
        print("[TENCENT] Failed")
    return result


if __name__ == "__main__":
    link = sys.argv[1] if len(sys.argv) > 1 else input("Tencent Video link: ").strip()
    download(link)
