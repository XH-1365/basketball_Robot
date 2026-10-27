# -*- coding: utf-8 -*-
"""
距离标定助手：被动读串口（不复位、不打断运行中的 main.py），
从 DET 上报里收集"人完整在画面里"的框高 h，反算建议的 FOCAL_PX。

用法:
  python tools/calib.py COM16 60 2.0
    端口           秒数  你站的真实距离(米)

原理:
  D_show = PERSON_H_M * FOCAL_OLD / h
  FOCAL_NEW = FOCAL_OLD * D_TRUE / D_show = D_TRUE * h / PERSON_H_M
  （身高在比例里会约掉，所以不知道身高也能标定，
    但 PERSON_H_M 设得越接近被标定者的真实身高，标定越准）
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
D_TRUE = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

PERSON_H = 1.70     # 必须和 body_detect.py 里的 PERSON_H_M 一致
FOCAL_OLD = 277.0   # 必须和 body_detect.py 里的 FOCAL_PX 一致
FRAME_H = 240

PAT = re.compile(r"#(\d+) x(\d+),y(\d+),w(\d+),h(\d+),([0-9.]+),([LRC])")


def median(a):
    b = sorted(a)
    n = len(b)
    if n == 0:
        return None
    return b[n // 2] if n % 2 else (b[n // 2 - 1] + b[n // 2]) / 2.0


def main():
    print("=" * 56)
    print(" 标定：真实距离 %.2f 米，采集 %d 秒" % (D_TRUE, SECS))
    print(" 请站直、全身进画面、别动")
    print("=" * 56)

    s = repl.open_port(PORT)
    samples = []       # (h, y, conf)
    clipped = 0
    lines = 0
    try:
        s.timeout = 0.2
        t0 = time.time()
        last = 0.0
        buf = ""
        while time.time() - t0 < SECS:
            n = s.in_waiting
            if n:
                buf += s.read(n).decode("utf-8", "replace")
                while "\n" in buf:
                    ln, buf = buf.split("\n", 1)
                    ln = ln.strip()
                    if not ln.startswith("DET "):
                        continue
                    lines += 1
                    sys.stdout.write("  " + ln + "\n")
                    sys.stdout.flush()
                    for m in PAT.finditer(ln):
                        y = int(m.group(3))
                        h = int(m.group(4))
                        conf = float(m.group(5))
                        if y <= 1 or y + h >= FRAME_H - 1:
                            clipped += 1
                            continue
                        samples.append((h, y, conf))
            else:
                time.sleep(0.04)
            el = time.time() - t0
            if el - last > 15:
                print("  ... 已读 %ds，有效样本 %d" % (int(el), len(samples)))
                last = el
    finally:
        try:
            s.dtr = False
            s.rts = False
            time.sleep(0.2)
        except Exception:
            pass
        s.close()

    print("-" * 56)
    print("DET 行 %d 条，有效样本 %d 个，因贴边丢弃 %d 个"
          % (lines, len(samples), clipped))

    if len(samples) < 3:
        print("!! 样本太少，标定不了。检查：")
        print("   - 人是不是站在画面里？(LCD 上应该能看到你的红框)")
        print("   - 是不是全身完整在画面里（头顶/脚别被切）")
        print("   - 板子是不是在跑？(peek.py 看有没有 DET 上报)")
        return 2

    hs = [s_[0] for s_ in samples]
    h_med = median(hs)
    d_show = PERSON_H * FOCAL_OLD / h_med
    focal_new = D_TRUE * h_med / PERSON_H

    print("框高 h: 最小 %d, 中位 %.0f, 最大 %d" % (min(hs), h_med, max(hs)))
    print("散布(h): %.0f 像素 (越小越稳)" % (max(hs) - min(hs)))
    print()
    print("  当前 FOCAL_PX = %.1f 时，屏幕会显示 %.2f 米" % (FOCAL_OLD, d_show))
    print("  你实际站在            %.2f 米" % D_TRUE)
    print()
    print("  >>> 建议 FOCAL_PX = %.1f  <<<" % focal_new)
    print("      ( = %.1f x %.2f / %.2f )" % (FOCAL_OLD, D_TRUE, d_show))
    return 0


sys.exit(main())
