#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-platform video downloader.
Supports: Douyin (闁硅埖鐗犻悡?, Xiaohongshu (閻忓繐绻掔€涒晜绋?, Kuaishou (闊浂鍋呮晶?
Usage: python run.py <share_link>
   or: python run.py
"""

import os, sys, time
from task_tracker import TaskTracker
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
    "wangyiyun": ["music.163.com"],
}


def detect_platform(url):
    url = url.split("#")[0]
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

def _batch_download_from_file(filepath, batch_all=False):
    if not os.path.exists(filepath):
        print("File not found: " + filepath)
        return
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    urls = [l for l in lines if l.startswith("http")]
    if not urls:
        print("No URLs found in file.")
        return
    print("=" * 50)
    print("Batch mode: {} URLs from {}".format(len(urls), filepath))
    print("=" * 50)
    ok, fail = 0, 0
    for i, url in enumerate(urls):
        print("\n>>> [{}/{}] {}".format(i+1, len(urls), url[:80]))
        platform = detect_platform(url)
        if not platform:
            print("  Unknown platform, skipping.")
            fail += 1
            continue
        print("  Platform: " + platform)
        try:
            if platform == "douyin":
                from platforms import douyin_api
                modal_id, _ = douyin_api.get_modalid_from_share_link(url)
                if modal_id:
                    page_url = "https://www.douyin.com/user/self?showTab=post&modal_id=" + modal_id
                    play_url = douyin_api.get_video_url(page_url)
                    if play_url: result = douyin_api.download_video(play_url, play_url.split("/")[-1]); _tracker.record_result(result) if _tracker else None
            elif platform == "xhs":
                from platforms import xhs; result = xhs.download(url); _tracker.record_result(result) if _tracker else None
            elif platform == "kuaishou":
                try:
                    from platforms import ks_pw; result = ks_pw.download(url); _tracker.record_result(result) if _tracker else None
                except:
                    from platforms import ks; result = ks.download(url); _tracker.record_result(result) if _tracker else None
            elif platform == "bilibili":
                from platforms import bili; result = bili.download(url,
                    start_from=_get_start_from() if "--start-from" in sys.argv else 1)
                if _tracker: _tracker.record_result(result)
            elif platform == "tencent":
                from platforms import tencent; result = tencent.download(url); _tracker.record_result(result) if _tracker else None
            elif platform == "youku":
                from platforms import youku; result = youku.download(url); _tracker.record_result(result) if _tracker else None
            elif platform == "ximalaya":
                from platforms import xm
                if "--login" in sys.argv:
                    xm._interactive_login_and_download(url, download_all=batch_all,
                        start_from=_get_start_from() if "--start-from" in sys.argv else 1)
                if _tracker: _tracker.record_result(result)
                else:
                    xm.download(url, download_all=batch_all,
                        start_from=_get_start_from() if "--start-from" in sys.argv else 1)
                if _tracker: _tracker.record_result(result)
            elif platform == "dushu":
                from platforms import dushu; dushu.download(url, download_all=batch_all)
            elif platform == "wangyiyun":
                from platforms import wangyiyun; wangyiyun.download(url)
            ok += 1
        except Exception as e:
            print("  ERROR: " + str(e)[:100])
            fail += 1
    print("\n" + "=" * 50)
    print("Done: {} OK, {} failed".format(ok, fail))


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
    if ("--file" in sys.argv or "-f" in sys.argv):
        try:
            idx = sys.argv.index("--file") if "--file" in sys.argv else sys.argv.index("-f")
            path = sys.argv[idx + 1]
            _batch_download_from_file(path, "--all" in sys.argv)
        except (ValueError, IndexError) as e:
            print("Usage: python run.py --file urls.txt [--all]")
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

    # Task tracker for upload
    _tracker = TaskTracker() if "--upload-baidu" in sys.argv else None
    if _tracker:
        _tracker.start_upload()
        print(f"  Douyin: https://v.douyin.com/xxxx/")
        print(f"  XHS:     http://xhslink.com/xxxx")
        print(f"  KS:      https://v.kuaishou.com/xxxx")
        print(f"  Bilibili: https://b23.tv/xxxx  or  https://www.bilibili.com/video/BVxxx")
        print(f"  Youku:    https://v.youku.com/v_show/id_XXXXX.html")
        print(f"  Tencent:  https://v.qq.com/x/page/xxxxx.html")

    print(f"Detected: {platform}")
    print("=" * 50)

    if platform == "douyin":
        from platforms import douyin_api
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
        from platforms import xhs
        xhs.download(link)

    elif platform == "kuaishou":
        try:
            from platforms import ks_pw
            result = ks_pw.download(link)
            if not result:
                raise Exception("Playwright failed")
        except Exception as e:
            print(f"[KS] Playwright failed ({e}), trying page scrape...")
            from platforms import ks
            ks.download(link)

    elif platform == "bilibili":
        from platforms import bili
        result = bili.download(link, start_from=_get_start_from())
        if _tracker: _tracker.record_result(result)

    elif platform == "tencent":
        from platforms import tencent
        tencent.download(link)
    elif platform == "youku":
        from platforms import youku
        youku.download(link)

    elif platform == "ximalaya":
        from platforms import xm
        if "--login" in sys.argv:
            result = xm._interactive_login_and_download(link, download_all=("--all" in sys.argv), start_from=_get_start_from()); _tracker.record_result(result) if _tracker else None
        else:
            result = xm.download(link, download_all=("--all" in sys.argv), start_from=_get_start_from()); _tracker.record_result(result) if _tracker else None

    elif platform == "wangyiyun":
        from platforms import wangyiyun
        result = wangyiyun.download(link, download_all=("--all" in sys.argv)); _tracker.record_result(result) if _tracker else None

    elif platform == "dushu":
        from platforms import dushu
        result = dushu.download(link, download_all=("--all" in sys.argv)); _tracker.record_result(result) if _tracker else None

    if _tracker:
        _tracker.wait()
        _tracker.save_log()
    print("\nDone. Check the output/ folder.")




if __name__ == "__main__":
    main()
