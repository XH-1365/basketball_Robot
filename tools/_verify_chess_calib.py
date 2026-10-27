# -*- coding: utf-8 -*-
"""验证棋盘格标定结果可信度(离线)。

三个问题, 三个实验:
  Q1 焦距稳不稳?      -> 自助抽样(bootstrap): 随机抽 16 张反复标定, 看 fx/fy 的离散度
  Q2 畸变系数吓人,     -> 纯针孔模型(把所有畸变项固定为 0)再标一次, 比 fx
     会不会把 fx 带偏?     两套模型 fx 差多少, 就是"body_detect 忽略畸变"的代价
  Q3 畸变到底多大?     -> 把标定出来的 k1/k2/k3 画成径向倍率曲线, 看整流形范围内偏离 1 多少
  (附带) 棋盘角点覆盖到画面多外圈? -> 决定畸变有没有被真正约束住
"""
import glob
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(os.path.dirname(HERE), "testimgs", "chess_imgs")
PAT = (9, 6)                       # 内角点数 (列, 行)
CRIT = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
FLAGS_FIND = (cv2.CALIB_CB_ADAPTIVE_THRESH
              | cv2.CALIB_CB_NORMALIZE_IMAGE
              | cv2.CALIB_CB_FAST_CHECK)

d = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
files = sorted(glob.glob(os.path.join(d, "chess_*.jpg")))
print("目录: %s" % d)
print("找到 %d 张图" % len(files))

objp = np.zeros((PAT[0] * PAT[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:PAT[0], 0:PAT[1]].T.reshape(-1, 2)

objpoints, imgpoints, kept, size = [], [], [], None
for f in files:
    img = cv2.imread(f)
    if img is None:
        print("  [?? ] %s 读不了" % os.path.basename(f))
        continue
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    size = (gray.shape[1], gray.shape[0])
    ok, corners = cv2.findChessboardCorners(gray, PAT, FLAGS_FIND)
    if not ok:
        print("  [MISS] %s" % os.path.basename(f))
        continue
    corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRIT)
    objpoints.append(objp)
    imgpoints.append(corners)
    kept.append((os.path.basename(f), corners.reshape(-1, 2)))
    print("  [OK ] %s" % os.path.basename(f))

n = len(objpoints)
print("\n有效图 %d / %d" % (n, len(files)))
if n < 8:
    sys.exit("有效图太少, 没法验证")

W, H = size
print("画面尺寸 %dx%d" % (W, H))


def calib(idx, fix_distortion=False):
    """在指定的图片子集上标定。fix_distortion=True 就是纯针孔(不需要畸变)。"""
    op = [objpoints[i] for i in idx]
    ip = [imgpoints[i] for i in idx]
    flags = 0
    if fix_distortion:
        flags = (cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1
                 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3
                 | cv2.CALIB_FIX_K4 | cv2.CALIB_FIX_K5
                 | cv2.CALIB_FIX_K6)
    rms, K, dist, _, _ = cv2.calibrateCamera(op, ip, size, None, None, flags=flags)
    return rms, K, dist.ravel()


# ---------------- Q1: bootstrap 稳定性 ----------------
print("\n" + "=" * 62)
print("Q1 焦距稳不稳? 随机抽 16 张标定, 重复 40 次")
print("=" * 62)
rng = np.random.RandomState(20261010)
fxs, fys, cxs, cys, rmses = [], [], [], [], []
m = 16
for _ in range(40):
    idx = rng.choice(n, m, replace=False)
    try:
        rms, K, _ = calib(idx)
    except cv2.error:
        continue
    fxs.append(K[0, 0]); fys.append(K[1, 1])
    cxs.append(K[0, 2]); cys.append(K[1, 2])
    rmses.append(rms)

def stat(name, a):
    a = np.array(a)
    print("  %-4s 均值 %7.2f  标准差 %6.3f  极差 %7.2f  相对极差 %5.2f%%"
          % (name, a.mean(), a.std(ddof=1), a.max() - a.min(),
             (a.max() - a.min()) / a.mean() * 100.0))

stat("fx", fxs); stat("fy", fys); stat("cx", cxs); stat("cy", cys)
print("  RMS  均值 %.4f px  最差 %.4f px" % (np.mean(rmses), np.max(rmses)))
print("  -> fx 相对极差 %.2f%% ; fy 相对极差 %.2f%%"
      % ((max(fxs) - min(fxs)) / np.mean(fxs) * 100.0,
         (max(fys) - min(fys)) / np.mean(fys) * 100.0))

# ---------------- Q2: 纯针孔 vs 全畸变模型 ----------------
print("\n" + "=" * 62)
print("Q2 忽略畸变(纯针孔)会不会把焦距带偏?")
print("=" * 62)
allidx = list(range(n))
rms_full, Kf, dfull = calib(allidx)
rms_pin, Kp, dpin = calib(allidx, fix_distortion=True)
print("  全模型(5畸变项): fx=%7.2f fy=%7.2f cx=%7.2f cy=%7.2f  RMS=%.4f"
      % (Kf[0, 0], Kf[1, 1], Kf[0, 2], Kf[1, 2], rms_full))
print("  纯针孔(无可调畸变): fx=%7.2f fy=%7.2f cx=%7.2f cy=%7.2f  RMS=%.4f"
      % (Kp[0, 0], Kp[1, 1], Kp[0, 2], Kp[1, 2], rms_pin))
r = Kf[1, 1] / Kp[1, 1]
print("\n  fy 之比 = %.4f  -> 用纯针孔值当焦距, 距离会偏 %.2f%%" % (r, (r - 1) * 100))
print("  RMS 之比 = %.3f  (纯针孔 RMS 只大这么多 -> 畸变本来就很小)"
      % (rms_pin / rms_full))

# ---------------- Q3: 畸变到底多大 + 覆盖范围 ----------------
print("\n" + "=" * 62)
print("Q3 这套镜头的畸变到底有多大?")
print("=" * 62)
k1, k2, p1, p2, k3 = dfull[:5]
print("  k1=%.5f k2=%.5f k3=%.5f  p1=%.5f p2=%.5f" % (k1, k2, k3, p1, p2))
print("  (k2/k3 数值大不代表畸变大 —— 它们会和 k1 互相抵消, 真正有意义的是合成曲线)")
print("")
print("  距画面中心半径 r 处的径向放缩倍率(1.000=无畸变):")
xc, yc = Kf[0, 2], Kf[1, 2]
maxr = np.hypot(max(xc, W - xc), max(yc, H - yc))
for rr in [0, 40, 80, 120, 160, 200, int(maxr)]:
    if rr > maxr + 1:
        continue
    x = rr / Kf[0, 0]                       # 归一化
    x2 = x * x
    f = 1 + k1 * x2 + k2 * x2 ** 2 + k3 * x2 ** 3
    # 该半径处的像素位移(约等于)
    shift = (f - 1) * rr
    print("    r=%-4d px (%2.0f%% 画面半对角)  倍率 %.5f   位移 %+6.2f px"
          % (rr, rr / maxr * 100, f, shift))
dev = []
for rr in np.linspace(0, maxr, 200):
    x = rr / Kf[0, 0]
    x2 = x * x
    dev.append(abs((1 + k1 * x2 + k2 * x2 ** 2 + k3 * x2 ** 3) - 1) * rr)
print("\n  全画面最大径向位移 %.2f px (占画面宽 %.2f%%)" % (max(dev), max(dev) / W * 100))

print("\n  棋盘角点覆盖范围(归一化到画面半宽/半高):")
allc = np.vstack([c for _, c in kept])
print("    x: %.3f ~ %.3f   (1.0 = 画面左/右边)" % (allc[:, 0].min() / W, allc[:, 0].max() / W))
print("    y: %.3f ~ %.3f   (1.0 = 画面下边)" % (allc[:, 1].min() / H, allc[:, 1].max() / H))
rr = np.hypot(allc[:, 0] - xc, allc[:, 1] - yc) / maxr
print("    距中心半径: %.1f%% ~ %.1f%% 的画面半对角" % (rr.min() * 100, rr.max() * 100))
