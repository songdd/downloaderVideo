import os, re, sys, json, time, base64, requests
from tqdm import tqdm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "Referer": "https://www.dushu365.com/"}

# AES-256-ECB for gateway API
_KEY = b"yZNpcKn6dJ4aveljI4kCrB/JhmR2CSND"

def _aes_encrypt(data_bytes):
    pad = 16 - len(data_bytes) % 16
    padded = data_bytes + bytes([pad] * pad)
    from Crypto.Cipher import AES
    return base64.b64encode(AES.new(_KEY, AES.MODE_ECB).encrypt(padded)).decode()

def _aes_decrypt(data_b64):
    from Crypto.Cipher import AES
    raw = base64.b64decode(data_b64)
    pt = AES.new(_KEY, AES.MODE_ECB).decrypt(raw)
    last = pt[-1]
    if last < 16:
        pt = pt[:-last]
    text = pt.decode("utf-8")
    # Trim trailing garbage (CryptoJS padding may leave extra bytes)
    idx = text.rfind("}")
    if idx > 0:
        text = text[:idx+1]
    return json.loads(text)

def _gateway_post(path, data_dict):
    body = json.dumps(data_dict).encode()
    enc = _aes_encrypt(body)
    h = {"Content-Type": "application/json", "reqentryption": "AES",
         "X-DUSHU-APP-PLT": "3", "X-DUSHU-APP-VER": "1.0.0",
         "User-Agent": H["User-Agent"], "Referer": H["Referer"],
         "Origin": "https://www.dushu365.com"}
    r = requests.post("https://gateway-api.dushu365.com/" + path,
                       data=enc, headers=h, timeout=30)
    if r.status_code != 200:
        return None
    return _aes_decrypt(r.text)

def _extract_next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>', html)
    return json.loads(m.group(1)) if m else None

def parse_url_type(url):
    m = re.search(r"/book/(\d+)", url)
    if m: return ("book", m.group(1))
    m = re.search(r"/course/(\d+)(?:/(\d+))?", url)
    if m: return ("course", m.group(1), m.group(2))
    return None

def get_course_programs(course_id):
    data = _gateway_post("fs-webtool/web/course/v100/programList",
                          {"courseId": int(course_id), "page": {"page": 1, "pageSize": 100}})
    if not data: return []
    programs = data.get("data", [])
    return [{"seq": p.get("seq",""), "title": (p.get("title","") or "").strip(),
             "audioUrl": p.get("audioUrl",""), "duration": p.get("duration",0),
             "programId": p.get("id"), "free": p.get("free",False),
             "albumName": p.get("albumName",""), "albumAuthorName": p.get("albumAuthorName","")}
            for p in programs]

def get_page_info(page_type, id1, id2=None):
    if page_type == "book":
        url = "https://www.dushu365.com/book/" + str(id1)
    else:
        url = "https://www.dushu365.com/course/" + str(id1)
        if id2: url += "/" + str(id2)
    try:
        r = requests.get(url, headers=H, timeout=30)
        if r.status_code != 200: print("[DUSHU] HTTP " + str(r.status_code)); return None
    except Exception as e: print("[DUSHU] Request failed: " + str(e)); return None
    data = _extract_next_data(r.text)
    if not data: print("[DUSHU] Could not extract page data"); return None
    try:
        pd = data["props"]["pageProps"]["data"]
        if page_type == "book":
            bi = pd.get("bookInfo", {}); ai = pd.get("audioInfo", {})
            mu = ai.get("mediaUrl", "")
            return {"page_type": "book", "book_id": id1, "title": bi.get("title",""),
                    "speaker": bi.get("speakerName",""), "duration": ai.get("duration",0),
                    "media_url": mu, "is_free": pd.get("bookRights",{}).get("free",False),
                    "is_trial": pd.get("bookRights",{}).get("trial",False)} if mu else None
        else:
            si = pd.get("sourceInfo", {}); mu = si.get("url", "")
            return {"page_type": "course", "course_id": id1, "program_id": id2,
                    "title": pd.get("title",""), "sub_title": pd.get("subTitle",""),
                    "speaker": pd.get("author",""), "duration": si.get("duration",0),
                    "media_url": mu, "total_programs": pd.get("totalProgramNum",0)} if mu else None
    except (KeyError, TypeError) as e: print("[DUSHU] Data parse error: " + str(e)); return None

def list_books():
    try: r = requests.get("https://www.dushu365.com/", headers=H, timeout=30)
    except: return []
    if r.status_code != 200: return []
    data = _extract_next_data(r.text)
    if not data: return []
    books = []
    try:
        pp = data["props"]["pageProps"]
        sections = [("newData", pp.get("newData",{}).get("data",[])),
                     ("allData", pp.get("allData",{}).get("data",[])),
                     ("hotData", pp.get("hotData",{}).get("books",[]))]
        seen = set()
        for sn, sbooks in sections:
            items = sbooks
            if sn == "hotData" and sbooks and isinstance(sbooks[0], list):
                items = [b for g in sbooks for b in g]
            for b in items:
                bid = b.get("bookId") or b.get("id")
                if bid and bid not in seen:
                    seen.add(bid)
                    books.append({"book_id":bid,"title":b.get("title",""),
                                  "speaker":b.get("speakerName",""),"score":b.get("score","")})
    except: pass
    return books

def download_audio(media_url, filename, output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    fp = os.path.join(output_dir, filename)
    headers = dict(H); headers["Referer"] = "https://www.dushu365.com/"
    try:
        r = requests.get(media_url, headers=headers, stream=True, timeout=120)
        total = int(r.headers.get("Content-Length", 0))
        if total > 0: print("[DUSHU] Downloading (" + str(round(total/1024/1024,1)) + " MB)...")
        else: print("[DUSHU] Downloading (size unknown)...")
        with open(fp, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="DUSHU") as bar:
                for chunk in r.iter_content(1024*1024):
                    if chunk: f.write(chunk); bar.update(len(chunk))
        actual = os.path.getsize(fp)
        print("[DUSHU] Saved: " + fp + " (" + str(round(actual/1024/1024,1)) + " MB)")
        return fp
    except Exception as e:
        print("[DUSHU] Download failed: " + str(e))
        try: os.remove(fp)
        except: pass
        return None

def download(link, output_dir=None, download_all=False):
    print("[DUSHU] Input: " + link)
    parsed = parse_url_type(link)
    if not parsed: print("[DUSHU] Cannot parse URL"); return None
    pt, id1 = parsed[0], parsed[1]
    id2 = parsed[2] if len(parsed) > 2 else None

    if pt == "book": print("[DUSHU] Type: book, ID: " + id1)
    else: print("[DUSHU] Type: course, CourseID: " + id1)

    # Course batch mode -- use API directly, not SSR
    if pt == "course" and download_all:
        print("[DUSHU] Fetching program list via API...")
        programs = get_course_programs(id1)
        if not programs:
            print("[DUSHU] No programs found (may need login)")
            return None

        # Get course info from API data (first program has albumName)
        speaker = programs[0].get("albumAuthorName", "") if "albumAuthorName" in programs[0] else ""
        if not speaker:
            info = get_page_info(pt, id1, id2)
            speaker = info["speaker"] if info else ""

        total = len(programs)
        print("[DUSHU] Found " + str(total) + " programs:")
        for p in programs:
            print(f"  {p['seq']}: {p['title'][:40]} ({p['duration']}s)")

        safe = lambda s: re.sub(r"""[<>:"/\\|?*]""", "_", s)[:50].strip(" _")
        safe_sp = re.sub(r"""[<>:"/\\|?*]""", "_", speaker)[:20].strip(" _")

        results = []
        for i, p in enumerate(programs):
            print(f"\n[DUSHU] [{i+1}/{total}] {p['seq']}: {p['title']}")
            if not p.get("audioUrl"):
                print("[DUSHU]   No audio URL, skipping")
                results.append(None)
                continue
            ts = time.strftime("%Y%m%d_%H%M%S")
            fn = "dushu_" + p['seq'] + "_" + safe(p['title']) + "_" + safe_sp + "_" + ts + ".mp3"
            results.append(download_audio(p["audioUrl"], fn, output_dir))
            if i < total - 1:
                time.sleep(1)
        ok = sum(1 for r in results if r)
        print(f"\n[DUSHU] Done: {ok}/{total} downloaded")
        return results

    # Single download (book or single course program)
    info = get_page_info(pt, id1, id2)

    # For course: use API to get program name and audio URL (fallback if SSR lacks audio)
    prog_name = None
    if pt == "course" and id2:
        programs = get_course_programs(id1)
        for p in programs:
            if str(p.get("programId")) == id2:
                prog_name = p["title"]
                api_audio = p.get("audioUrl", "")
                if not info:
                    # SSR gave nothing, build info from API
                    info = {"page_type": "course", "title": prog_name or "course",
                            "speaker": "", "duration": p.get("duration", 0),
                            "media_url": api_audio}
                elif not info.get("media_url"):
                    # SSR had no audio URL, use API's
                    info["media_url"] = api_audio
                break
        if prog_name and info:
            print("[DUSHU] Program: " + prog_name)

    if not info:
        print("[DUSHU] Could not get page info")
        return None

    d = info["duration"]
    print("[DUSHU] Title: " + info["title"])
    print("[DUSHU] Speaker: " + info["speaker"])
    print("[DUSHU] Duration: " + str(d) + "s (" + str(d//60) + ":" + str(d%60).zfill(2) + ")")
    if pt == "book": print("[DUSHU] Free: " + str(info.get("is_free",False)) + ", Trial: " + str(info.get("is_trial",False)))
    print("[DUSHU] Audio: " + info["media_url"][:80] + "...")

    safe = lambda s: re.sub(r"""[<>:"/\\|?*]""", "_", s)[:50].strip(" _")
    safe20 = lambda s: re.sub(r"""[<>:"/\\|?*]""", "_", s)[:20].strip(" _")
    ts = time.strftime("%Y%m%d_%H%M%S")
    if prog_name: filename = "dushu_" + safe(prog_name) + "_" + safe20(info["speaker"]) + "_" + ts + ".mp3"
    else: filename = "dushu_" + safe(info["title"]) + "_" + safe20(info["speaker"]) + "_" + ts + ".mp3"
    return download_audio(info["media_url"], filename, output_dir)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Dushu365 audio downloader")
    ap.add_argument("link", nargs="?", help="Book/course URL or ID")
    ap.add_argument("--list", action="store_true", help="List books")
    ap.add_argument("--all", action="store_true", help="Download ALL programs in a course")
    ap.add_argument("--output", "-o", default=None, help="Output dir")
    args = ap.parse_args()
    if args.list:
        books = list_books()
        print("\n" + "="*70)
        print("%-12s %-35s %-12s %-8s" % ("ID","Title","Speaker","Score"))
        print("-"*70)
        for b in books: print("%-12s %-35s %-12s %-8s" % (str(b["book_id"]), b["title"][:34], b["speaker"][:11], b["score"]))
        print("-"*70); print("Total: " + str(len(books)) + " books")
    elif args.link:
        link = args.link
        if not link.startswith("http"): link = "https://www.dushu365.com/book/" + link
        download(link, output_dir=args.output, download_all=args.all)
    else:
        link = input("Dushu365 URL or book ID: ").strip()
        if link:
            if not link.startswith("http"): link = "https://www.dushu365.com/book/" + link
            download(link)
