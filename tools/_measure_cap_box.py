# -*- coding: utf-8 -*-
"""从按键照片(SHOT_WITH_HUD=True, 存的是画完框之后的图)里量出检测框的像素高度。

做法: 黄色框在 BGR 里是 (B低, G高, R高), 阈值分割 + 连通域, 报每个黄色块的
外接矩形。HUD 文字也是黄的, 先把顶部 30px 排除。
同一个告警区矩形在每张图里位置都一样 -> 一眼能认出来; 会动的那块就是人。
"""
import glob
import os
import sys

import cv2
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "testimgs", "caps")

FOCAL = 408.9
files = sorted(glob.glob(os.path.join(D, "cap_*.jpg")))
print("目录: %s  (%d 张)" % (D, len(files)))
print("FOCAL_PX = %.1f (板上是 H=1.80 的口径)\n" % FOCAL)

results = []
for f in files:
    img = cv2.imread(f)
    if img is None:
        print("%s 读不了" % os.path.basename(f))
        continue
    H, W = img.shape[:2]
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    # 黄色: R 和 G 都高, B 明显低
    mask = ((r > 150) & (g > 150) & (b < 110)).astype(np.uint8) * 255
    # 去掉顶部 HUD 文字区
    mask[:30, :] = 0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 60:                 # 文字残渣
            continue
        fill = area / float(w * h)    # 实心矩形 fill 接近 1(边框约 2*边/(宽))
        boxes.append((x, y, w, h, area, fill))
    boxes.sort(key=lambda t: -t[4])
    print("=" * 70)
    print("%s  (%dx%d)" % (os.path.basename(f), W, H))
    for x, y, w, h, area, fill in boxes[:5]:
        print("   黄色块 x=%3d y=%3d w=%3d h=%3d  area=%5d  fill=%.3f"
              % (x, y, w, h, area, fill))
    results.append((os.path.basename(f), boxes))

# 找出"每张都一样的"= 告警区; 会变的 = 人
if len(results) >= 2:
    print("\n" + "=" * 70)
    print("跨图对比(位置几乎不变的是告警区, 变的是人):")
    base = results[0][1]
    for name, bx in results:
        print("  %s" % name)
        for x, y, w, h, area, fill in bx[:3]:
            print("     x=%3d y=%3d w=%3d h=%3d" % (x, y, w, h))

print("\n" + "=" * 70)
print("如果上面能认出人那个框(高 h), 那么反算距离 D = %.1f * H / h:" % FOCAL)
print("  H=1.80 时: 见下面逐张输出")
print("")
for name, bx in results:
    # 取"不是告警区"的那个框: 简单起见取 h 最大的第二块, 或面积第二的
    cand = [b for b in bx if b[3] < 235]      # 告警区一般顶到底
    if not cand:
        continue
    x, y, w, h, area, fill = cand[0]
    d18 = FOCAL * 1.80 / h
    d17 = FOCAL * 1.70 / h
    print("  %s: 框 h=%d px  ->  H=1.80 报 %.2f m | H=1.70 报 %.2f m"
          % (name, h, d18, d17))
