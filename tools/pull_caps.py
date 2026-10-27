# -*- coding: utf-8 -*-
"""拉回板上 /sd/cap_*.jpg (body_detect 按键/定时存的图)。

用法:
  python tools/pull_caps.py COM16            # 列出来, 拉最后 3 张
  python tools/pull_caps.py COM16 5          # 拉最后 5 张
  python tools/pull_caps.py COM16 5 --list-only
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import repl as R  # noqa: E402

OUT = os.path.join(ROOT, "testimgs", "caps")


def list_caps(s):
    out, err = R.exec_code(
        s,
        "import os\n"
        "ns = []\n"
        "for n in os.listdir('/sd'):\n"
        "    if n.startswith('cap_') and n.endswith('.jpg'):\n"
        "        ns.append(n)\n"
        "print('|'.join(sorted(ns)))\n",
        echo=False)
    txt = out.decode("utf-8", "replace").strip()
    ids = []
    for name in txt.split("|"):
        name = name.strip()
        m = re.match(r"cap_(\d+)\.jpg$", name)
        if m:
            ids.append(int(m.group(1)))
    return sorted(ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="COM16")
    ap.add_argument("n", nargs="?", type=int, default=3, help="拉最后 N 张")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(OUT):
        os.makedirs(OUT)

    s = R.open_port(args.port)
    try:
        R.drain(s, 0.8)
        print(">>> 打断板上脚本 ...")
        if not R.sync_to_prompt(s, timeout=12.0):
            print(">>> Ctrl-C 没反应, 改用硬复位 ...")
            R.hard_reset(s)

        ids = list_caps(s)
        print(">>> /sd/cap_*.jpg 共 %d 张: %s"
              % (len(ids), ids if len(ids) <= 20 else "%s ..." % ids[:20]))
        if not ids:
            return 1
        if args.list_only:
            return 0

        want = ids[-args.n:]
        print(">>> 拉最后 %d 张: %s" % (len(want), want))
        for i in want:
            remote = "/sd/cap_%03d.jpg" % i
            local = os.path.join(OUT, "cap_%03d.jpg" % i)
            try:
                R.cmd_get(s, remote, local)
            except Exception as e:
                print("!! 拉 %s 失败: %r" % (remote, e))
        print(">>> 完成 -> %s" % OUT)
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
