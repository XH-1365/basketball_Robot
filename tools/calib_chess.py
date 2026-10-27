# -*- coding: utf-8 -*-
"""
棋盘格相机标定（PC 端, OpenCV）

输入: 一堆棋盘格照片(由 tools/shot_chess.py 在板上拍, 存 /sd/chess_NN.jpg)
输出: fx / fy / cx / cy / 畸变系数, 以及可直接贴进 body_detect.py 的两行

用法:
  python tools/calib_chess.py <图片目录> [--size=WxH] [--square=毫米]
  python tools/calib_chess.py D:/chess_imgs
  python tools/calib_chess.py D:/chess_imgs --size=7x5

要点:
  1. 【不用量格子边长】. calibrateCamera 的内参(fx/fy/cx/cy)和物点尺度无关,
     格子物理边长只影响外参(位姿)的平移单位. 所以 --square 只是可选的报告项.
  2. 照片分辨率必须和实际检测分辨率一致 —— 本项目统一 QVGA 320x240,
     板端 shot_chess.py 已经固定 QVGA, 所以直接算出来的 fx 就是 FOCAL_PX.
  3. 内角点数 = 每行/列的【格子数 - 1】. 比如棋盘 8x6 个格子就是 7x5 个内角点.
     不确定就用默认的自动猜测.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

# 自动猜的内角点候选(列, 行)。棋盘格常见规格都在这了。
CANDIDATES = [
    (7, 5), (8, 6), (9, 6), (6, 4), (7, 4), (9, 7), (10, 7),
    (6, 5), (8, 5), (5, 4), (10, 8), (11, 8), (9, 5), (10, 6),
    (4, 3), (5, 3), (6, 3), (7, 3), (8, 4), (9, 4), (12, 9),
]

FIND_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
              cv2.CALIB_CB_NORMALIZE_IMAGE |
              cv2.CALIB_CB_FAST_CHECK)


def load_images(folder):
    pats = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
        pats += glob.glob(os.path.join(folder, ext))
        pats += glob.glob(os.path.join(folder, ext.upper()))
    return sorted(set(pats))


def try_pattern(img_gray, size):
    """在一帧里找指定内角点数的棋盘格. 成功返回亚像素角点, 失败 None."""
    ok, corners = cv2.findChessboardCorners(img_gray, size, FIND_FLAGS)
    if not ok:
        return None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-3)
    return cv2.cornerSubPix(img_gray, corners, (5, 5), (-1, -1), crit)


def guess_pattern(imgs_gray, forced=None):
    """扫描候选规格, 选【命中图数最多】的那个. 平手选先出现的."""
    if forced is not None:
        return forced, [try_pattern(g, forced) for g in imgs_gray]
    best = None
    for size in CANDIDATES:
        hits = [try_pattern(g, size) for g in imgs_gray]
        n = sum(1 for h in hits if h is not None)
        if n == 0:
            continue
        if best is None or n > best[0]:
            best = (n, size, hits)
        if n == len(imgs_gray):
            break           # 全中, 没必要再试
    if best is None:
        return None, []
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="图片目录")
    ap.add_argument("--size", default=None,
                    help="强制指定内角点数, 如 7x5 (默认自动猜)")
    ap.add_argument("--square", type=float, default=None,
                    help="格子物理边长 mm (可选, 只影响报告不影响内参)")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        print("!! 目录不存在: %s" % args.folder)
        return 1

    paths = load_images(args.folder)
    if not paths:
        print("!! 目录里没有图片: %s" % args.folder)
        return 1
    print("找到 %d 张图片" % len(paths))

    forced = None
    if args.size:
        w, h = args.size.lower().split("x")
        forced = (int(w), int(h))

    # 读了第一张确定尺寸, 顺便做统一性检查
    first = cv2.imread(paths[0])
    if first is None:
        print("!! 第一张读不出来: %s" % paths[0])
        return 1
    imsize = (first.shape[1], first.shape[0])
    print("图片尺寸: %dx%d" % imsize)
    if imsize != (320, 240):
        print("!! 注意: 不是 QVGA 320x240. body_detect.py 的 FOCAL_PX 是按")
        print("   320x240 用的, 不同分辨率下 fx 不能直接抄, 需要按比例换算.")

    grays = []
    keep = []
    for p in paths:
        im = cv2.imread(p)
        if im is None:
            print("  跳过(读不出): %s" % os.path.basename(p))
            continue
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        grays.append(g)
        keep.append(p)

    size, hits = guess_pattern(grays, forced)
    if size is None:
        print("!! 所有候选规格都找不到棋盘格.")
        print("   检查: 1) 光线是不是太暗  2) 棋盘格有没有整个在画面里")
        print("         3) 是不是标准方格棋盘(黑白交替, 角点数=格数-1)")
        return 1

    print("棋盘格内角点: %dx%d" % size)
    good = [(p, c) for p, c in zip(keep, hits) if c is not None]
    for p, c in zip(keep, hits):
        mark = "OK " if c is not None else "MISS"
        print("  [%s] %s" % (mark, os.path.basename(p)))
    if len(good) < 8:
        print("!! 有效图只有 %d 张(<8), 标定不稳定, 再多拍几张" % len(good))
        return 1
    print("有效图 %d / %d" % (len(good), len(keep)))

    # 物点: 内参和物点尺度无关, 用 1.0 就行
    objp = np.zeros((size[0] * size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:size[0], 0:size[1]].T.reshape(-1, 2)
    if args.square:
        objp *= args.square

    objpoints = [objp] * len(good)
    imgpoints = [c for _, c in good]

    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, imsize, None, None)

    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    k1, k2, p1, p2, k3 = dist.ravel()[:5]

    print("")
    print("=" * 60)
    print(" RMS 重投影误差 : %.4f px   (<0.5 很好, <1.0 可用, >1.5 重拍)" % rms)
    print(" fx = %.2f   fy = %.2f   (fx/fy = %.4f, 方形像素应接近 1)"
          % (fx, fy, fx / fy))
    print(" cx = %.2f   cy = %.2f   (画面中心是 %.1f, %.1f)"
          % (cx, cy, imsize[0] / 2.0, imsize[1] / 2.0))
    print(" 畸变 k1=%.5f k2=%.5f p1=%.5f p2=%.5f k3=%.5f"
          % (k1, k2, p1, p2, k3))
    print("=" * 60)
    if abs(fx / fy - 1.0) > 0.03:
        print(" !! fx 和 fy 差超过 3%%, 通常说明拍的角度太单一/图太少, 建议补拍")
    if rms > 1.5:
        print(" !! RMS 偏大, 建议补拍: 更多角度 / 更好的光 / 棋盘格别出画")

    print("")
    print(">>> 贴进 body_detect.py:")
    print("    FOCAL_PX    = %.1f     # = fy. HEIGHT 法量的是框【高】(纵向),"
          " 纵向投影对应 fy" % fy)
    print("                    # 棋盘格标定, RMS %.3f px, %d 张图, fx=%.1f"
          % (rms, len(good), fx))
    print("    CAM_CY      = %d       # 主点行(原假设 %d)"
          % (int(round(cy)), imsize[1] // 2))
    print("")
    print(">>> 说明: 用 fy 不用 fx 的理由 —— 人体框高 h_px 是【纵向】像素,")
    print("    纵向投影 h_px = fy * H / D, 所以 D = fy * H / h_px。")
    print("    方形像素下 fx≈fy 差别很小(这里差 %.2f%%), 但用错就是系统性偏差。"
          % (abs(fx - fy) / fy * 100))
    print("")
    print(">>> cx 一般就在画面中线附近, HEIGHT 法用不到它;")
    print("    但 GROUND 法(地脚测距)用的是 CAM_CY, 这个值现在有实测依据了.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
