import os, re, sys, time, requests, shutil, subprocess
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":"https://v.youku.com/"}

def load_cookie():
    try: from cookies import load_cookie as lc; return lc("youku")
    except: return None

def parse_url(url):
    m = re.search(r"/id_([a-zA-Z0-9=]+)(\.html)?", url)
    return m.group(1) if m else None

def get_video_info(vid, cookie=None, use_firefox=False):
    try: from playwright.sync_api import sync_playwright
    except ImportError: print("[YOUKU] Playwright not installed."); return None
    print("[YOUKU] Opening " + ("Firefox" if use_firefox else "Chrome") + "...")
    video_urls, title = [], "youku_" + vid
    try:
        with sync_playwright() as p:
            if use_firefox:
                browser = p.firefox.launch(headless=False)
            else:
                browser = p.chromium.launch(headless=False, channel="chrome",
                    args=["--no-sandbox","--disable-blink-features=AutomationControlled","--window-size=800,600"])
            ctx = browser.new_context(user_agent=H["User-Agent"], viewport={"width":1280,"height":720})
            if cookie:
                for ck in cookie.split("; "):
                    if "=" in ck:
                        n, v = ck.split("=", 1)
                        try: ctx.add_cookies([{"name":n,"value":v,"domain":".youku.com","path":"/"}])
                        except: pass
            page = ctx.new_page()
            def on_response(resp):
                u = resp.url
                if any(x in u for x in [".m3u8",".ts",".mp4"]) or "video" in (resp.headers.get("content-type") or ""):
                    try: cl = int(resp.headers.get("content-length","0"))
                    except: cl = 0
                    video_urls.append((u, cl))
            page.on("response", on_response)
            page.goto("https://v.youku.com/v_show/id_" + vid + ".html", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(15000)
            try:
                btn = page.query_selector("video, .play-btn, [class*=play]")
                if btn: btn.click(); page.wait_for_timeout(10000)
            except: pass
            try:
                js_url = page.evaluate("""() => {var v=document.querySelector('video');if(v&&v.src)return v.src;var ss=document.querySelectorAll('script');for(var i=0;i<ss.length;i++){var t=ss[i].textContent||'';var m=t.match(/https?:[^\"'\\s]+\\.m3u8[^\"'\\s]*/);if(m)return m[0]}return null}""")
                if js_url: print("[YOUKU] JS found: " + str(js_url)[:120]); video_urls.append((js_url, 0))
            except Exception as e: print("[YOUKU] JS error: " + str(e))
            try: title = page.title().replace("-浼橀叿","").replace("-娓告垙","").strip()
            except: pass
            browser.close()
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

def download_m3u8(m3u8_url, fp, hd=None):
    hd = hd or dict(H)
    r = requests.get(m3u8_url, headers=hd, timeout=15)
    if r.status_code != 200: return None
    lines, base = r.text.split("\n"), m3u8_url.rsplit("/",1)[0] + "/"
    segs = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    segs = [s if s.startswith("http") else base + s for s in segs]
    if not segs: return None
    print("[YOUKU] " + str(len(segs)) + " TS segments, downloading...")
    tmp = os.path.join(ROOT, "ts_tmp", str(int(time.time()*1000)))
    os.makedirs(tmp, exist_ok=True)
    try:
        for i, s in enumerate(segs):
            tf = os.path.join(tmp, str(i).zfill(5) + ".ts")
            if os.path.exists(tf) and os.path.getsize(tf) > 0: continue
            for _ in range(3):
                try:
                    sr = requests.get(s, headers=hd, timeout=30)
                    data = sr.content
                    if len(data) > 500 and data[0] == 0x47:
                        open(tf, "wb").write(data); break
                except: time.sleep(2)
            else:
                try: sr = requests.get(s, headers=hd, timeout=30); open(tf, "wb").write(sr.content)
                except: pass
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

def download(link, out_dir=None, cookie=None):
    cookie = cookie or load_cookie()
    if cookie: print("[YOUKU] Using saved login cookie")
    print("[YOUKU] Input: " + link)
    vid = parse_url(link)
    if not vid: print("[YOUKU] Cannot parse URL"); return None
    print("[YOUKU] Video ID: " + vid)
    use_firefox = "--firefox" in sys.argv
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