# -*- coding: utf-8 -*-
"""
ground_collect.py 的离线自测 —— 不需要板子、不需要真人。

做法: 按【已知的】相机高度和俯角, 正着算出每个距离上脚尖应该落在第几行,
      再把这些行伪装成串口日志, 看解析 + 分段聚合 + fit_pitch 能不能把
      俯角原样反算回来。

同时验证: SIMFT(自检假框) 不能被当成真实数据收走。
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import ground_collect as gc  # noqa: E402

HC = 1.20          # 真值: 相机高
PITCH = 25.0       # 真值: 俯角
F = 277.0
CY = 120.0

# 三个测点, 都落在 pitch=25 度时 "1.07m~43.6m" 的可测区间里
CASES = (
    (0.0, 18.0, 1.30),
    (18.0, 36.0, 1.60),
    (36.0, 54.0, 2.00),
)


def yf_for(D):
    """由真值正算脚尖行: yf = cy + f * tan(atan(hc/D) - pitch)"""
    alpha = math.atan(HC / D)
    beta = alpha - math.radians(PITCH)
    return int(round(CY + F * math.tan(beta)))


def build_log():
    lines = []
    # 先来两行 SIMFT, 验证它们不会被 regex 收走
    lines.append("[   1.0s] SIMFT yf=214 y= 14 h=200 w=110 cx=155 p=0.99")
    lines.append("[   1.0s] SIMGT dG=3.54m  dH=2.35m")
    for a, b, D in CASES:
        yf = yf_for(D)
        # 每段塞 12 帧, 让"离散度"是个真实的小数字(±1px)
        for k in range(12):
            jitter = (k % 3) - 1      # -1/0/+1
            t = a + (b - a) * k / 12.0
            lines.append("[%6.1fs] FEET yf=%3d y=%3d h=%3d w=%3d cx=%3d p=%.2f"
                         % (t, yf + jitter, yf + jitter - 190, 196, 110, 155, 0.85))
    return "\n".join(lines) + "\n"


def main():
    log = build_log()
    print("=" * 60)
    print("合成日志片段:")
    print("\n".join(log.splitlines()[:6]))
    print("...")
    print("=" * 60)

    rows = gc.parse_feet(log)
    print("\n解析出 FEET 行 %d 条 (期望 %d)" % (len(rows), 12 * len(CASES)))
    assert len(rows) == 12 * len(CASES), \
        "数量不对: SIMFT 被误收了? 或者 FEET 正则漏了"
    print("OK  SIMFT 未被误收")

    # 复刻 ground_collect 的分段聚合
    pts = []
    print("\n分段聚合:")
    for a, b, D in CASES:
        sel = [r for r in rows if a <= r[0] < b and 0 < r[1] < 238]
        yf = gc.median([r[1] for r in sel])
        pts.append((D, yf))
        print("  真实 %.2f m -> yf=%6.1f (n=%d, 期望 %d)"
              % (D, yf, len(sel), yf_for(D)))

    # 调 fit_pitch.py 反算
    print("\n交给 fit_pitch.py 反算 ...")
    args = [sys.executable, os.path.join(HERE, "fit_pitch.py"),
            "%.3f" % HC, "--f=%.1f" % F, "--cy=%.1f" % CY]
    args += ["D=%.2f,y=%.1f" % (d, y) for d, y in pts]
    p = subprocess.run(args, capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    print(out)

    import re
    m = re.search(r"CAM_PITCH_DEG\s*=\s*(-?[\d.]+)", out)
    assert m, "没解析到 CAM_PITCH_DEG"
    got = float(m.group(1))
    err = abs(got - PITCH)
    print("=" * 60)
    print("真值 %.2f 度  ->  反算 %.2f 度   偏差 %.2f 度" % (PITCH, got, err))
    if err <= 0.5:
        print(">>> 通过: 整条链路(解析->聚合->拟合)正确")
        return 0
    print(">>> 失败: 偏差过大")
    return 1


if __name__ == "__main__":
    sys.exit(main())
