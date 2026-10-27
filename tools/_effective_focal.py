# -*- coding: utf-8 -*-
"""按【body_detect 的真实测量几何】反算有效焦距。

争论点: 全模型 fy=408.95 vs 纯针孔 fy=385.86, 差 6%。四个模型 LOO 打平, 数据
       分不开。但 body_detect 的用法很具体 —— 人在画面中央, 框高 h_px 跨画面
       中部约 ±120 px, 公式是纯针孔 D = f*H/h_px。

所以不该问"哪个模型泛化好", 该问"在【中央那一条竖线】上, 哪个 f 能让纯针孔
公式等于真实投影"。做法:
  1. 拿全模型(K,dist)当作"物理真值"(它 RMS 最低, 且在 r=0 附近是精确的)
  2. 在相机坐标里摆一根竖直杆 [0, ±H/2, D], 用 projectPoints 投影 -> 真值 h_px
  3. 反解 f_eff = h_px * D / H
  4. 对整个距离范围积分, 看 f_eff 稳不稳、等于多少
  5. 再把人横向挪开(cx 方向上 ±40/80 px) 看 f_eff 会不会变
"""
import glob
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(os.path.dirname(HERE), "testimgs", "chess_imgs")
PAT = (9, 6)
CRIT = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
FLAGS_FIND = (cv2.CALIB_CB_ADAPTIVE_THRESH
              | cv2.CALIB_CB_NORMALIZE_IMAGE
              | cv2.CALIB_CB_FAST_CHECK)

d = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
files = sorted(glob.glob(os.path.join(d, "chess_*.jpg")))
objp = np.zeros((PAT[0] * PAT[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:PAT[0], 0:PAT[1]].T.reshape(-1, 2)

objpoints, imgpoints, size = [], [], None
for f in files:
    img = cv2.imread(f)
    if img is None:
        continue
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    size = (gray.shape[1], gray.shape[0])
    ok, c = cv2.findChessboardCorners(gray, PAT, FLAGS_FIND)
    if not ok:
        continue
    c = cv2.cornerSubPix(gray, c, (5, 5), (-1, -1), CRIT)
    objpoints.append(objp)
    imgpoints.append(c)

rms, K, dist, _, _ = cv2.calibrateCamera(objpoints, imgpoints, size, None, None)
Kp = K.copy()
dist_p = np.zeros(5)
rmsp, Kp, distp, _, _ = cv2.calibrateCamera(
    objpoints, imgpoints, size, None, None,
    flags=(cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2
           | cv2.CALIB_FIX_K3 | cv2.CALIB_FIX_K4 | cv2.CALIB_FIX_K5
           | cv2.CALIB_FIX_K6))

W, H_img = size
print("画面 %dx%d" % (W, H_img))
print("全模型 : fx=%.2f fy=%.2f cx=%.2f cy=%.2f  RMS=%.4f"
      % (K[0, 0], K[1, 1], K[0, 2], K[1, 2], rms))
print("纯针孔 : fx=%.2f fy=%.2f cx=%.2f cy=%.2f  RMS=%.4f"
      % (Kp[0, 0], Kp[1, 1], Kp[0, 2], Kp[1, 2], rmsp))

PERSON_H = 1.70
rvec0 = np.zeros(3, float)

print("")
print("=" * 78)
print("竖直杆 [x_off, ±H/2, D] 投影 -> 反解有效焦距 f_eff = h_px*D/H")
print("=" * 78)
print("%8s %10s %10s %12s %12s" % ("D(m)", "x_off(px)", "h_px", "f_eff(全模型)", "f_eff(针孔)"))

rows = []
for D in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]:
    for x_off_px in [0, 40, 80, 110]:
        # 相机坐标: x 右, y 上, z 前。图像 y 向下增大。
        # 像素 x_px = cx + fx * (x_cam/z)  =>  x_cam = (x_px-cx)*z/fx
        xc = (x_off_px - K[0, 2]) / K[0, 0] * D
        pts = np.array([[xc, PERSON_H / 2.0, D],
                        [xc, -PERSON_H / 2.0, D]], np.float32)
        proj, _ = cv2.projectPoints(pts, rvec0, np.zeros(3, float), K, dist)
        h_px = abs(proj[0][0][1] - proj[1][0][1])
        projp, _ = cv2.projectPoints(pts, rvec0, np.zeros(3, float), Kp, distp)
        h_pxp = abs(projp[0][0][1] - projp[1][0][1])
        fe = h_px * D / PERSON_H
        fep = h_pxp * D / PERSON_H
        rows.append((D, x_off_px, h_px, fe, fep))
        print("%8.1f %10d %10.1f %12.2f %12.2f" % (D, x_off_px, h_px, fe, fep))

print("")
a = np.array([r[3] for r in rows])
b = np.array([r[4] for r in rows])
print("全模型口径: f_eff 均值 %8.2f  极差 %6.2f (%.1f%%)"
      % (a.mean(), a.max() - a.min(), (a.max() - a.min()) / a.mean() * 100))
print("针孔口径  : f_eff 均值 %8.2f  极差 %6.2f (%.1f%%)"
      % (b.mean(), b.max() - b.min(), (b.max() - b.min()) / b.mean() * 100))

# 只用画面中央的(D>=2.0 且 x_off<=40) 最贴近真实使用
sel = [r for r in rows if r[1] <= 40]
c = np.array([r[3] for r in sel])
print("")
print(">>> 只取画面中央一列(x_off<=40px, 覆盖人的站位):")
print("    全模型口径 f_eff = %.1f (极差 %.2f)" % (c.mean(), c.max() - c.min()))
print("")
print(">>> body_detect 该填 FOCAL_PX = %.1f" % c.mean())
