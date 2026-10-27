# -*- coding: utf-8 -*-
"""v3: 按颜色把【橙色的人框】和【黄色的告警区框】分开, 量出人框的高度。

依据 body_detect.py:
    COLOR_ALERT = (255, 160, 0)   人在告警区内 -> 框画成【橙色】
    COLOR_ZONE  = (255, 255, 0)   告警区边框  -> 【黄色】
    COLOR_TEXT  = (255, 255, 0)   HUD 文字    -> 【黄色】
  区别只在 G 通道: 橙 G=160, 黄 G=255。

同时把距离标签(画在人框左上角, 形如 "#2 P88 3.5m")裁出来放大, 供人眼复核。
"""
import glob
import os
import sys

import cv2
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "testimgs", "caps")
OUT = os.path.join(os.path.dirname(D), "caps_labels")
FOCAL = 408.9

if not os.path.isdir(OUT):
    os.makedirs(OUT)

files = sorted(glob.glob(os.path.join(D, "cap_*.jpg")))
print("FOCAL_PX=%.1f  (板上 PERSON_H_M=1.80)\n" % FOCAL)

print("%-14s %-38s %8s %10s %10s" % ("文件", "橙框 bbox(x,y,w,h)", "h_px", "报H=1.80", "报H=1.70"))
print("-" * 86)

rows = []
for f in files:
    img = cv2.imread(f)
    if img is None:
        continue
    b = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    r = img[:, :, 2].astype(int)

    # 橙色: R 高, G 中等(约160), B 低。用 G<205 把黄(G=255)排掉
    orange = ((r > 180) & (g > 90) & (g < 205) & (b < 110)).astype(np.uint8) * 255
    # 黄框/黄字
    yellow = ((r > 180) & (g >= 205) & (b < 110)).astype(np.uint8) * 255

    n_org = int((orange > 0).sum())
    n_yel = int((yellow > 0).sum())

    comps = []
    if n_org > 100:
        nn, lab, stats, cent = cv2.connectedComponentsWithStats(orange, 8)
        for i in range(1, nn):
            x, y, w, h, area = stats[i]
            if area < 40:
                continue
            comps.append((x, y, w, h, area))
    comps.sort(key=lambda t: -(t[2] * t[3]))     # 外接矩形面积大的排前面

    if not comps:
        print("%-14s %-38s %8s %10s %10s"
              % (os.path.basename(f), "(无橙框, 黄像素%d)" % n_yel, "-", "-", "-"))
        continue

    x, y, w, h, area = comps[0]
    d18 = FOCAL * 1.80 / h
    d17 = FOCAL * 1.70 / h
    print("%-14s x=%3d y=%3d w=%3d h=%3d  area=%5d %6d %9.2fm %9.2fm"
          % (os.path.basename(f), x, y, w, h, area, h, d18, d17))
    rows.append((os.path.basename(f), x, y, w, h, img))

# 把标签区裁出来放大, 人眼读距离文字
print("\n>>> 标签区放大图(人框左上角那块)写到 %s" % OUT)
for name, x, y, w, h, img in rows:
    y0 = max(0, y - 20)
    y1 = min(img.shape[0], y + 16)
    x0 = max(0, x - 6)
    x1 = min(img.shape[1], x + 130)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        continue
    big = cv2.resize(crop, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    p = os.path.join(OUT, "label_%s" % name)
    cv2.imwrite(p, big)
    print("   %s  (裁 %d,%d-%d,%d -> %dx%d)" % (p, x0, y0, x1, y1, big.shape[1], big.shape[0]))

# 拼一张总览
if rows:
    tiles = []
    for name, x, y, w, h, img in rows:
        y0 = max(0, y - 20)
        y1 = min(img.shape[0], y + 6)
        x0 = max(0, x - 6)
        x1 = min(img.shape[1], x + 130)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        tiles.append(cv2.resize(crop, None, fx=6, fy=6,
                                interpolation=cv2.INTER_NEAREST))
    if tiles:
        W = max(t.shape[1] for t in tiles)
        canvas = np.zeros((sum(t.shape[0] for t in tiles), W, 3), np.uint8)
        yy = 0
        for t in tiles:
            canvas[yy:yy + t.shape[0], :t.shape[1]] = t
            yy += t.shape[0]
        p = os.path.join(OUT, "_all_labels.png")
        cv2.imwrite(p, canvas)
        print(">>> 汇总图: %s (%dx%d)" % (p, canvas.shape[1], canvas.shape[0]))
