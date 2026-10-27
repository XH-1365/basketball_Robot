# -*- coding: utf-8 -*-
"""留一交叉验证(LOO-CV): 哪种畸变模型最能预测【没见过的】一张图的真实像素?

动机: 全模型 fy=408.95, 纯针孔 fy=385.86, 差 5.98%。但畸变造成的实际像素位移
     最多才 3.57 px —— 6% 的焦距差(约 19 px)不可能是真实畸变, 只能是 k2/k3 和
     fx/cx/cy 之间的过拟合抵消。棋盘格从没进过画面四角, 参数分不开。

判据: 用 N-1 张标定 -> 用 solvePnP 求第 N 张的姿态 -> projectPoints 预测角点
      -> 与实际检出的角点比。谁的平均误差小, 谁的焦距就更可信。
      这是"泛化能力", 不是"拟合能力"(拟合能力大家 RMS 都差不多)。

每一折里的焦距也是独立标出来的, 所以顺带看 fx 的折间离散度。
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

ZERO_TAN = cv2.CALIB_ZERO_TANGENT_DIST

MODELS = [
    ("全模型 (k1,k2,k3,p1,p2)", 0),
    ("只有 k1", ZERO_TAN | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3
     | cv2.CALIB_FIX_K4 | cv2.CALIB_FIX_K5 | cv2.CALIB_FIX_K6),
    ("k1,k2", ZERO_TAN | cv2.CALIB_FIX_K3 | cv2.CALIB_FIX_K4
     | cv2.CALIB_FIX_K5 | cv2.CALIB_FIX_K6),
    ("纯针孔 (无畸变)", ZERO_TAN | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2
     | cv2.CALIB_FIX_K3 | cv2.CALIB_FIX_K4 | cv2.CALIB_FIX_K5
     | cv2.CALIB_FIX_K6),
]

d = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
files = sorted(glob.glob(os.path.join(d, "chess_*.jpg")))

objp = np.zeros((PAT[0] * PAT[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:PAT[0], 0:PAT[1]].T.reshape(-1, 2)

objpoints, imgpoints, names, size = [], [], [], None
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
    names.append(os.path.basename(f))

n = len(objpoints)
print("有效图 %d 张, 画面 %dx%d" % (n, size[0], size[1]))
if n < 8:
    sys.exit("有效图太少")

allidx = list(range(n))

print("\n" + "=" * 74)
print("%-24s %10s %10s %8s %9s %9s" % ("模型", "LOO误差/px", "折间fx极差", "fx", "fy", "RMS"))
print("=" * 74)

summary = []
for name, flags in MODELS:
    # 全量标定(报告用)
    rms_all, K_all, dist_all, _, _ = cv2.calibrateCamera(
        objpoints, imgpoints, size, None, None, flags=flags)

    loo_err = []
    fxs, fys = [], []
    for j in allidx:
        tr = [i for i in allidx if i != j]
        try:
            _, K, dist, _, _ = cv2.calibrateCamera(
                [objpoints[i] for i in tr], [imgpoints[i] for i in tr],
                size, None, None, flags=flags)
            ok, rvec, tvec = cv2.solvePnP(objpoints[j], imgpoints[j], K, dist)
            if not ok:
                continue
            proj, _ = cv2.projectPoints(objpoints[j], rvec, tvec, K, dist)
            e = np.linalg.norm(proj.reshape(-1, 2) - imgpoints[j].reshape(-1, 2),
                               axis=1)
            loo_err.append(e.mean())
            fxs.append(K[0, 0]); fys.append(K[1, 1])
        except cv2.error:
            continue

    loo = float(np.mean(loo_err)) if loo_err else float("nan")
    spread = (max(fxs) - min(fxs)) if fxs else float("nan")
    print("%-24s %10.4f %10.2f %8.2f %9.2f %9.4f"
          % (name, loo, spread, K_all[0, 0], K_all[1, 1], rms_all))
    summary.append((name, loo, np.mean(fxs), np.mean(fys), K_all))

print("=" * 74)
print("LOO误差 = 平均每张【没参与标定】的图, 预测角点与真实角点的平均距离(px)")
print("折间fx极差 = 20 折各自标出的 fx 的极差, 越小说明焦距越定得死")

best = min(summary, key=lambda s: s[1])
print("\n>>> 泛化最好(LOO误差最小): %s" % best[0])
print("    LOO 误差 %.4f px ; 该模型的 fy = %.2f" % (best[1], best[4][1, 1]))
print("")
print(">>> 建议 body_detect.py 用的 FOCAL_PX (= fy): %.1f" % best[4][1, 1])
print("    理由: body_detect 是【纯针孔】公式 D = f*H/h_px, 不做去畸变,")
print("          所以应该用【纯针孔口径】的焦距, 而不是全模型的焦距。")
print("")
print(">>> 各模型的 fy 一览:")
for name, loo, mfx, mfy, K in summary:
    print("    %-24s fy=%7.2f   LOO=%.4f px" % (name, K[1, 1], loo))
