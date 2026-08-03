import os, re, sys, json, time, base64, requests
from tqdm import tqdm
from Crypto.Cipher import AES

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "Referer": "https://music.163.com/"}

# ---------- weapi encryption ----------
_FIRST_KEY = b"0CoJUm6Qyw8W8jud"
_IV = b"0102030405060708"

def _weapi(data_dict):
    """Encrypt params for NetEase weapi endpoint."""
    key2 = os.urandom(16)
    text = json.dumps(data_dict).encode()
    pad = 16 - len(text) % 16
    text += bytes([pad]) * pad
    enc1 = AES.new(_FIRST_KEY, AES.MODE_CBC, _IV).encrypt(text)
    enc2 = AES.new(key2, AES.MODE_CBC, _IV).encrypt(enc1)
    params_b64 = base64.b64encode(enc2).decode()
    enc_sec_key = "".join(f"{b:02x}" for b in reversed(key2))
    return params_b64, enc_sec_key

def _get_csrf(session):
    """Get CSRF token for weapi. Uses cookie or generates from MUSIC_U."""
    for c in session.cookies:
        if c.name == "__csrf":
            return c.value
    # Modern NetEase: try deriving from MUSIC_U
    music_u = session.cookies.get("MUSIC_U", "")
    if music_u:
        import hashlib
        return hashlib.md5(music_u.encode()).hexdigest()[:32]
    # Last resort: random hex
    return os.urandom(16).hex()


def _create_session():
    """Create a requests session with proper cookies. Uses Playwright if available."""
    session = requests.Session()
    session.headers.update(H)
    # Load saved cookies from file
    try:
        cp = os.path.join(ROOT, "cookies", "wangyiyun.json")
        if os.path.exists(cp):
            saved = json.load(open(cp, encoding="utf-8")).get("cookie", "")
            for ck in saved.split("; "):
                if "=" in ck:
                    n, v = ck.split("=", 1)
                    session.cookies.set(n, v, domain=".163.com", path="/")
            mu = session.cookies.get("MUSIC_U", "")
            print("[WYY] Loaded cookies, MUSIC_U=" + ("yes" if mu else "no"))
    except Exception as e:
        print("[WYY] Cookie load failed: " + str(e)[:60])
    session.get("https://music.163.com/", timeout=10)
    # Check if we have valid session
    if session.cookies.get("MUSIC_U") or session.cookies.get("__csrf"):
        return session
    # Try Playwright to get proper cookies
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel="chrome",
                args=["--no-sandbox", "--disable-gpu"])
            page = browser.new_page()
            page.goto("https://music.163.com/", wait_until="domcontentloaded", timeout=15000)
            cookies = page.context.cookies()
            browser.close()
            for ck in cookies:
                session.cookies.set(ck["name"], ck["value"], domain=ck.get("domain",""))
            print("[WYY] Got cookies via browser: {} total, csrf={}".format(
                len(cookies), session.cookies.get("__csrf", "none")))
            return session
    except Exception as e:
        print("[WYY] Playwright fallback failed: {}".format(str(e)[:60]))
    return session

def _weapi_post(session, path, data_dict):
    csrf = _get_csrf(session)
    data_dict["csrf_token"] = csrf
    params, sk = _weapi(data_dict)
    url = f"https://music.163.com/weapi{path}?csrf_token={csrf}"
    r = session.post(url, data={"params": params, "encSecKey": sk},
                     headers={"Referer": "https://music.163.com/"}, timeout=30)
    if r.status_code != 200 or not r.text.strip():
        return None
    return r.json()

# ---------- URL parsing ----------
def parse_url(url):
    """Parse NetEase URL. Returns (type, id) or None."""
    search_url = url
    fragment = ""
    if "#" in url:
        parts = url.split("#", 1)
        search_url = parts[0]
        fragment = parts[1]
        search_url = search_url + "?" + fragment if "?" in fragment else search_url

    # Special: toplist page (check both main URL and fragment)
    if "/discover/toplist" in search_url or "/discover/toplist" in fragment:
        return ("toplist", "")

    for pat, typ in [
        (r"/song\?id=(\d+)", "song"),
        (r"/playlist\?id=(\d+)", "playlist"),
        (r"/album\?id=(\d+)", "album"),
        (r"/artist\?id=(\d+)", "artist"),
    ]:
        m = re.search(pat, search_url)
        if m: return (typ, m.group(1))
    # Plain ID
    m = re.search(r"^(\d+)$", url.strip())
    if m: return ("song", m.group(1))
    return None


def list_toplists(session=None):
    if session is None:
        session = _create_session()
    try:
        r = session.get("https://music.163.com/api/toplist", headers=H, timeout=15)
        d = r.json()
        toplists = d.get("list", [])
        return [{"id": str(t["id"]), "name": t.get("name", ""), 
                 "count": t.get("trackCount", 0)} for t in toplists]
    except Exception:
        return []

# ---------- Song info & URL ----------
def get_song_info(song_id, session=None):
    if session is None:
        session = _create_session()

    # Get audio URL via old API
    audio_url = ""
    try:
        r = session.get(
            f"https://music.163.com/api/song/enhance/player/url?id={song_id}&ids=[{song_id}]&br=999000",
            headers=H, timeout=15)
        if r.status_code == 200:
            audio_url = r.json().get("data", [{}])[0].get("url", "") or ""
    except Exception:
        pass

    # Get song detail via old API
    name, artists, album, duration = "", "", "", 0
    try:
        r2 = session.get(
            f"https://music.163.com/api/song/detail?id={song_id}&ids=%5B{song_id}%5D",
            headers=H, timeout=15)
        if r2.status_code == 200:
            songs = r2.json().get("songs", [])
            if songs:
                s = songs[0]
                name = s.get("name", "")
                # artists field is "artists" not "ar" in newer API
                ar_list = s.get("artists", s.get("ar", []))
                artists = "/".join(a.get("name", "") for a in ar_list)
                # album field is "album" not "al" in newer API
                al_info = s.get("album", s.get("al", {}))
                if isinstance(al_info, dict):
                    album = al_info.get("name", "")
                duration = s.get("dt", 0) // 1000
    except Exception:
        pass

    if not audio_url:
        return {"song_id": song_id, "title": name, "artists": artists,
                "album": album, "audio_url": "", "duration": duration}

    return {
        "song_id": song_id, "title": name, "artists": artists,
        "album": album, "audio_url": audio_url, "duration": duration,
    }

def get_playlist_tracks(list_id, session=None):
    if session is None:
        session = _create_session()

    # Use old API
    try:
        r = session.get(f"https://music.163.com/api/playlist/detail?id={list_id}", headers=H, timeout=30)
        if r.status_code == 200:
            data = r.json()
            playlist = data.get("result", {})
            tracks = playlist.get("tracks", [])
            return [{"track_id": str(t["id"]), "title": t.get("name", ""),
                     "artists": "/".join(a.get("name", "") for a in t.get("artists", t.get("ar", []))),
                     "album": (t.get("album", t.get("al", {})) or {}).get("name", "") if isinstance(t.get("album", t.get("al", {})), dict) else "", 
                     "duration": t.get("dt", 0) // 1000} for t in tracks]
    except Exception:
        pass

    data = _weapi_post(session, "/v6/playlist/detail",
                       {"id": list_id, "n": 100000, "s": 0})
    if not data or data.get("code") != 200:
        return []
    playlist = data.get("playlist", {})
    tracks = playlist.get("tracks", [])
    return [{"track_id": str(t["id"]), "title": t["name"],
             "artists": "/".join(a["name"] for a in t.get("ar", [])),
             "album": t.get("al", {}).get("name", ""),
             "duration": t.get("dt", 0) // 1000} for t in tracks]

def get_album_tracks(album_id, session=None):
    if session is None:
        session = _create_session()

    # Use old API
    try:
        r = session.get(f"https://music.163.com/api/album/{album_id}", headers=H, timeout=30)
        if r.status_code == 200:
            data = r.json()
            album = data.get("album", {})
            tracks = album.get("songs", [])
            return [{"track_id": str(t["id"]), "title": t.get("name", ""),
                     "artists": "/".join(a.get("name", "") for a in t.get("artists", t.get("ar", []))),
                     "album": album.get("name", ""),
                     "duration": t.get("dt", 0) // 1000} for t in tracks]
    except Exception:
        pass

    # Fallback to weapi
    data = _weapi_post(session, "/v1/album", {"id": album_id})
    if not data or data.get("code") != 200:
        return []
    album = data.get("album", {})
    tracks = album.get("songs", [])
    return [{"track_id": str(t["id"]), "title": t["name"],
             "artists": "/".join(a["name"] for a in t.get("artists", t.get("ar", []))),
             "album": album.get("name", ""),
             "duration": t.get("dt", 0) // 1000} for t in tracks]


def get_artist_tracks(artist_id, session=None):
    if session is None:
        session = _create_session()
    try:
        r = session.get(
            f"https://music.163.com/api/artist/{artist_id}",
            headers=H, timeout=30)
        if r.status_code == 200:
            data = r.json()
            artist = data.get("artist", {})
            songs = artist.get("hotSongs", data.get("hotSongs", []))
            return [{"track_id": str(t["id"]), "title": t.get("name", ""),
                     "artists": "/".join(a.get("name", "") for a in t.get("artists", t.get("ar", []))),
                     "album": (t.get("album", t.get("al", {})) or {}).get("name", "") if isinstance(t.get("album", t.get("al", {})), dict) else "",
                     "duration": t.get("dt", 0) // 1000} for t in songs]
    except Exception:
        pass
    return []


# ---------- Download ----------
def download_audio(media_url, filename, output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    fp = os.path.join(output_dir, filename)
    headers = dict(H)
    try:
        r = requests.get(media_url, headers=headers, stream=True, timeout=120)
        total = int(r.headers.get("Content-Length", 0))
        if total > 0:
            print("[WYY] Downloading ({:.1f} MB)...".format(total/1024/1024))
        else:
            print("[WYY] Downloading (size unknown)...")
        with open(fp, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="WYY") as bar:
                for chunk in r.iter_content(1024*1024):
                    if chunk: f.write(chunk); bar.update(len(chunk))
        actual = os.path.getsize(fp)
        print("[WYY] Saved: {} ({:.1f} MB)".format(fp, actual/1024/1024))
        return fp
    except Exception as e:
        print("[WYY] Download failed: " + str(e))
        try: os.remove(fp)
        except: pass
        return None

# ---------- Main ----------
def _get_batch_name(ptype, pid, session):
    """Get human-readable name for playlist/album/artist."""
    try:
        if ptype == "playlist":
            r = session.get(f"https://music.163.com/api/playlist/detail?id={pid}", headers=H, timeout=15)
            return r.json().get("result", {}).get("name", "")
        elif ptype == "album":
            r = session.get(f"https://music.163.com/api/album/{pid}", headers=H, timeout=15)
            return r.json().get("album", {}).get("name", "")
        elif ptype == "artist":
            r = session.get(f"https://music.163.com/api/artist/{pid}", headers=H, timeout=15)
            return r.json().get("artist", {}).get("name", "")
    except Exception:
        pass
    return ""


def download(link, output_dir=None, download_all=False):
    print("[WYY] Input: " + link)
    parsed = parse_url(link)
    if not parsed:
        print("[WYY] Cannot parse URL (expected /song?id=xxx, /playlist?id=xxx, /album?id=xxx)")
        return None

    ptype, pid = parsed
    session = _create_session()

    safe = lambda s: re.sub(r'[<>:"/\\|?*]', "_", s)[:60].strip(" _")
    ts = time.strftime("%Y%m%d_%H%M%S")

    if ptype in ("playlist", "album", "artist") or ptype == "toplist":
        # Batch
        print("[WYY] Fetching track list...")
        if ptype == "toplist":
            # Show available toplists
            toplists = list_toplists(session)
            print("[WYY] {} charts available:".format(len(toplists)))
            for tl in toplists:
                print("  {} ({} tracks) -> python run.py https://music.163.com/playlist?id={}".format(
                    tl["name"][:40], tl["count"], tl["id"]))
            print("")
            print("[WYY] Example: python run.py https://music.163.com/playlist?id={}".format(toplists[0]["id"] if toplists else ""))
            return None
        elif ptype == "playlist":
            tracks = get_playlist_tracks(pid, session)
        elif ptype == "album":
            tracks = get_album_tracks(pid, session)
        else:
            tracks = get_artist_tracks(pid, session)

        if not tracks:
            print("[WYY] No tracks found.")
            return None

        total = len(tracks)
        print("[WYY] {} tracks:".format(total))
        for t in tracks[:5]:
            print("  {}. {} - {} ({}s)".format(
                tracks.index(t)+1, t["title"][:40], t["artists"][:20], t["duration"]))

        # Create subdirectory named after playlist/album/artist
        batch_name = _get_batch_name(ptype, pid, session)
        batch_dir = output_dir
        if batch_name:
            batch_dir = os.path.join(output_dir or os.path.join(ROOT, "output"),
                                    re.sub(r'[<>:"/\\|?*]', "_", batch_name)[:40].strip(" _"))
        os.makedirs(batch_dir, exist_ok=True)
        print("[WYY] Output: " + batch_dir)

        results = []
        for i, t in enumerate(tracks):
            print("\n[WYY] [{}/{}] {} - {} ...".format(
                i+1, total, t["title"][:30], t["artists"][:15]))
            info = get_song_info(t["track_id"], session)
            if not info or not info["audio_url"]:
                print("[WYY]   (no audio URL, may be VIP or unavailable)")
                results.append(None)
                continue
            ext = info["audio_url"].rsplit(".", 1)[-1].split("?")[0] if "." in info["audio_url"] else "mp3"
            fn = "wyy_{}_{}_{}.{}".format(
                safe(t["title"]), safe(t["artists"]), ts, ext)
            fn = fn[:120]
            results.append(download_audio(info["audio_url"], fn, batch_dir))
            time.sleep(1)

        ok = sum(1 for r in results if r)
        print("\n[WYY] Done: {}/{} downloaded".format(ok, total))
        return results
    else:
        info = get_song_info(pid, session)
        if not info or not info["audio_url"]:
            print("[WYY] Could not get audio URL (may be VIP-only or region-restricted)")
            return None
        print("[WYY] {} - {}".format(info["title"], info["artists"]))
        print("[WYY] Album: {}".format(info["album"]))
        print("[WYY] Duration: {}s".format(info["duration"]))
        ext = info["audio_url"].rsplit(".", 1)[-1].split("?")[0]
        if ext not in ("mp3", "m4a", "flac", "aac"): ext = "mp3"
        fn = "wyy_{}_{}_{}.{}".format(safe(info["title"]), safe(info["artists"]), ts, ext)
        return download_audio(info["audio_url"], fn, output_dir)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NetEase Music downloader")
    ap.add_argument("link", nargs="?", help="Song/playlist/album URL or ID")
    ap.add_argument("--all", action="store_true", help="Download all tracks in playlist/album")
    ap.add_argument("--output", "-o", default=None, help="Output dir")
    args = ap.parse_args()
    if args.link:
        link = args.link
        if not link.startswith("http") and link.isdigit():
            link = "https://music.163.com/song?id=" + link
        download(link, output_dir=args.output, download_all=args.all)
    else:
        link = input("NetEase Music URL or song ID: ").strip()
        if link:
            if not link.startswith("http") and link.isdigit():
                link = "https://music.163.com/song?id=" + link
            download(link)
