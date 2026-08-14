#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量重命名下载文件，支持三种常用规则。

规则（--mode）:
  strip  去掉文件前缀：xm_xxx.m4a -> xxx.m4a
  seq    按时间戳从小到大编号：xm_前言_20260814_161854.m4a -> 001_前言.m4a
  vol    同卷加相同卷编号，卷号按各卷最早时间戳排序：
         xm_晋朝那些事儿. 壹, 魏晋风度卷001_20260814_124249.m4a
             -> 1_晋朝那些事儿. 壹, 魏晋风度卷001.m4a

用法示例:
  python rename_files.py "output\\某目录" --mode seq --dry-run   # 先预览，不执行
  python rename_files.py "output\\某目录" --mode seq             # 执行改名
  python rename_files.py "output\\某目录" --mode vol
  python rename_files.py --undo rename_map_20260814_120000.csv  # 按日志还原
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime


def parse_ts(name, prefix):
    """解析 xm_音频名_YYYYMMDD_HHMMSS.ext 形式，返回 (音频名, 时间戳, 扩展名)。"""
    pat = "^" + re.escape(prefix) + r"(.+)_(\d{8})_(\d{6})\.([A-Za-z0-9]+)$"
    m = re.match(pat, name)
    if not m:
        return None
    audio, day, t, ext = m.groups()
    return audio, day + "_" + t, ext


def split_volume(audio):
    """从音频名尾部提取卷号，返回 (系列名, 集号)。集号可能为 None。"""
    m = re.search(r"卷(\d+)$", audio)
    if m:
        return audio[: m.start()], int(m.group(1))
    m = re.search(r"(\d{2,3})$", audio)
    if m:
        return audio[: m.start()], int(m.group(1))
    return audio, None


def plan_strip(files, prefix):
    plan, skipped = [], []
    for f in sorted(files, key=lambda x: x.name):
        if f.name.startswith(prefix) and len(f.name) > len(prefix):
            plan.append((f.name, f.name[len(prefix):]))
        else:
            skipped.append(f.name)
    return plan, skipped


def plan_seq(files, prefix, digits):
    items, skipped = [], []
    for f in files:
        p = parse_ts(f.name, prefix)
        if not p:
            skipped.append(f.name)
            continue
        items.append((f.name, p))
    items.sort(key=lambda x: (x[1][1], x[0]))  # 时间戳，相同则按原名
    plan = []
    for i, (old, (audio, _ts, ext)) in enumerate(items, 1):
        plan.append((old, "%s_%s.%s" % (str(i).zfill(digits), audio, ext)))
    return plan, skipped


def plan_vol(files, prefix):
    items, skipped = [], []
    for f in files:
        p = parse_ts(f.name, prefix)
        if not p:
            skipped.append(f.name)
            continue
        audio, ts, ext = p
        series, _ep = split_volume(audio)
        items.append({"old": f.name, "audio": audio, "ts": ts, "ext": ext, "series": series})

    # 卷号：按该卷最早时间戳排序，相同时按系列名
    earliest = {}
    for it in items:
        if it["series"] not in earliest or it["ts"] < earliest[it["series"]]:
            earliest[it["series"]] = it["ts"]
    order = sorted(earliest.items(), key=lambda kv: (kv[1], kv[0]))
    vol_index = {series: i + 1 for i, (series, _) in enumerate(order)}

    plan = []
    for it in items:
        plan.append((it["old"], "%d_%s.%s" % (vol_index[it["series"]], it["audio"], it["ext"])))
    return plan, skipped, [(s, vol_index[s]) for s, _ in order]


def check_collisions(dirpath, plan):
    problems, targets = [], {}
    for old, new in plan:
        if old == new:
            continue
        if new in targets:
            problems.append("冲突：%s 与 %s 都指向 %s" % (targets[new], old, new))
        else:
            targets[new] = old
        if os.path.exists(os.path.join(dirpath, new)):
            problems.append("目标已存在：%s" % new)
    return problems


def show_plan(plan, skipped):
    for old, new in plan[:40]:
        print("  %s -> %s" % (old, new))
    if len(plan) > 40:
        print("  ... 共 %d 条" % len(plan))
    if skipped:
        print("跳过(不符合规则) %d 个：%s" % (len(skipped), ", ".join(skipped[:10])))


def apply_plan(dirpath, plan, log_path):
    renamed = 0
    rows = []
    for old, new in plan:
        if old == new:
            continue
        src, dst = os.path.join(dirpath, old), os.path.join(dirpath, new)
        if not os.path.exists(src):
            print("跳过(源不存在)：%s" % old)
            continue
        os.rename(src, dst)
        rows.append((src, dst))
        renamed += 1
    with open(log_path, "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["old_path", "new_path"])
        w.writerows(rows)
    return renamed


def undo(log_path):
    if not os.path.exists(log_path):
        print("日志不存在：%s" % log_path)
        sys.exit(1)
    restored = 0
    with open(log_path, "r", encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            old, new = row["old_path"], row["new_path"]
            if not os.path.exists(new):
                print("跳过(目标不存在)：%s" % new)
                continue
            os.rename(new, old)
            restored += 1
    print("还原 %d 个文件" % restored)


def main():
    usage = """用法示例：
  # 去掉 xm_ 前缀：xm_xxx.m4a -> xxx.m4a
  python rename_files.py "output\\某目录" --mode strip

  # 按时间戳从小到大编号：xm_前言_20260814_161854.m4a -> 001_前言.m4a
  python rename_files.py "output\\某目录" --mode seq

  # 同卷加相同卷编号，卷号按各卷最早时间戳排序：
  #   xm_晋朝那些事儿. 壹, 魏晋风度卷001_20260814_124249.m4a -> 1_晋朝那些事儿. 壹, 魏晋风度卷001.m4a
  python rename_files.py "output\\某目录" --mode vol

细节说明：
  * 文件名格式：<prefix>音频名_YYYYMMDD_HHMMSS.ext，默认 prefix 为 xm_。
  * 任何规则都可先加 --dry-run 预览改名计划，不真正执行。
  * 执行时会自动生成日志 rename_map_*.csv（可用 --log 指定路径），记录旧、新路径。
  * 用 --undo 日志可一键还原改名。
  * 改名前自动检查目标冲突，有冲突则拒绝执行。
"""

    ap = argparse.ArgumentParser(
        description="批量重命名下载文件，支持 strip / seq / vol 三种规则",
        epilog=usage,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("dir", nargs="?", help="要处理的目录")
    ap.add_argument("--mode", choices=["strip", "seq", "vol"], help="改名规则：strip 去前缀 / seq 按时间戳编号 / vol 按卷加卷编号")
    ap.add_argument("--prefix", default="xm_", help="文件前缀，默认 xm_")
    ap.add_argument("--digits", type=int, default=3, help="seq 编号补零位数，默认 3")
    ap.add_argument("--dry-run", action="store_true", help="只打印改名计划，不真正执行")
    ap.add_argument("--log", default=None, help="改名日志 CSV 路径，默认自动生成到当前目录")
    ap.add_argument("--undo", metavar="LOG", help="按日志 CSV 还原改名")
    args = ap.parse_args()

    if args.undo:
        undo(args.undo)
        return

    if not args.dir or not os.path.isdir(args.dir):
        print("目录不存在或未指定：%r" % (args.dir or ""))
        sys.exit(1)

    files = [f for f in os.scandir(args.dir) if f.is_file()]
    if not files:
        print("目录里没有文件")
        return

    plan, skipped = [], []
    if args.mode == "strip":
        plan, skipped = plan_strip(files, args.prefix)
    elif args.mode == "seq":
        plan, skipped = plan_seq(files, args.prefix, args.digits)
    elif args.mode == "vol":
        plan, skipped, order = plan_vol(files, args.prefix)
        print("卷编号分配：")
        for series, idx in order:
            print("  %d  %s" % (idx, series))
    else:
        print("请指定 --mode strip|seq|vol")
        sys.exit(1)

    if not plan:
        print("没有匹配 %r 前缀的文件" % args.prefix)
        return

    problems = check_collisions(args.dir, plan)
    if problems:
        print("发现问题，未执行：")
        for p in problems:
            print("  " + p)
        sys.exit(1)

    print("计划改名 %d 个文件" % len(plan))
    if args.dry_run:
        show_plan(plan, skipped)
        return

    log_path = args.log or os.path.join(
        os.getcwd(), "rename_map_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    renamed = apply_plan(args.dir, plan, log_path)
    print("完成：改名 %d 个" % renamed)
    print("日志：%s（可用 --undo 还原）" % log_path)


if __name__ == "__main__":
    main()
