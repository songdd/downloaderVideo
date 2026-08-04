# -*- coding: utf-8 -*-
"""Baidu Netdisk uploader. Uses OAuth 2.0 and Pan API.
Config: config.json in project root.
Usage: python upload_baidu.py <file_path>
   or: python upload_baidu.py --auth   (first time OAuth)
"""

import os, json, time, requests, hashlib, webbrowser, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
OAUTH_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
UPLOAD_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
PRE_CREATE = "https://pan.baidu.com/rest/2.0/xpan/file?method=precreate"

_user_agent = "pan.baidu.com"


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("[BAIDU] config.json not found")
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_access_token(cfg):
    """Get a valid access token, refreshing if needed."""
    token = cfg.get("access_token", "")
    refresh = cfg.get("refresh_token", "")

    # Quick check: if we have a token, try a simple API call
    if token:
        try:
            r = requests.get(
                "https://pan.baidu.com/rest/2.0/xpan/nas?method=uinfo",
                params={"access_token": token}, timeout=10)
            if r.status_code == 200 and r.json().get("errno") == 0:
                return token
        except Exception:
            pass

    # Try refreshing
    if refresh:
        try:
            r = requests.get(TOKEN_URL, params={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": cfg["app_key"],
                "client_secret": cfg["secret_key"],
            }, timeout=15)
            d = r.json()
            if "access_token" in d:
                cfg["access_token"] = d["access_token"]
                cfg["refresh_token"] = d.get("refresh_token", refresh)
                save_config(cfg)
                print("[BAIDU] Token refreshed")
                return d["access_token"]
        except Exception as e:
            print("[BAIDU] Refresh failed: " + str(e)[:60])

    return None


def do_oauth(cfg):
    """Open browser for OAuth authorization."""
    redirect_uri = "oob"
    url = "{}?response_type=code&client_id={}&redirect_uri={}&scope=basic,netdisk&display=page".format(
        OAUTH_URL, cfg["app_key"], redirect_uri)
    print("[BAIDU] Opening browser for authorization...")
    print("[BAIDU] URL: " + url)
    webbrowser.open(url)
    code = input("[BAIDU] Paste the authorization code from the page: ").strip()
    if not code:
        return None
    try:
        r = requests.get(TOKEN_URL, params={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cfg["app_key"],
            "client_secret": cfg["secret_key"],
            "redirect_uri": redirect_uri,
        }, timeout=15)
        d = r.json()
        if "access_token" in d:
            cfg["access_token"] = d["access_token"]
            cfg["refresh_token"] = d.get("refresh_token", "")
            save_config(cfg)
            print("[BAIDU] Authorized successfully")
            return d["access_token"]
        else:
            print("[BAIDU] Auth failed: " + json.dumps(d, ensure_ascii=False)[:200])
    except Exception as e:
        print("[BAIDU] Auth error: " + str(e))
    return None


def _get_upload_host(token):
    """Get upload domain via locateupload."""
    try:
        r = requests.get(
            "https://d.pcs.baidu.com/rest/2.0/pcs/file",
            params={"method": "locateupload", "access_token": token},
            timeout=10)
        d = r.json()
        if d.get("host"):
            return d["host"]
    except Exception:
        pass
    return "c.pcs.baidu.com"  # fallback


def upload_file(filepath, cfg=None, remote_dir=None, verbose=True):
    """Upload a file to Baidu Netdisk. Supports any file size."""
    if cfg is None: cfg = load_config()
    if not cfg: return False
    token = get_access_token(cfg)
    if not token:
        print("[BAIDU] No valid token. Run: python upload_baidu.py --auth")
        return False
    if remote_dir is None: remote_dir = cfg.get("upload_dir", "/apps/downloaderVideo")

    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)
    # Ensure path is under app sandbox
    if not remote_dir.startswith("/apps/"):
        remote_dir = "/apps/奕霖工具" + ("" if remote_dir.startswith("/") else "/") + remote_dir
    remote_path = remote_dir + "/" + filename

    import urllib.parse
    enc_path = urllib.parse.quote(remote_path, safe="/")

    # For small files (< 4MB), use single-step upload
    if file_size <= 4 * 1024 * 1024:
        if verbose: print("[BAIDU] Uploading: {} ({:.1f} MB)".format(filename, file_size / 1024 / 1024))
        host = _get_upload_host(token)
        url = "https://{}/rest/2.0/pcs/file?method=upload&access_token={}&path={}&ondup=overwrite".format(
            host, token, enc_path)
        try:
            with open(filepath, "rb") as f:
                r = requests.post(url, files={"file": (filename, f, "application/octet-stream")}, timeout=300)
            data = r.json()
            if data.get("md5") or data.get("fs_id") or data.get("errno") == 0:
                if verbose: print("[BAIDU] Uploaded: " + remote_path)
                return True
            if verbose: print("[BAIDU] Upload failed: " + str(data)[:200])
            return False
        except Exception as ex:
            if verbose: print("[BAIDU] Upload error: " + str(ex)[:100])
            return False

    # Large file: full 3-step flow
    CHUNK = 4 * 1024 * 1024
    if verbose: print("[BAIDU] Uploading: {} ({:.1f} MB, chunked)".format(filename, file_size / 1024 / 1024))

    # Step 1: Pre-create
    file_data = open(filepath, "rb").read()
    file_md5 = hashlib.md5(file_data).hexdigest()
    block_list = json.dumps([file_md5])

    try:
        r = requests.post(
            "https://pan.baidu.com/rest/2.0/xpan/file",
            data={
                "method": "precreate",
                "access_token": token,
                "path": enc_path,
                "size": file_size,
                "isdir": 0,
                "autoinit": 1,
                "block_list": block_list,
                "rtype": 3,
            },
            timeout=15)
        pre = r.json()
        if pre.get("errno") != 0:
            if verbose: print("[BAIDU] Pre-create failed: " + str(pre)[:200])
            return False
        upload_id = pre["uploadid"]
    except Exception as ex:
        if verbose: print("[BAIDU] Pre-create error: " + str(ex)[:100])
        return False

    # Step 2: Upload chunks via superfile2
    host = _get_upload_host(token)
    chunk_count = (file_size + CHUNK - 1) // CHUNK
    print("[BAIDU] {} chunks, uploading...".format(chunk_count))

    for i in range(chunk_count):
        start = i * CHUNK
        end = min(file_size, start + CHUNK)
        chunk_data = file_data[start:end]

        part_url = "https://{}/rest/2.0/pcs/superfile2?method=upload&access_token={}&path={}&uploadid={}&partseq={}&type=tmpfile".format(
            host, token, enc_path, upload_id, i)

        for attempt in range(3):
            try:
                r = requests.post(part_url,
                    files={"file": ("chunk_{}".format(i), chunk_data, "application/octet-stream")},
                    timeout=120)
                part = r.json()
                if part.get("md5") or part.get("error_code") == 0:
                    break
            except Exception:
                if attempt < 2:
                    time.sleep(2)
        else:
            if verbose: print("[BAIDU] Chunk {} upload failed".format(i))
            return False

    # Step 3: Create (finalize)
    try:
        r = requests.post(
            "https://pan.baidu.com/rest/2.0/xpan/file",
            data={
                "method": "create",
                "access_token": token,
                "path": enc_path,
                "size": file_size,
                "isdir": 0,
                "block_list": block_list,
                "uploadid": upload_id,
                "rtype": 3,
            },
            timeout=15)
        create = r.json()
        if create.get("errno") == 0:
            if verbose: print("[BAIDU] Uploaded: " + remote_path)
            return True
        if verbose: print("[BAIDU] Create failed: " + str(create)[:200])
        return False
    except Exception as ex:
        if verbose: print("[BAIDU] Create error: " + str(ex)[:100])
        return False

if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage:")
        print("  python upload_baidu.py --auth                (authorize once)")
        print("  python upload_baidu.py <dir> --upload-baidu  (upload all audio)")
        print("  python upload_baidu.py <dir> --upload-baidu --baidu-dir /path")
        sys.exit(0)
    if "--auth" in sys.argv:
        cfg = load_config(); do_oauth(cfg); sys.exit(0)
    source = None
    for a in sys.argv[1:]:
        if not a.startswith("--"): source = a; break
    if not source or not os.path.exists(source):
        print("[BAIDU] Not found: " + str(source)); sys.exit(1)
    remote_dir = None
    if "--baidu-dir" in sys.argv:
        try: idx = sys.argv.index("--baidu-dir"); remote_dir = sys.argv[idx + 1]
        except: pass
    import glob as _g
    if os.path.isdir(source):
        files = _g.glob(os.path.join(source, "*.m4a")) + _g.glob(os.path.join(source, "*.mp3")) + _g.glob(os.path.join(source, "*.aac")) + _g.glob(os.path.join(source, "*.flac"))
        print("[BAIDU] Found {} audio files".format(len(files)))
        # Preserve directory name in remote path
        if remote_dir is None: remote_dir = ""
        remote_dir = remote_dir.rstrip("/") + "/" + os.path.basename(source.rstrip("/\\"))
    elif os.path.isfile(source):
        files = [source]
    else:
        files = []
    if not files:
        print("[BAIDU] No files"); sys.exit(1)
    if remote_dir:
        print("[BAIDU] Remote dir: " + remote_dir)
    from tqdm import tqdm
    ok = 0; fail = 0
    for f in tqdm(files, desc="Upload", unit="file"):
        if upload_file(f, remote_dir=remote_dir, verbose=False):
            ok += 1
        else:
            fail += 1
    print("[BAIDU] Done: {}/{} uploaded".format(ok, len(files)))
