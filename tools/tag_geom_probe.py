# -*- coding: utf-8 -*-
# ============================================================
#  tag.w() 几何实测 v2 —— 密集扫格宽, 并打印 rect()/corners()
#
#  v1 结果: cell=6/10/12/16 都是 w ≈ 8*cell (外沿), 但 cell=8 偏 +12.5%,
#  cell=20 干脆检不出来。这两个反常必须弄清, 否则标定会带一个说不清的偏差。
#
#  本脚本:
#    - 扫 cell = 5..19 全部取值, 看 w 对 8*cell 的残差是不是常数/是否与格宽有关
#    - 打印 rect() 和 corners(), 看检测到的四边形到底是哪一圈
#    - 用 get_pixel 扫外沿边界那一列, 确认画出来的黑边外沿究竟在第几像素
#
#  运行: python tools/live_run.py COM16 tools/tag_geom_probe2.py 60
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

N = len(GRID)
BODY = N - 2      # 8
DATA = N - 4      # 6


def build_tag(cell):
    side = N * cell
    img = image.Image(size=(side, side))
    img.draw_rectangle(0, 0, side, side, color=(255, 255, 255), fill=True)
    for r in range(N):
        for c in range(N):
            if GRID[r][c] == "#":
                img.draw_rectangle(c * cell, r * cell, cell, cell,
                                   color=(0, 0, 0), fill=True)
    return img, side


def is_black(px):
    return px[0] < 128 and px[1] < 128 and px[2] < 128


def edge_scan(img, cell, side):
    """沿中间那一行往右扫, 找第一段黑像素的起止列 -> 就是左边黑框的真实外沿/内沿。"""
    y = side // 2
    xs = []
    for x in range(side):
        if is_black(img.get_pixel(x, y)):
            xs.append(x)
    if not xs:
        return None
    # 左边黑框: 第一段连续黑
    start = xs[0]
    end = start
    for x in xs:
        if x == end + 1:
            end = x
        elif x > end + 1:
            break
    return start, end


def main():
    print("=" * 64)
    print("tag.w() 几何实测 v2: 扫 cell=5..19")
    print("tag 本体 = %d 格(外沿), 数据区 = %d 格(内沿)" % (BODY, DATA))
    print("=" * 64)

    rows = []
    for cell in range(5, 20):
        side = N * cell
        img, side = build_tag(cell)
        exp_out = BODY * cell
        exp_in = DATA * cell

        le = edge_scan(img, cell, side)
        if le is None:
            print("[cell=%2d] 边缘扫描失败, 跳过" % cell)
            continue
        drawn_start, drawn_end = le

        try:
            tags = img.find_apriltags()
        except Exception as e:
            print("[cell=%2d] find_apriltags 异常: %s" % (cell, repr(e)))
            continue

        if not tags:
            print("[cell=%2d] 画布%3d 画出左边黑框 x=%d..%d(宽%d)  期望外沿=%d 内沿=%d"
                  "  -> 没检出"
                  % (cell, side, drawn_start, drawn_end,
                     drawn_end - drawn_start + 1, exp_out, exp_in))
            continue

        tg = tags[0]
        w = tg.w()
        h = tg.h()
        cx = tg.cx()
        cy = tg.cy()
        tid = tg.id()
        try:
            rect = tg.rect()
        except Exception:
            rect = None
        try:
            corners = tg.corners()
        except Exception:
            corners = None

        # 检出的左边框像素位置(由 rect 推) 与画出来的外沿比较
        print("[cell=%2d] 画布%3d 画出左边黑框 x=%d..%d"
              % (cell, side, drawn_start, drawn_end))
        print("          TAG id%d w=%d h=%d cx=%d cy=%d rect=%s"
              % (tid, w, h, cx, cy, rect))
        if corners:
            print("          corners=%s" % (corners,))
        d = w - exp_out
        print("          w-外沿=%+d px   w/外沿=%.4f   w/内沿=%.4f"
              % (d, w / float(exp_out), w / float(exp_in)))
        rows.append((cell, w, exp_out, d))
        gc.collect()
        time.sleep_ms(80)

    print("=" * 64)
    print("汇总: cell  w 与外沿(8*cell)的差")
    for cell, w, exp, d in rows:
        print("  cell=%2d  8*cell=%3d  w=%3d  差=%+d" % (cell, exp, w, d))
    if rows:
        ds = [r[3] for r in rows]
        print("  差值范围: %+d ~ %+d" % (min(ds), max(ds)))
        # 判断是"常数偏移"还是"比例偏移"
        import math
        n = len(rows)
        xs = [r[2] for r in rows]
        ys = [r[1] for r in rows]
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        slope = num / den if den else 0
        print("  线性回归 w = %.4f * (8*cell) + %.2f" % (slope, my - slope * mx))
        print("  斜率接近 1 = 只是常数偏移(标定会吸收掉); 明显偏离 1 = 有比例误差(危险)")
    print("=" * 64)


main()
