# -*- coding: utf-8 -*-
"""Unified cookie management for all platforms.
Cookies are stored in ./cookies/ directory as JSON files.
"""

import os, json

COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies")

PLATFORMS = {
    "douyin": {
        "file": "douyin.json",
        "help": "Login to creator.douyin.com in Chrome, then run: python login.py douyin",
    },
    "xhs": {
        "file": "xhs.json",
        "help": "Login to xiaohongshu.com in Chrome, press F12 -> Application -> Cookies -> xiaohongshu.com, copy the web_session value, then run: python login.py xhs --cookie 'web_session=xxx'",
    },
    "kuaishou": {
        "file": "kuaishou.json", 
        "help": "Login to kuaishou.com in Chrome, press F12 -> Application -> Cookies -> kuaishou.com, copy all cookies, then run: python login.py kuaishou --cookie 'kuaishou.server.web_st=xxx; did=yyy'",
    },
    "tencent": {
        "file": "tencent.json",
        "help": "Login to v.qq.com in Chrome, then run: python login.py tencent",
    },
    "youku": {
        "file": "youku.json",
        "help": "Login to youku.com in Chrome, then run: python login.py youku",
    },
    "bilibili": {
        "file": "bilibili.json",
        "help": "Login to bilibili.com in Chrome, press F12 -> Application -> Cookies -> bilibili.com, copy SESSDATA value, then run: python login.py bilibili --cookie 'SESSDATA=xxx'",
    },
    "wangyiyun": {
        "file": "wangyiyun.json",
        "help": "Login to music.163.com in Chrome, then run: python login.py wangyiyun",
    },
}


def get_cookie_path(platform):
    """Get cookie file path for a platform"""
    cfg = PLATFORMS.get(platform)
    if not cfg:
        return None
    return os.path.join(COOKIE_DIR, cfg["file"])


def load_cookie(platform):
    """Load saved cookie for a platform. Returns dict or string or None."""
    path = get_cookie_path(platform)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cookie", data.get("cookies", None))


def save_cookie(platform, cookie_value):
    """Save cookie for a platform"""
    path = get_cookie_path(platform)
    if not path:
        return False
    os.makedirs(COOKIE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cookie": cookie_value, "platform": platform}, f, ensure_ascii=False, indent=2)
    print(f"[COOKIE] Saved for {platform}: {path}")
    return True


def status():
    """Show cookie status for all platforms"""
    print("Cookie status:")
    for name, cfg in PLATFORMS.items():
        path = os.path.join(COOKIE_DIR, cfg["file"])
        exists = os.path.exists(path)
        print(f"  {name:12s} {'[SAVED]' if exists else '[MISSING]'}" +
              ("" if exists else f"  -- {cfg['help'][:60]}..."))