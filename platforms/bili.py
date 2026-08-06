import os, re, sys, json, time, requests, threading, subprocess, concurrent.futures, hashlib, urllib.parse
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":"https://www.bilibili.com/"}

# ---- Wbi signing ----
_wbi_key = None
_wbi_ts = 0

def _fetch_wbi_key():
    global _wbi_key, _wbi_ts
    if _wbi_key and time.time() - _wbi_ts < 3600:
        return _wbi_key
    try:
        r = requests.get("https://api.bilibili.com/x/web-interface/wbi/index/nav", headers=H, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json().get("data", {}).get("wbi_img", {})
        img_url = d.get("img_url", "")
        sub_url = d.get("sub_url", "")
        if not img_url or not sub_url:
            return None
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        _wbi_key = (img_key + sub_key)[:32]
        _wbi_ts = time.time()
        return _wbi_key
    except Exception:
        return None

def _sign_wbi(params):
    key = _fetch_wbi_key()
    if not key:
        return params
    params["wts"] = str(int(time.time()))
    keys = sorted(params.keys())
    qs = "&".join(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(params[k]))}" for k in keys)
    params["w_rid"] = hashlib.md5((qs + key).encode()).hexdigest()
    return params

def load_cookie():
    try: from cookies import load_cookie as lc; return lc("bilibili")
    except: return None

def check_cookie_valid(cookie_str):
    if not cookie_str: return False, "no cookie"
    try:
        r = requests.get("https://api.bilibili.com/x/web-interface/nav",
                        headers={"User-Agent":H["User-Agent"],"Cookie":cookie_str}, timeout=10)
        if r.status_code != 200: return False, "HTTP " + str(r.status_code)
        data = r.json()
        if data.get("code") != 0: return False, data.get("message","unknown")
        uname = data.get("data",{}).get("uname","")
        level = data.get("data",{}).get("level_info",{}).get("current_level",0)
        vip = data.get("data",{}).get("vip",{}).get("type",0)
        return True, uname + " (Lv." + str(level) + ", " + ("VIP" if vip>0 else "Free") + ")"
    except: return False, "error"

def api_get(url, cookie=None):
    h = dict(H); h["Origin"] = "https://www.bilibili.com"
    if cookie: h["Cookie"] = cookie
    # Add Wbi signing to all x/web-interface and x/player calls
    if "/x/web-interface/" in url or "/x/player/" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params = {k: v[0] for k, v in qs.items()}
        params = _sign_wbi(params)
        base = url.split("?")[0]
        url = base + "?" + urllib.parse.urlencode(params)
    try: r = requests.get(url, headers=h, timeout=15); return r.json() if r.status_code==200 else None
    except: return None

def parse_url(url):
    for pat, typ in [(r"/video/(BV[a-zA-Z0-9]+)","bvid"),(r"/bangumi/play/ep(\d+)","ep"),
                     (r"/bangumi/play/ss(\d+)","ss"),(r"/video/av(\d+)","aid"),
                     (r"/BV([a-zA-Z0-9]+)","bvid"),(r"ep_id=(\d+)","ep"),(r"season_id=(\d+)","ss")]:
        m = re.search(pat, url)
        if m:
            vid = m.group(1)
            return {"type":typ,"id":"BV"+vid if typ=="bvid" and not vid.startswith("BV") else vid}
    return None

def get_redirect(url):
    try: r = requests.get(url, headers=H, allow_redirects=True, timeout=15); return r.url
    except: return None

def get_video_info(bvid, cookie=None):
    data = api_get("https://api.bilibili.com/x/web-interface/view?bvid=" + bvid, cookie)
    return data.get("data") if data and data.get("code")==0 else None

def get_bangumi_info(ep_id=None, ss_id=None, cookie=None):
    api = "https://api.bilibili.com/pgc/view/web/season?" + ("ep_id" if ep_id else "season_id") + "=" + (ep_id or ss_id)
    data = api_get(api, cookie)
    if not data or data.get("code")!=0: return None
    r = data.get("result",{}); eps = r.get("episodes",[])
    if not eps: return None
    ep, st = eps[0], r.get("season_title","")
    if ep_id:
        for e in eps:
            if str(e.get("id"))==ep_id: ep=e; break
    all_eps = [{"title":st+" "+e.get("long_title","")[:60],"bvid":e.get("bvid",""),"cid":e.get("cid",0),
        "aid":e.get("aid",0),"ep_id":str(e.get("id","")),"ep_num":e.get("title","") or e.get("long_title","")} for e in eps]
    return {"title":st+" "+ep.get("long_title","")[:60],"bvid":ep.get("bvid",""),"cid":ep.get("cid",0),
        "aid":ep.get("aid",0),"ep_id":str(ep.get("id","")),"ep_num":ep.get("title",""),"all_episodes":all_eps}

def _extract_url_and_quality(data):
    r = data.get("result",{}) or data.get("data",{})
    dash = r.get("dash",{})
    vids = dash.get("video",[]); auds = dash.get("audio",[])
    url, audio_url, label = None, None, None
    if vids:
        vids.sort(key=lambda x:x.get("bandwidth",0), reverse=True)
        url = vids[0].get("baseUrl","") or vids[0].get("base_url","")
        w,h = vids[0].get("width",0), vids[0].get("height",0)
        label = str(w)+"x"+str(h) if w and h else None
    if auds:
        auds.sort(key=lambda x:x.get("bandwidth",0), reverse=True)
        audio_url = auds[0].get("baseUrl","") or auds[0].get("base_url","")
    if not url:
        durl = r.get("durl",[])
        if durl: url = durl[0].get("url",""); audio_url = None
    if not label:
        qn = r.get("quality",0)
        qm = {127:"8K",120:"4K",116:"1080P60",112:"1080P+",80:"1080P",64:"720P",32:"480P",16:"360P"}
        label = qm.get(qn, "qn"+str(qn))
    return url, audio_url, label or "SD"

def get_best_play_url(is_pgc, ep_id=None, bvid=None, cid=None, aid=None, cookie=None):
    base = "https://api.bilibili.com/pgc/player/web/playurl" if is_pgc else "https://api.bilibili.com/x/player/playurl"
    idp = "ep_id="+ep_id if is_pgc else "bvid="+bvid+"&cid="+str(cid)
    for fn, ck in [("fnval=16",cookie),("fnval=16",None),("fnval=1&fourk=1",cookie),("fnval=1&fourk=1",None)]:
        for qn in [127,116,112,80,64,32,16]:
            data = api_get(base+"?"+idp+"&qn="+str(qn)+"&"+fn, ck)
            if data and data.get("code")==0:
                r = data.get("result",{}) or data.get("data",{})
                aqn = r.get("quality",0)
                url, audio_url, label = _extract_url_and_quality(data)
                if url and aqn >= qn-1:
                    print("[BILI] Got qn="+str(aqn)+" ("+label+") via "+("+ck" if ck else "no-ck"))
                    return url, audio_url, label
    return None, None, None

class _Progress:
    def __init__(self, t, b, s): self.d, self.t, self.b, self.l, self.s = [0]*4, t, b, threading.Lock(), s
    def up(self, i, n):
        with self.l: self.d[i]+=n; self.b.n=sum(self.d); self.b.refresh()

def _chunk(url, s, e, fp, hd, prog, i, stop):
    h = dict(hd); h["Range"] = "bytes="+str(s)+"-"+str(e)
    r = requests.get(url, headers=h, stream=True, timeout=(30,120))
    with open(fp,"wb") as f:
        for c in r.iter_content(512*1024):
            if stop.is_set(): return i, None
            if c: f.write(c); prog.up(i, len(c))
    return i, None

def _download_multi(url, fp, total, hd, threads=4):
    stop = threading.Event()
    print("[BILI] " + str(threads) + " threads, " + str(round(total/1024/1024,1)) + " MB")
    try:
        with tqdm(total=total, unit="B", unit_scale=True, desc="BILI") as bar:
            prog = _Progress(total, bar, stop)
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
                fs = [ex.submit(_chunk, url, i*(total//threads),
                      total-1 if i==threads-1 else (i+1)*(total//threads)-1,
                      fp+".part"+str(i), hd, prog, i, stop) for i in range(threads)]
                while fs:
                    done, fs = concurrent.futures.wait(fs, timeout=1)
                    for f in done:
                        i, err = f.result()
                        if err: stop.set(); ex.shutdown(wait=False); raise IOError("Chunk"+str(i))
    except KeyboardInterrupt:
        print("\n[BILI] Cancelled"); stop.set()
        for i in range(threads):
            try: os.remove(fp+".part"+str(i))
            except: pass
        raise
    with open(fp,"wb") as out:
        for i in range(threads):
            with open(fp+".part"+str(i),"rb") as f: out.write(f.read())
            os.remove(fp+".part"+str(i))
    return fp

def download_video(url, filename, out_dir=None, cookie=None, retries=5, audio_url=None):
    out_dir = out_dir or os.path.join(ROOT,"output")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, filename)
    h = dict(H); h["Referer"]="https://www.bilibili.com/"; h["Origin"]="https://www.bilibili.com"
    if cookie: h["Cookie"] = cookie
    for attempt in range(retries):
        try:
            rh = requests.head(url, headers=h, timeout=15)
            total = int(rh.headers.get("Content-Length",0))
            if total > 10*1024*1024 and "bytes" in rh.headers.get("Accept-Ranges",""):
                _download_multi(url, fp, total, h, 4)
            else:
                r = requests.get(url, headers=h, stream=True, timeout=(30,300))
                total = total or int(r.headers.get("Content-Length",0))
                if total > 0: print("[BILI] Downloading (" + str(round(total/1024/1024,1)) + " MB)...")
                else: print("[BILI] Downloading (size unknown)...")
                with open(fp,"wb") as f:
                    with tqdm(total=total, unit="B", unit_scale=True, desc="BILI") as bar:
                        for c in r.iter_content(1024*1024):
                            if c: f.write(c); bar.update(len(c))
            actual = os.path.getsize(fp)
            if total > 0 and actual < total*0.99: raise IOError("Incomplete: "+str(actual)+"/"+str(total))
            print("[BILI] Video saved: " + fp)

            # Download and merge audio if available
            if audio_url:
                audio_fp = fp + ".audio.m4s"
                print("[BILI] Downloading audio track...")
                try:
                    ar = requests.get(audio_url, headers=h, stream=True, timeout=(30,120))
                    with open(audio_fp, "wb") as af:
                        for chunk in ar.iter_content(1024*1024):
                            if chunk: af.write(chunk)
                    merged_fp = fp + ".merged.mp4"
                    ffmpeg = "ffmpeg"
                    for g in [os.path.join(ROOT, "bin", "ffmpeg.exe"), "ffmpeg"]:
                        if os.path.exists(g): ffmpeg = g; break
                    rr = subprocess.run([ffmpeg,"-i",fp,"-i",audio_fp,"-c","copy","-shortest","-y",merged_fp],
                                      capture_output=True, timeout=300)
                    if rr.returncode == 0 and os.path.getsize(merged_fp) > 0:
                        os.remove(fp); os.remove(audio_fp)
                        os.rename(merged_fp, fp)
                        print("[BILI] Audio merged: " + fp)
                    else:
                        print("[BILI] Audio merge failed, keeping video-only")
                        try: os.remove(audio_fp)
                        except: pass
                        try: os.remove(merged_fp)
                        except: pass
                except Exception as e:
                    print("[BILI] Audio download failed: " + str(e))
                    try: os.remove(audio_fp)
                    except: pass

            return fp
        except KeyboardInterrupt: raise
        except Exception as e:
            print("[BILI] Error (" + str(attempt+1) + "/" + str(retries) + "): " + str(e))
            try: os.remove(fp)
            except: pass
            for i in range(10):
                try: os.remove(fp+".part"+str(i))
                except: pass
            if attempt < retries-1: time.sleep(min(5+attempt*3,20))
    return None

def download(link, out_dir=None, cookie=None, start_from=1, progress_callback=None):
    cookie = cookie or load_cookie()
    if cookie:
        v, info = check_cookie_valid(cookie)
        if v: print("[BILI] Cookie valid: " + info)
        else: print("[BILI] Cookie INVALID: " + info)
    print("[BILI] Input: " + link)
    url = link
    if "b23.tv" in link: url = get_redirect(link) or url
    p = parse_url(url)
    if not p: print("[BILI] Cannot parse URL"); return None
    print("[BILI] Type=" + p["type"])
    if p["type"] in ("ep","ss"):
        info = get_bangumi_info(ep_id=p["id"] if p["type"]=="ep" else None,
                                ss_id=p["id"] if p["type"]=="ss" else None, cookie=cookie)
        if not info: return None
        eps = info.get("all_episodes",[])
        if len(eps) > 1:
            sn = re.sub(r'[<>:"/\\|?*]','_',info["title"][:40]).strip("_ ").strip() or "season"
            sd = os.path.join(out_dir or os.path.join(ROOT,"output"), sn)
            os.makedirs(sd, exist_ok=True)
            if progress_callback:
                progress_callback({"event": "init", "total": len(eps)})
            print("[BILI] " + str(len(eps)) + " episodes -> " + sd + "/")
            eps_to_dl, out = eps, sd
        else: eps_to_dl, out = [info], out_dir
        results = []
        skipped = 0
        for i, ep in enumerate(eps_to_dl):
            if i + 1 < start_from:
                continue
            n = ep.get("ep_num","") or str(i+1)
            t = re.sub(r'[<>:"/\\|?*]','_',ep["title"])[:35]
            # Skip if already downloaded
            existing = [f for f in os.listdir(out) if os.path.isfile(os.path.join(out, f)) and f.startswith("bili_" + n + "_")]
            if existing:
                skipped += 1
                continue
            print("\n[BILI] [" + str(i+1) + "/" + str(len(eps_to_dl)) + "] " + n)
            url, audio_url, q = get_best_play_url(True, ep_id=ep.get("ep_id",""), cookie=cookie)
            if not url: continue
            fn = "bili_" + n + "_" + t + "_" + q + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4"
            r = download_video(url, fn, out, cookie, audio_url=audio_url)
            results.append(r)
            if progress_callback and r:
                progress_callback({"event": "progress", "current": i + 1, "total": len(eps_to_dl), "file": r, "title": ep.get("title", "")})
            if i < len(eps_to_dl)-1: time.sleep(1)
        if skipped > 0:
            print("[BILI] Skipped " + str(skipped) + " already downloaded")
        if progress_callback:
            progress_callback({"event": "done", "downloaded": sum(1 for r in results if r), "total": len(eps_to_dl)})
        if skipped > 0:
            print("[BILI] Skipped " + str(skipped) + " already downloaded")
        return results
    else:
        info = get_video_info(p["id"], cookie)
        if not info: return None
        bvid = info.get("bvid","") or p["id"]
        pages = info.get("pages", [])
        if len(pages) > 1:
            main_title = re.sub(r'[<>:"/\\|?*]','_',info.get("title","unknown"))[:40].strip("_ ").strip()
            if not main_title:
                main_title = "bili_" + bvid
            total = len(pages)
            if progress_callback:
                progress_callback({"event": "init", "total": total})
            vid_dir = os.path.join(out_dir or os.path.join(ROOT,"output"), main_title)
            os.makedirs(vid_dir, exist_ok=True)
            print("[BILI] " + str(total) + " parts -> " + vid_dir)
            results = []
            skipped = 0
            for i, page in enumerate(pages):
                if i + 1 < start_from:
                    continue
                pn = str(page.get("page", i+1))
                pt = re.sub(r'[<>:"/\\|?*]','_',page.get("part","P"+pn))[:35]
                existing = [f for f in os.listdir(vid_dir) if os.path.isfile(os.path.join(vid_dir, f)) and f.startswith("bili_p"+pn+"_")]
                if existing:
                    skipped += 1
                    continue
                print("\n[BILI] [" + str(i+1) + "/" + str(total) + "] P" + pn + ": " + page.get("part",""))
                url, audio_url, q = get_best_play_url(False, bvid=bvid, cid=page.get("cid",0), aid=info.get("aid"), cookie=cookie)
                if not url: continue
                fn = "bili_p" + pn + "_" + pt + "_" + q + "_" + time.strftime("%Y%m%d_%H%M%S") + ".mp4"
                r = download_video(url, fn, vid_dir, cookie, audio_url=audio_url)
                results.append(r)
                if progress_callback and r:
                    progress_callback({"event": "progress", "current": i+1, "total": total, "file": r, "title": page.get("part","")})
                if i < total-1: time.sleep(1)
            if skipped > 0:
                print("[BILI] Skipped " + str(skipped) + " already downloaded")
            if progress_callback:
                progress_callback({"event": "done", "downloaded": sum(1 for r in results if r), "total": total})
            return results

        else:
            cid = pages[0].get("cid", info.get("cid",0)) if pages else info.get("cid",0)
            url, audio_url, q = get_best_play_url(False, bvid=bvid, cid=cid, aid=info.get("aid"), cookie=cookie)
            if not url: return None
            t = re.sub(r'[<>:"/\\|?*]','_',info.get("title","unknown"))[:40]
            return download_video(url, "bili_"+t+"_"+q+"_"+time.strftime("%Y%m%d_%H%M%S")+".mp4", out_dir, cookie, audio_url=audio_url)

if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser()
    ap.add_argument("link", nargs="?")
    ap.add_argument("--start-from", type=int, default=1, help="Start downloading from episode N")
    a = ap.parse_args()
    download(a.link, start_from=a.start_from) if a.link else download(input("Link: ").strip())