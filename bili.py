# -*- coding: utf-8 -*-
"""Bilibili downloader - multi-threaded, auto-quality, season batch, Ctrl+C safe."""

import os, re, sys, json, time, requests, threading
import concurrent.futures
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":"https://www.bilibili.com/"}

def load_cookie():
    try: from cookies import load_cookie as lc; return lc("bilibili")
    except: return None

def check_cookie_valid(cookie_str):
    """Check if Bilibili cookie is still valid by calling user info API."""
    if not cookie_str: return False, "no cookie"
    try:
        r = requests.get("https://api.bilibili.com/x/web-interface/nav",
                        headers={"User-Agent": H["User-Agent"], "Cookie": cookie_str}, timeout=10)
        if r.status_code != 200: return False, f"HTTP {r.status_code}"
        data = r.json()
        if data.get("code") != 0: return False, data.get("message","unknown")
        uname = data.get("data",{}).get("uname","")
        level = data.get("data",{}).get("level_info",{}).get("current_level",0)
        vip = data.get("data",{}).get("vip",{}).get("type",0)
        vip_label = "VIP" if vip > 0 else "Free"
        return True, f"{uname} (Lv.{level}, {vip_label})"
    except Exception as e:
        return False, str(e)

def api_get(url, cookie=None):
    h = dict(H); h["Origin"] = "https://www.bilibili.com"
    if cookie: h["Cookie"] = cookie
    try: r = requests.get(url, headers=h, timeout=15); return r.json() if r.status_code == 200 else None
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
    data = api_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", cookie)
    return data.get("data") if data and data.get("code")==0 else None

def get_bangumi_info(ep_id=None, ss_id=None, cookie=None):
    api = f"https://api.bilibili.com/pgc/view/web/season?{'ep_id' if ep_id else 'season_id'}={ep_id or ss_id}"
    data = api_get(api, cookie)
    if not data or data.get("code") != 0: return None
    r = data.get("result",{}); eps = r.get("episodes",[])
    if not eps: return None
    ep, st = eps[0], r.get("season_title","")
    if ep_id:
        for e in eps:
            if str(e.get("id")) == ep_id: ep = e; break
    all_eps = [{"title":f"{st} {e.get('long_title','')}"[:80],"bvid":e.get("bvid",""),"cid":e.get("cid",0),
        "aid":e.get("aid",0),"ep_id":str(e.get("id","")),"ep_num":e.get("title","") or e.get("long_title","")} for e in eps]
    return {"title":f"{st} {ep.get('long_title','')}"[:80],"bvid":ep.get("bvid",""),"cid":ep.get("cid",0),
        "aid":ep.get("aid",0),"ep_id":str(ep.get("id","")),"ep_num":ep.get("title",""),"all_episodes":all_eps}

def _extract_url_and_quality(data):
    r = data.get("result",{}) or data.get("data",{})
    dash = r.get("dash",{}); vids = dash.get("video",[])
    url, label = None, None
    if vids:
        vids.sort(key=lambda x:x.get("bandwidth",0), reverse=True)
        url = vids[0].get("baseUrl","") or vids[0].get("base_url","")
        w,h = vids[0].get("width",0), vids[0].get("height",0)
        label = f"{w}x{h}" if w and h else None
    if not url:
        durl = r.get("durl",[])
        if durl: url = durl[0].get("url","")
    if not label:
        qn = r.get("quality",0)
        qm = {127:"8K",120:"4K",116:"1080P60",112:"1080P+",80:"1080P",64:"720P",32:"480P",16:"360P"}
        label = qm.get(qn, f"qn{qn}")
    return url, label or "SD"

def get_best_play_url(is_pgc, ep_id=None, bvid=None, cid=None, aid=None, cookie=None):
    base = "https://api.bilibili.com/pgc/player/web/playurl" if is_pgc else "https://api.bilibili.com/x/player/playurl"
    idp = f"ep_id={ep_id}" if is_pgc else f"bvid={bvid}&cid={cid}"
    for fn, ck in [("fnval=16",cookie),("fnval=16",None),("fnval=1&fourk=1",cookie),("fnval=1&fourk=1",None)]:
        for qn in [127,116,112,80,64,32,16]:
            data = api_get(f"{base}?{idp}&qn={qn}&{fn}", ck)
            if data and data.get("code")==0:
                r = data.get("result",{}) or data.get("data",{})
                aqn = r.get("quality",0)
                url, label = _extract_url_and_quality(data)
                if url and aqn >= qn-1:
                    print(f"[BILI] Got qn={aqn} ({label}) via {'+ck' if ck else 'no-ck'}")
                    return url, label
    return None, None

class _Progress:
    def __init__(self, total, bar, stop):
        self.done, self.total, self.bar = [0]*4, total, bar
        self.lock, self.stop = threading.Lock(), stop
    def update(self, i, n):
        with self.lock: self.done[i] += n; self.bar.n = sum(self.done); self.bar.refresh()

def _chunk(url, s, e, fp, h, prog, i):
    hd = dict(h); hd["Range"] = f"bytes={s}-{e}"
    r = requests.get(url, headers=hd, stream=True, timeout=(15,30))
    with open(fp,"wb") as f:
        for c in r.iter_content(512*1024):
            if prog.stop.is_set(): return i, "cancelled"
            if c: f.write(c); prog.update(i, len(c))
    return i, None

def _download_multi(url, fp, total, headers, threads=4):
    stop = threading.Event()
    print(f"[BILI] {threads} threads, {total/1024/1024:.1f} MB")
    try:
        with tqdm(total=total, unit="B", unit_scale=True, desc="BILI") as bar:
            prog = _Progress(total, bar, stop)
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
                fs = [ex.submit(_chunk, url, i*(total//threads),
                      total-1 if i==threads-1 else (i+1)*(total//threads)-1,
                      fp+".part"+str(i), headers, prog, i) for i in range(threads)]
                while fs:
                    done, fs = concurrent.futures.wait(fs, timeout=1)
                    for f in done:
                        i, err = f.result()
                        if err:
                            stop.set(); ex.shutdown(wait=False)
                            if err == "cancelled": raise KeyboardInterrupt()
                            raise IOError(f"Chunk{i}: {err}")
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

def download_video(url, filename, out_dir=None, cookie=None, retries=5):
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
                r = requests.get(url, headers=h, stream=True, timeout=(30,120))
                total = total or int(r.headers.get("Content-Length",0))
                print(f"[BILI] Downloading ({total/1024/1024:.1f} MB)...")
                with open(fp,"wb") as f:
                    with tqdm(total=total, unit="B", unit_scale=True, desc="BILI") as bar:
                        for c in r.iter_content(512*1024):
                            if c: f.write(c); bar.update(len(c))
            if total and os.path.getsize(fp) < total*0.99:
                raise IOError(f"Incomplete: {os.path.getsize(fp)}/{total}")
            print(f"[BILI] Saved: {fp}"); return fp
        except KeyboardInterrupt: raise
        except Exception as e:
            print(f"[BILI] Error ({attempt+1}/{retries}): {e}")
            try: os.remove(fp)
            except: pass
            for i in range(10):
                try: os.remove(fp+".part"+str(i))
                except: pass
            if attempt < retries-1: time.sleep(min(5+attempt*3,20))
    return None

def download(link, out_dir=None, cookie=None):
    cookie = cookie or load_cookie()
    if cookie:
        valid, info = check_cookie_valid(cookie)
        if valid:
            print(f"[BILI] Cookie valid: {info}")
        else:
            print(f"[BILI] Cookie INVALID: {info} - quality will be limited")
    print(f"[BILI] Input: {link}")
    url = link
    if "b23.tv" in link: url = get_redirect(link) or url
    p = parse_url(url)
    if not p: print("[BILI] Cannot parse URL"); return None
    print(f"[BILI] Type={p['type']}")
    if p["type"] in ("ep","ss"):
        info = get_bangumi_info(ep_id=p["id"] if p["type"]=="ep" else None,
                                ss_id=p["id"] if p["type"]=="ss" else None, cookie=cookie)
        if not info: return None
        eps = info.get("all_episodes",[])
        if len(eps) > 1:
            sn = re.sub(r'[<>:"/\\|?*]','_',info['title'][:40]).strip('_ ').strip() or 'season'
            sd = os.path.join(out_dir or os.path.join(ROOT,"output"), sn)
            os.makedirs(sd, exist_ok=True)
            print(f"[BILI] {len(eps)} episodes -> {sd}/")
            eps_to_dl, out = eps, sd
        else: eps_to_dl, out = [info], out_dir
        results = []
        for i, ep in enumerate(eps_to_dl):
            n = ep.get("ep_num","") or str(i+1)
            t = re.sub(r'[<>:"/\\|?*]','_',ep['title'])[:35]
            print(f"\n[BILI] [{i+1}/{len(eps_to_dl)}] {n}")
            url, q = get_best_play_url(True, ep_id=ep.get("ep_id",""), cookie=cookie)
            if not url: continue
            fn = f"bili_{n}_{t}_{q}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            results.append(download_video(url, fn, out, cookie))
            if i < len(eps_to_dl)-1: time.sleep(1)
        return results
    else:
        info = get_video_info(p["id"], cookie)
        if not info: return None
        bvid = info.get("bvid","") or p["id"]
        cid = info.get("cid",0) or (info.get("pages",[{}])[0].get("cid",0))
        url, q = get_best_play_url(False, bvid=bvid, cid=cid, aid=info.get("aid"), cookie=cookie)
        if not url: return None
        t = re.sub(r'[<>:"/\\|?*]','_',info.get("title","unknown"))[:40]
        return download_video(url, f"bili_{t}_{q}_{time.strftime('%Y%m%d_%H%M%S')}.mp4", out_dir, cookie)

if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser()
    ap.add_argument("link", nargs="?")
    a = ap.parse_args()
    download(a.link) if a.link else download(input("Link: ").strip())