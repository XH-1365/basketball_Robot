# -*- coding: utf-8 -*-
"""
calib_chess.py 的离线自测（不需要板子、不需要真棋盘格）。

做法: 用一个已知内参的虚拟相机, 把棋盘格以多个位姿投影渲染成黑白图,
      存成 jpg, 然后调 calib_chess 的主流程, 看反算出来的 fx/fy/cx/cy
      是否贴近真值。

真值: fx = fy = 277.0, cx = 160, cy = 120  (QVGA 320x240, 和项目假设一致)
"""
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 320, 240
FX_TRUE = 277.0
FY_TRUE = 277.0
CX_TRUE = 160.0
CY_TRUE = 120.0
PATTERN = (7, 5)          # 内角点 7x5
SQ = 1.0


def render(rvec, tvec):
    """把棋盘格投影到虚拟相机里, 返回 BGR 图。棋盘格往外多扩一圈,
    让内角点正好落在 (0..cols-1, 0..rows-1)。"""
    img = np.full((H, W, 3), 255, np.uint8)
    cols, rows = PATTERN
    for i in range(-1, cols):
        for j in range(-1, rows):
            if (i + j) % 2 == 0:
                continue
            pts = np.array([[i * SQ, j * SQ, 0],
                            [(i + 1) * SQ, j * SQ, 0],
                            [(i + 1) * SQ, (j + 1) * SQ, 0],
                            [i * SQ, (j + 1) * SQ, 0]], np.float32)
            proj, _ = cv2.projectPoints(pts, rvec, tvec, 
                                        np.array([[FX_TRUE, 0, CX_TRUE],
                                                  [0, FY_TRUE, CY_TRUE],
                                                  [0, 0, 1.0]]), None)
            poly = proj.reshape(-1, 2).astype(np.int32)
            # fillPoly 会自动裁边, 不需要自己判断出画;
            # 出画的姿态由 findChessboardCorners 自己判 MISS, 那才是真实行为
            cv2.fillPoly(img, [poly], (0, 0, 0))
    return img


def build_poses():
    """一组姿态: 距离/俯仰/偏航都变, 模拟真实拍摄。
    距离按 fx=277 和棋盘物理尺寸(9x7 格)算过, 保证棋盘格整体在画面内:
      棋盘宽 9 单位 -> z=10 时约 249px < 320, z=16 时约 156px。"""
    poses = []
    for z in (10.0, 13.0, 16.0):
        for rx in (-0.20, 0.0, 0.20):
            for ry in (-0.25, 0.0, 0.25):
                poses.append((np.array([rx, ry, 0.05], np.float32),
                              np.array([-0.5, -0.5, z], np.float32)))
    return poses


def main():
    tmp = tempfile.mkdtemp(prefix="chesstest_")
    n_ok = 0
    try:
        for k, (rvec, tvec) in enumerate(build_poses()):
            img = render(rvec, tvec)
            p = os.path.join(tmp, "chess_%03d.jpg" % k)
            cv2.imwrite(p, img)
            n_ok += 1
        print("生成了 %d 张合成棋盘格图 -> %s" % (n_ok, tmp))

        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "calib_chess.py"), tmp],
            capture_output=True, text=True, encoding="utf-8")
        out = r.stdout + r.stderr
        print(out)

        assert r.returncode == 0, "calib_chess 退出码 %d" % r.returncode

        import re
        m = re.search(r"fx = ([\d.]+)\s+fy = ([\d.]+)\s+\(fx/fy = ([\d.]+)", out)
        assert m, "输出里没找到 fx/fy"
        fx, fy, ratio = float(m.group(1)), float(m.group(2)), float(m.group(3))
        m2 = re.search(r"cx = ([\d.]+)\s+cy = ([\d.]+)", out)
        cx, cy = float(m2.group(1)), float(m2.group(2))
        m3 = re.search(r"RMS \S* : ([\d.]+) px", out)
        rms = float(m3.group(1))

        print("=" * 60)
        print("真值  fx=%.1f fy=%.1f cx=%.1f cy=%.1f" %
              (FX_TRUE, FY_TRUE, CX_TRUE, CY_TRUE))
        print("反算  fx=%.1f fy=%.1f cx=%.1f cy=%.1f  RMS=%.3f" %
              (fx, fy, cx, cy, rms))
        err_fx = abs(fx - FX_TRUE) / FX_TRUE * 100
        err_fy = abs(fy - FY_TRUE) / FY_TRUE * 100
        err_cx = abs(cx - CX_TRUE) / CX_TRUE * 100
        err_cy = abs(cy - CY_TRUE) / CY_TRUE * 100
        print("偏差  fx %.2f%%  fy %.2f%%  cx %.2f%%  cy %.2f%%"
              % (err_fx, err_fy, err_cx, err_cy))
        assert err_fx < 2.0, "fx 偏差过大 %.2f%%" % err_fx
        assert err_fy < 2.0, "fy 偏差过大 %.2f%%" % err_fy
        assert err_cx < 5.0, "cx 偏差过大 %.2f%%" % err_cx
        assert err_cy < 5.0, "cy 偏差过大 %.2f%%" % err_cy
        assert rms < 1.0, "RMS 过大 %.3f" % rms
        assert abs(ratio - 1.0) < 0.02, "fx/fy 偏离 1 过多"
        print(">>> 通过: 合成真值能被整条链收回")
        print("=" * 60)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
