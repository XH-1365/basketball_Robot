# -*- coding: utf-8 -*-
"""v2: 用行/列投影把【贴在一起的两个黄框】分开。

v1 用连通域, 但人的框和告警区框挨着 -> 合并成一个, 量到的是告警区。
矩形无论怎么贴, 它的边总是"某一行/某一列上有大量黄像素"。
  · 水平边 -> 行投影的峰
  · 垂直边 -> 列投影的峰
两个矩形 = 4 条水平边 + 4 条垂直边, 从峰位就能还原出两个框。
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


def yellow_mask(img):
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    m = ((r > 150) & (g > 150) & (b < 110)).astype(np.uint8) * 255
    m[:30, :] = 0            # 顶部 HUD 文字
    return m


def peaks(profile, thresh, min_gap=4):
    """找一维投影里的峰(连续高于阈值的段取质心)。"""
    out = []
    i = 0
    n = len(profile)
    while i < n:
        if profile[i] >= thresh:
            j = i
            while j < n and profile[j] >= thresh:
                j += 1
            seg = profile[i:j]
            idx = np.arange(i, j)
            out.append(int(round(float((idx * seg).sum() / seg.sum()))))
            i = j
        else:
            i += 1
    # 合并太近的
    merged = []
    for p in out:
        if merged and p - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + p) // 2
        else:
            merged.append(p)
    return merged


files = sorted(glob.glob(os.path.join(D, "cap_*.jpg")))
print("FOCAL_PX=%.1f\n" % FOCAL)
for f in files:
    img = cv2.imread(f)
    if img is None:
        continue
    m = yellow_mask(img)
    if m.sum() < 5000:
        print("%s: 黄像素太少, 跳过(可能没画框)" % os.path.basename(f))
        continue
    rows = m.sum(axis=1)
    cols = m.sum(axis=0)
    # 一条水平边至少横跨 60px, 垂直边至少 60px 高
    hp = peaks(rows, 60)
    vp = peaks(cols, 60)
    print("%s  水平边 y=%s   垂直边 x=%s" % (os.path.basename(f), hp, vp))
    if len(hp) >= 2 and len(vp) >= 2:
        # 组合成候选矩形: 每两条水平边 x 每两条垂直边
        print("   候选矩形(h = 两水平边间距):")
        for i in range(len(hp)):
            for j in range(i + 1, len(hp)):
                h = hp[j] - hp[i]
                if h < 30:
                    continue
                d18 = FOCAL * 1.80 / h
                d17 = FOCAL * 1.70 / h
                print("     y=%d..%d  h=%3d  -> H=1.80 报 %.2f m | H=1.70 报 %.2f m"
                      % (hp[i], hp[j], h, d18, d17))
    print("")
