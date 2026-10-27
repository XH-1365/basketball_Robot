# -*- coding: utf-8 -*-
# ============================================================
#  标定时 tag 能摆多远 —— 测 find_apriltags 的最小可检边长(像素)
#
#  为什么重要:
#    标定要求把 tag 摆在若干【已知距离】上。摆多远取决于两件事:
#      side_px = FOCAL_PX * TAG_W_M / D
#    所以 D 越大 side_px 越小, 小到检不到就白跑一趟。
#    事先测出最小可检边长 N, 就能反推最远标定距离:
#      D_max = FOCAL_PX * TAG_W_M / N
#
#  做法: 在【固定 160x120 画布】上(和 QQVGA 摄像头帧同尺寸)画不同格宽的 tag,
#        格宽 1..8 -> 外沿边长 8..64 px, 看哪一档开始检不到。
#
#  运行: python tools/live_run.py COM16 tools/tag_min_probe.py 30
# ============================================================

import gc
import time

import image

GRID = [
    "..........",
    ".########.",
    ".#..#.#.#.",
    ".##...#.#.",
    ".##..####.",
    ".#.#.####.",
    ".##.#..##.",
    ".####.###.",
    ".########.",
    "..........",
]

W, H = 160, 120
N = len(GRID)


def build(cell):
    img = image.Image(size=(W, H))
    img.draw_rectangle(0, 0, W, H, color=(255, 255, 255), fill=True)
    box = N * cell
    ox = (W - box) // 2
    oy = (H - box) // 2
    if ox < 0:
        ox = 0
    if oy < 0:
        oy = 0
    for r in range(N):
        for c in range(N):
            if GRID[r][c] == "#":
                img.draw_rectangle(ox + c * cell, oy + r * cell, cell, cell,
                                   color=(0, 0, 0), fill=True)
    return img


def main():
    print("=" * 60)
    print("最小可检 tag 尺寸 (画布固定 %dx%d, 同 QQVGA)" % (W, H))
    print("格宽 1..9 -> 外沿边长 8..72 px")
    print("=" * 60)

    results = []
    for cell in range(1, 10):
        side_exp = 8 * cell
        img = build(cell)
        try:
            tags = img.find_apriltags()
        except Exception as e:
            print("cell=%d 外沿=%2dpx -> 异常 %s" % (cell, side_exp, repr(e)))
            continue
        if not tags:
            print("cell=%d 外沿=%2dpx 每格%2dpx -> 未检出" % (cell, side_exp, cell))
            results.append((cell, side_exp, None))
            continue
        tg = tags[0]
        w = tg.w()
        try:
            cs = tg.corners()
            tot = 0.0
            import math
            for i in range(4):
                x0, y0 = cs[i]
                x1, y1 = cs[(i + 1) % 4]
                tot += math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
            side = tot / 4.0
        except Exception:
            side = None
        print("cell=%d 外沿=%2dpx 每格%2dpx -> 检出 id%d w=%d side=%s"
              % (cell, side_exp, cell, tg.id(), w,
                 ("%.1f" % side) if side else "n/a"))
        results.append((cell, side_exp, w))
        gc.collect()
        time.sleep_ms(60)

    print("=" * 60)
    det = [(c, s) for c, s, w in results if w is not None]
    und = [(c, s) for c, s, w in results if w is None]
    if det:
        mn = min(s for _, s in det)
        print("检出的最小外沿边长: %d px (格宽 %d)" % (mn, mn // 8))
    if und:
        mx = max(s for _, s in und)
        print("没检出的最大外沿边长: %d px (格宽 %d)" % (mx, mx // 8))
    print("")
    print("换算成『tag 能摆多远』(f 用 277, tag 外沿 0.100m):")
    for name, px in (("最保守", 48), ("实测下限附近", 40), ("乐观", 32)):
        print("  若最小可检边长 = %2d px -> 最远标定距离 = 277*0.100/%d = %.2f m"
              % (px, px, 277.0 * 0.100 / px))
    print("=" * 60)


main()
