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


HELP_TEXT = """
==========================================================
  Multi-Platform Media Downloader - Usage
==========================================================

Usage: python run.py <url> [options]

EXAMPLES
--------
# Single download
python run.py https://www.bilibili.com/video/BVxxxxxx
python run.py https://music.163.com/#/song?id=1210496
python run.py https://www.ximalaya.com/sound/72982155

# Batch download (all episodes/tracks)
python run.py --all <url>
python run.py --all https://www.bilibili.com/bangumi/play/ep327107
python run.py --all https://www.ximalaya.com/album/13396678

# Start from episode N
python run.py --all --start-from 10 <url>

# Batch from file (one URL per line, # for comments)
python run.py --file urls.txt
python run.py --file urls.txt --all

# Login / cookie management
python run.py -l <platform>     # e.g. -l bilibili
python run.py -s                # show cookie status

# NetEase Music browsing
python run.py https://music.163.com/#/discover/toplist        # list all charts
python run.py https://music.163.com/#/discover/playlist        # discover playlists
python run.py https://music.163.com/#/discover/playlist --cat 古风 --page 1 --endpage 3

# Ximalaya interactive login (for paid tracks)
python run.py --login --all https://www.ximalaya.com/album/xxx

# Baidu Netdisk upload after download
python run.py --upload-baidu <url>
python run.py --upload-baidu --baidu-dir "/music/排行榜" <url>
python upload_baidu.py --auth     # first time OAuth

OPTIONS
-------
--all               Download entire season/album/course/playlist
--start-from N      Start downloading from episode N
--to N              Stop downloading at episode N
--tracks 3,5,10    Download only the listed episode numbers
--file path         Batch download from URL list file
--login             Interactive browser login (Tencent, Ximalaya)
--upload-baidu      Upload files to Baidu Netdisk after download
--baidu-dir path    Custom Baidu Netdisk upload directory
--cat name          Filter discover playlists by category
--page N            Browse discover playlists page N
--endpage M         List pages N..M of discover playlists
-l <platform>       Save login cookie for a platform
-s                  Show cookie status for all platforms
-h, --help          Show this help

PLATFORMS: douyin, xhs, kuaishou, bilibili, youku, tencent,
           dushu365, ximalaya, wangyiyun(music.163.com)
"""

def _get_start_from():
    try:
        idx = sys.argv.index("--start-from")
        return int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return 1

def _get_to():
    try:
        idx = sys.argv.index("--to")
        return int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return None

def _get_tracks():
    try:
        idx = sys.argv.index("--tracks")
        return sys.argv[idx + 1]
    except (ValueError, IndexError):
        return ""

def _batch_download_from_file(filepath, batch_all=False, _tracker=None):
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
                    result = xm._interactive_login_and_download(url, download_all=batch_all,
                        start_from=_get_start_from() if "--start-from" in sys.argv else 1,
                        to=_get_to(), tracks=_get_tracks())
                else:
                    result = xm.download(url, download_all=batch_all,
                        start_from=_get_start_from() if "--start-from" in sys.argv else 1,
                        to=_get_to(), tracks=_get_tracks())
                if _tracker: _tracker.record_result(result)
            elif platform == "dushu":
                from platforms import dushu; result = dushu.download(url, download_all=batch_all); _tracker.record_result(result) if _tracker else None
            elif platform == "wangyiyun":
                from platforms import wangyiyun; result = wangyiyun.download(url); _tracker.record_result(result) if _tracker else None
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
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(HELP_TEXT)
        return

    # Task tracker for Baidu upload (created once, shared by all download paths)
    _tracker = TaskTracker() if "--upload-baidu" in sys.argv else None

    if ("--file" in sys.argv or "-f" in sys.argv):
        try:
            idx = sys.argv.index("--file") if "--file" in sys.argv else sys.argv.index("-f")
            path = sys.argv[idx + 1]
            if _tracker:
                _tracker.start_upload()
            _batch_download_from_file(path, "--all" in sys.argv, _tracker)
        except (ValueError, IndexError) as e:
            print("Usage: python run.py --file urls.txt [--all]")
        finally:
            if _tracker:
                _tracker.wait()
                _tracker.save_log()
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

    if _tracker:
        _tracker.start_upload()

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
            result = xm._interactive_login_and_download(link, download_all=("--all" in sys.argv), start_from=_get_start_from(), to=_get_to(), tracks=_get_tracks()); _tracker.record_result(result) if _tracker else None
        else:
            result = xm.download(link, download_all=("--all" in sys.argv), start_from=_get_start_from(), to=_get_to(), tracks=_get_tracks()); _tracker.record_result(result) if _tracker else None

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
