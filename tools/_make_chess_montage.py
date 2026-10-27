# -*- coding: utf-8 -*-
"""把检出的棋盘角点画回原图, 拼成一张核对图(标定"吃了什么数据"的直观证据)。

输出: testimgs/chess_corners_montage.png
  · 绿点 + 绿线 = 成功检出的 9x6 内角点
  · 红底 MISS   = 没检出, 没参与标定
每格左上角标文件名, 右上角标该格的角点平均间距(px), 便于一眼看出棋盘多大。
"""
import glob
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
D = os.path.join(ROOT, "testimgs", "chess_imgs")
OUT = os.path.join(ROOT, "testimgs", "chess_corners_montage.png")
PAT = (9, 6)
FLAGS_FIND = (cv2.CALIB_CB_ADAPTIVE_THRESH
              | cv2.CALIB_CB_NORMALIZE_IMAGE
              | cv2.CALIB_CB_FAST_CHECK)
CRIT = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

files = sorted(glob.glob(os.path.join(D, "chess_*.jpg")))
print("共 %d 张" % len(files))

tiles = []
n_ok = n_miss = 0
for f in files:
    img = cv2.imread(f)
    name = os.path.basename(f)
    if img is None:
        print("  [?? ] %s" % name)
        continue
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok, c = cv2.findChessboardCorners(gray, PAT, FLAGS_FIND)
    vis = img.copy()
    if ok:
        c = cv2.cornerSubPix(gray, c, (5, 5), (-1, -1), CRIT)
        cv2.drawChessboardCorners(vis, PAT, c, ok)
        # 角点平均间距(横向第一行的相邻间距)
        p = c.reshape(-1, 2)
        step = np.linalg.norm(p[1] - p[0])
        tag = "OK  %.1fpx" % step
        col = (0, 200, 0)
        n_ok += 1
        print("  [OK ] %s  角点间距 %.1f px" % (name, step))
    else:
        tag = "MISS (未参与标定)"
        col = (0, 0, 220)
        n_miss += 1
        print("  [MISS] %s" % name)

    # 画一条半透明色带放文字, 保证在任何背景上都看得清
    band = vis.copy()
    cv2.rectangle(band, (0, 0), (vis.shape[1], 16), (0, 0, 0), -1)
    vis = cv2.addWeighted(band, 0.45, vis, 0.55, 0)
    cv2.putText(vis, name, (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                (255, 255, 255), 1, cv2.LINE_AA)
    (tw, _), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)
    cv2.putText(vis, tag, (vis.shape[1] - tw - 3, 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, col, 1, cv2.LINE_AA)
    tiles.append(vis)

if not tiles:
    sys.exit("没有可拼的图")

h, w = tiles[0].shape[:2]
cols = 5
rows = (len(tiles) + cols - 1) // cols
canvas = np.full((rows * h, cols * w, 3), 28, np.uint8)
for i, t in enumerate(tiles):
    r, cc = divmod(i, cols)
    canvas[r * h:(r + 1) * h, cc * w:(cc + 1) * w] = t

# 底部加一行统计
stat = ("K210 chessboard calibration input - %d images, %d OK / %d MISS   "
        "(green = 9x6 inner corners detected)" % (len(tiles), n_ok, n_miss))
cv2.rectangle(canvas, (0, canvas.shape[0] - 22),
              (canvas.shape[1], canvas.shape[0]), (0, 0, 0), -1)
cv2.putText(canvas, stat, (6, canvas.shape[0] - 7),
            cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 230, 0), 1, cv2.LINE_AA)

cv2.imwrite(OUT, canvas)
print("\n已写出 %s  (%dx%d, %d OK / %d MISS)"
      % (OUT, canvas.shape[1], canvas.shape[0], n_ok, n_miss))
