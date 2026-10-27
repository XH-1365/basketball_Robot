# -*- coding: utf-8 -*-
"""真人对拍: 人站在【已知距离】上, 看板上 HEIGHT 法的读数对不对。

被动抓串口 —— 不做 Ctrl-C, 让 main.py 自己跑, 所以测的就是板上真实配置。
解析 DET 行, 统计 h_px 和距离, 并按 5 秒一格打时间线(换位置会形成明显台阶)。

顺带做一件更有用的事: 如果给了真实距离和人的真实身高, 反解
    f_eff = h_px * D_true / H_true
拿它和 body_detect 里填的 FOCAL_PX 比 —— 这是一条【绝对尺度的交叉验证】,
和棋盘格那条链路互相独立(棋盘格靠的是靶标形状, 这条靠的是卷尺)。

用法:
  python tools/height_check.py COM16 25
  python tools/height_check.py COM16 25 --dist 3.00 --h 1.72
"""
import argparse
import re
import statistics
import sys
import time

import serial

DET_RE = re.compile(
    r"#(\d+)\s+x(\d+),y(\d+),w(\d+),h(\d+),([\d.]+)"
    r"(?:,HOT)?(?:,d([\d.]+)([A-Za-z]?))?")


def parse_dets(ln):
    """把一行 DET 里的【所有人】解析出来(可能有多人, 用 ' ; ' 分隔)。

    格式(见 body_detect.py 的串口上报):
      DET n=1 total=5 | #1 x125,y12,w58,h191,0.88,d2.4H
      可能带 ,HOT; 距离拿不到时是 ,d?  (此时 dist=None)
    返回 [(tid, x, y, w, h, score, dist, mode), ...]
    """
    out = []
    for m in DET_RE.finditer(ln):
        out.append((int(m.group(1)), float(m.group(2)), float(m.group(3)),
                    float(m.group(4)), float(m.group(5)), float(m.group(6)),
                    float(m.group(7)) if m.group(7) else None,
                    m.group(8) or ""))
    return out


BOOT_MARKS = ("sdcard init ok", "sdcard mount ok", "model load succeed",
              "[BODY] 就绪", "[BODY] 模型加载成功", "[SHOT] 存储",
              "[SHOT] 按键就绪", "find gc2145")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="COM16")
    ap.add_argument("secs", nargs="?", type=float, default=25.0)
    ap.add_argument("--dist", type=float, default=None,
                    help="人站位到镜头的真实距离(米), 拿卷尺量")
    ap.add_argument("--h", type=float, default=1.70,
                    help="人的真实身高(米)")
    ap.add_argument("--focal", type=float, default=408.9,
                    help="body_detect 当前填的 FOCAL_PX, 用来对照")
    args = ap.parse_args()

    s = serial.Serial()
    s.port = args.port
    s.baudrate = 115200
    s.timeout = 0.1
    s.dtr = False
    s.rts = False
    s.open()
    s.dtr = False
    s.rts = False
    s.reset_input_buffer()

    print(">>> DTR 复位, 让 main.py 自启(不做 Ctrl-C) ...")
    s.dtr = True
    time.sleep(0.3)
    s.dtr = False

    t0 = time.time()
    samples = []           # (t, tid, x, y, w, h, dist, mode)
    boot = []
    last = 0.0
    while time.time() - t0 < args.secs:
        d = s.read(8192)
        if not d:
            continue
        txt = d.decode("utf-8", "replace")
        sys.stdout.write(txt)
        sys.stdout.flush()
        now = time.time() - t0
        for ln in txt.splitlines():
            if any(k in ln for k in BOOT_MARKS):
                boot.append(ln.strip())
            for one in parse_dets(ln):
                samples.append((now,) + one)
        # 每 5 秒打一格时间线
        el = time.time() - t0
        if el - last >= 5.0:
            last = el
            win = [x for x in samples if x[0] >= el - 5.0]
            if win:
                hh = [x[5] for x in win]
                dd = [x[7] for x in win if x[7]]
                print("[t=%4.1fs] n=%2d  h_px 中位 %5.1f (%.0f~%.0f)  %s"
                      % (el, len(win), statistics.median(hh), min(hh), max(hh),
                         ("距离中位 %.2f m" % statistics.median(dd)) if dd
                         else "无距离"))
            else:
                print("[t=%4.1fs] n= 0  (没检测到人)" % el)

    s.close()

    print("\n" + "=" * 66)
    print("=== 开机确认 ===")
    for b in boot:
        print("  " + b)
    print("=" * 66)
    if not samples:
        print("!! 一个 DET 行都没抓到 —— 人没在画面里? 模型没加载?")
        return 1

    # 按 tid 分组(取样本最多的那个 tid = 主体)
    by_tid = {}
    for sm in samples:
        by_tid.setdefault(sm[1], []).append(sm)
    print("=== 分跟踪 id 统计 ===")
    print("%5s %6s %10s %10s %10s %9s %6s"
          % ("tid", "帧数", "h中位", "h均值", "h标准差", "距离中位", "模式"))
    main_tid, main_n = None, -1
    for tid, ss in sorted(by_tid.items()):
        hh = [x[5] for x in ss]
        dd = [x[7] for x in ss if x[7]]
        modes = sorted(set(x[8] for x in ss if x[8]))
        print("%5d %6d %10.1f %10.1f %10.2f %9s %6s"
              % (tid, len(ss), statistics.median(hh), statistics.mean(hh),
                 statistics.pstdev(hh),
                 ("%.2f m" % statistics.median(dd)) if dd else "-",
                 "/".join(modes) or "-"))
        if len(ss) > main_n:
            main_tid, main_n = tid, len(ss)

    ss = by_tid[main_tid]
    hh = [x[5] for x in ss]
    dd = [x[7] for x in ss if x[7]]
    h_med = statistics.median(hh)
    modes = sorted(set(x[8] for x in ss if x[8]))
    print("")
    print(">>> 主体 = tid %d, %d 帧, h_px 中位 %.1f, 距离中位 %s, 模式 %s"
          % (main_tid, len(ss), h_med,
             ("%.2f m" % statistics.median(dd)) if dd else "-", modes or "-"))

    print("")
    print("=" * 66)
    if args.dist:
        f_eff = h_med * args.dist / args.h
        d_pred = args.focal * args.h / h_med
        print("=== 和真实距离 %.2f m 对照 ===" % args.dist)
        print("  板上报的距离(中位)      : %s"
              % (("%.2f m" % statistics.median(dd)) if dd else "-"))
        print("  板上 FOCAL_PX           : %.1f" % args.focal)
        print("  用 h_px=%.1f 反推的距离  : %.2f m   (D = FOCAL_PX*H/h)"
              % (h_med, d_pred))
        print("  真实距离                : %.2f m" % args.dist)
        if d_pred > 0:
            print("  相对偏差                : %+.1f%%"
                  % ((d_pred / args.dist - 1) * 100))
        print("")
        print("=== 反解有效焦距(独立于棋盘格的绝对检验) ===")
        print("  f_eff = h_px * D_true / H_true = %.1f * %.2f / %.2f = %.1f"
              % (h_med, args.dist, args.h, f_eff))
        print("  与 body_detect 里填的 %.1f 相比: %+.1f%%"
              % (args.focal, (f_eff / args.focal - 1) * 100))
        print("  (f_eff 是人【真实身高】的函数, 身高给错就整体缩放)")
    else:
        print("=== 没给 --dist, 只出统计 ===")
        print("  想算绝对检验, 加参数:  --dist 3.00 --h 1.72")
    return 0


if __name__ == "__main__":
    sys.exit(main())
