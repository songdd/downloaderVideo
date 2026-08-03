#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-platform video downloader.
Supports: Douyin (闁硅埖鐗犻悡?, Xiaohongshu (閻忓繐绻掔€涒晜绋?, Kuaishou (闊浂鍋呮晶?
Usage: python run.py <share_link>
   or: python run.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.chdir(os.path.dirname(os.path.abspath(__file__)))

PLATFORMS = {
    "douyin":  ["douyin.com", "iesdouyin.com"],
    "xhs":     ["xiaohongshu.com", "xhslink.com"],
    "kuaishou": ["kuaishou.com", "kuaishou"],
    "bilibili":  ["bilibili.com", "b23.tv"],
    "youku":     ["youku.com", "v.youku.com"],
    "tencent":   ["v.qq.com"],
    "dushu":     ["dushu365.com"],
    "ximalaya":  ["ximalaya.com"],
}


def detect_platform(url):
    for name, domains in PLATFORMS.items():
        for d in domains:
            if d in url.lower():
                return name
    return None

def _get_start_from():
    try:
        idx = sys.argv.index("--start-from")
        return int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return 1


def main():
    # Handle special commands
    if len(sys.argv) > 1 and sys.argv[1] in ("-l",):
        platform = sys.argv[2] if len(sys.argv) > 2 else input("Platform (douyin/xhs/kuaishou/bilibili/youku/tencent): ").strip()
        from login import login_platform
        login_platform(platform)
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--status", "-s"):
        from cookies import status
        status()
        return

    link = None
    for a in sys.argv[1:]:
        if a.startswith("http"):
            link = a
            break
    if not link:
        link = input("Paste share link: ").strip()
    if not link:
        print("No link provided.")
        return
    if not link.startswith("http"):
        print("Invalid link. Must start with http:// or https://")
        return

    platform = detect_platform(link)
    if not platform:
        print(f"Unknown platform. Supported: {', '.join(PLATFORMS.keys())}")
        print(f"  Douyin: https://v.douyin.com/xxxx/")
        print(f"  XHS:     http://xhslink.com/xxxx")
        print(f"  KS:      https://v.kuaishou.com/xxxx")
        print(f"  Bilibili: https://b23.tv/xxxx  or  https://www.bilibili.com/video/BVxxx")
        print(f"  Youku:    https://v.youku.com/v_show/id_XXXXX.html")
        print(f"  Tencent:  https://v.qq.com/x/page/xxxxx.html")

    print(f"Detected: {platform}")
    print("=" * 50)

    if platform == "douyin":
        import douyin_api
        modal_id, video_url = douyin_api.get_modalid_from_share_link(link)
        if not modal_id:
            print("[FAIL] Could not extract video ID.")
            return
        print(f"Video ID: {modal_id}")
        page_url = f"https://www.douyin.com/user/self?showTab=post&modal_id={modal_id}"
        play_url = douyin_api.get_video_url(page_url)
        if not play_url:
            print("[FAIL] Could not get video play URL.")
            return
        print(f"Play URL: {play_url[:80]}...")
        douyin_api.download_video(play_url, play_url.split("/")[-1])

    elif platform == "xhs":
        import xhs
        xhs.download(link)

    elif platform == "kuaishou":
        try:
            import ks_pw
            result = ks_pw.download(link)
            if not result:
                raise Exception("Playwright failed")
        except Exception as e:
            print(f"[KS] Playwright failed ({e}), trying page scrape...")
            import ks
            ks.download(link)

    elif platform == "bilibili":
        import bili
        bili.download(link, start_from=_get_start_from())

    elif platform == "tencent":
        import tencent
        tencent.download(link)
    elif platform == "youku":
        import youku
        youku.download(link)

    elif platform == "ximalaya":
        import xm
        if "--login" in sys.argv:
            xm._interactive_login_and_download(link, download_all=("--all" in sys.argv), start_from=_get_start_from())
        else:
            xm.download(link, download_all=("--all" in sys.argv), start_from=_get_start_from())

    elif platform == "dushu":
        import dushu
        dushu.download(link, download_all=("--all" in sys.argv))

    print("\nDone. Check the output/ folder.")


if __name__ == "__main__":
    main()
