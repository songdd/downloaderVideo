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


def upload_file(filepath, cfg=None, remote_dir=None):
    """Upload a file to Baidu Netdisk. Returns True on success."""
    if cfg is None:
        cfg = load_config()
    if not cfg:
        return False

    token = get_access_token(cfg)
    if not token:
        print("[BAIDU] No valid token. Run: python upload_baidu.py --auth")
        return False

    if remote_dir is None:
        remote_dir = cfg.get("upload_dir", "/apps/downloaderVideo")

    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)
    remote_path = remote_dir + "/" + filename

    print("[BAIDU] Uploading: {} ({:.1f} MB)".format(filename, file_size / 1024 / 1024))

    # Step 1: Pre-create
    try:
        content_md5 = hashlib.md5(open(filepath, "rb").read()).hexdigest()
        slice_md5 = hashlib.md5(open(filepath, "rb").read(262144)).hexdigest()
    except Exception:
        content_md5 = ""
        slice_md5 = ""

    params = {
        "access_token": token,
        "path": remote_path,
        "size": file_size,
        "isdir": 0,
        "autoinit": 1,
        "rtype": 3,
    }
    if content_md5:
        params["content-md5"] = content_md5
        params["slice-md5"] = slice_md5

    try:
        r = requests.post(PRE_CREATE, data=params, timeout=15)
        data = r.json()
        if data.get("errno") != 0:
            print("[BAIDU] Pre-create failed: " + str(data))
            return False
        upload_id = data.get("uploadid", "")
    except Exception as e:
        print("[BAIDU] Pre-create error: " + str(e))
        return False

    # Step 2: Upload
    try:
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "application/octet-stream")}
            upload_params = {
                "access_token": token,
                "path": remote_path,
                "uploadid": upload_id,
                "partseq": 0,
                "method": "upload",
                "type": "tmpfile",
            }
            r = requests.post(
                "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2",
                params={"method": "upload", "access_token": token,
                        "path": remote_path, "uploadid": upload_id,
                        "partseq": 0, "type": "tmpfile"},
                files=files, timeout=300)
            data = r.json()
            if r.status_code == 200 and data.get("md5"):
                print("[BAIDU] Uploaded: " + remote_path)
                return True
            else:
                print("[BAIDU] Upload failed: " + str(data)[:200])
                return False
    except Exception as e:
        print("[BAIDU] Upload error: " + str(e)[:100])
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--auth":
        cfg = load_config()
        do_oauth(cfg)
    elif len(sys.argv) > 1:
        upload_file(sys.argv[1])
    else:
        print("Usage: python upload_baidu.py --auth    (authorize once)")
        print("       python upload_baidu.py <file>   (upload a file)")
