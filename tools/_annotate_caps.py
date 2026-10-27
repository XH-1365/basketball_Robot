# -*- coding: utf-8 -*-
"""把量到的橙色人框画回照片上, 直观展示"头被切掉"这件事。"""
import glob
import os

import cv2
import numpy as np

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "testimgs", "caps")
OUT = os.path.join(os.path.dirname(D), "caps_annotated.png")
FOCAL = 408.9

files = sorted(glob.glob(os.path.join(D, "cap_*.jpg")))
tiles = []
for f in files[:6]:
    img = cv2.imread(f)
    if img is None:
        continue
    b = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    r = img[:, :, 2].astype(int)
    orange = ((r > 180) & (g > 90) & (g < 205) & (b < 110)).astype(np.uint8) * 255
    yellow = ((r > 180) & (g >= 205) & (b < 110)).astype(np.uint8) * 255

    vis = img.copy()
    # 黄色告警区标成蓝
    ys = np.where(yellow.sum(axis=1) > 60)[0]
    xs = np.where(yellow.sum(axis=0) > 60)[0]
    if len(ys) and len(xs):
        cv2.rectangle(vis, (int(xs.min()), int(ys.min())),
                      (int(xs.max()), int(ys.max())), (255, 120, 0), 1)
        cv2.putText(vis, "ZONE", (int(xs.min()) + 2, int(ys.min()) + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 120, 0), 1, cv2.LINE_AA)
    nn, lab, stats, cent = cv2.connectedComponentsWithStats(orange, 8)
    comps = [stats[i] for i in range(1, nn) if stats[i][4] >= 40]
    comps.sort(key=lambda t: -(t[2] * t[3]))
    if comps:
        x, y, w, h, a = comps[0]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        tag = "h=%d -> %.2fm" % (h, FOCAL * 1.80 / h)
        if y <= 1:
            tag += "  HEAD CUT!"
        cv2.putText(vis, tag, (3, 232), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    (0, 0, 255), 1, cv2.LINE_AA)
    else:
        cv2.putText(vis, "no person box", (3, 232), cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (0, 0, 255), 1, cv2.LINE_AA)
    tiles.append(vis)

if not tiles:
    raise SystemExit("没有图")

h, w = tiles[0].shape[:2]
cols = 3
rows = (len(tiles) + cols - 1) // cols
canvas = np.full((rows * h, cols * w, 3), 25, np.uint8)
for i, t in enumerate(tiles):
    rr, cc = divmod(i, cols)
    canvas[rr * h:(rr + 1) * h, cc * w:(cc + 1) * w] = t
cv2.imwrite(OUT, canvas)
print("写出 %s (%dx%d)" % (OUT, canvas.shape[1], canvas.shape[0]))
