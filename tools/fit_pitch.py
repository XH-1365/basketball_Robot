# -*- coding: utf-8 -*-
"""
地面法标定: 反算相机俯角 CAM_PITCH_DEG（或相机高度 CAM_H_M）。

为什么需要它:
  地面法 D = CAM_H_M / tan(俯角 + atan((y脚 - cy)/f))。
  其中 CAM_H_M 拿卷尺一量就有, 但**俯角没法量准** —— 目测差 3 度,
  2 米处的距离就能差几十厘米。所以必须反算。

数据从哪来:
  让板子跑起来, 人站在【卷尺量准】的距离上正面站直, 读串口那行 DET:
      DET n=1 total=1 | #1 x181,y0,w117,h147,0.75,R,d3.2H
                                        ^^ y=框顶行, h=框高
  脚尖行 = y + h。上例 = 0 + 147 = 147。

用法一（推荐，相机高度用卷尺量好，反算俯角）:
  python tools/fit_pitch.py 1.20 "D=2.0,y=210" "D=3.0,y=190" "D=4.0,y=180"

用法二（相机水平安装、俯角确认为 0，反算相机高度）:
  python tools/fit_pitch.py --solve-hc "D=2.0,y=210" "D=3.0,y=190"

可选: --f=277.0 --cy=120   （焦距 / 主点行, 默认就是这两个）
"""
import math
import sys


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return None
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def parse(s):
    kv = dict(p.split("=") for p in s.split(","))
    return float(kv["D"]), float(kv["y"])


def main():
    args = sys.argv[1:]
    f = 277.0
    cy = 120.0
    solve_hc = False
    rest = []
    for a in args:
        if a == "--solve-hc":
            solve_hc = True
        elif a.startswith("--f="):
            f = float(a[4:])
        elif a.startswith("--cy="):
            cy = float(a[5:])
        else:
            rest.append(a)

    if solve_hc:
        if len(rest) < 2:
            print(__doc__)
            return 1
        pts = [parse(s) for s in rest]
    else:
        if len(rest) < 3:
            print(__doc__)
            return 1
        hc = float(rest[0])
        pts = [parse(s) for s in rest[1:]]

    print("参数: FOCAL_PX=%.1f  CAM_CY=%.1f" % (f, cy))

    if solve_hc:
        # 假设俯角为 0: tan(beta) = (y-cy)/f, 且 D = hc / tan(beta) -> hc = D * tan(beta)
        ests = []
        print("\n各测点给出的 相机高度:")
        for D, y in pts:
            beta = math.atan((y - cy) / f)
            hc_i = D * math.tan(beta)
            ests.append(hc_i)
            print("  D=%.2fm y脚=%3.0f -> beta=%.2f度 -> hc=%.3f m"
                  % (D, y, math.degrees(beta), hc_i))
        hc = median(ests)
        lo, hi = min(ests), max(ests)
        print("\n>>> CAM_H_M = %.3f m   (离散 %.3f~%.3f, 极差 %.1f%%)"
              % (hc, lo, hi, (hi - lo) / hc * 100))
        print(">>> 把这行填进 body_detect.py:  CAM_H_M = %.2f" % hc)
        print(">>> 注意: 这是在【假设俯角=0】的前提下反算的。"
              "如果你的相机其实是朝下装的, 这个值会偏大, 请改用正常模式先算俯角。")
        return 0

    # 正常模式: 已知 hc, 逐点反算俯角 phi
    #   alpha = atan(hc / D)          (总俯角, 由几何决定)
    #   beta  = atan((y - cy)/f)      (像素行相对光轴的角度)
    #   phi   = alpha - beta
    phis = []
    print("\n各测点给出的 俯角:")
    for D, y in pts:
        alpha = math.atan(hc / D)
        beta = math.atan((y - cy) / f)
        phi = alpha - beta
        phis.append(phi)
        print("  D=%.2fm y脚=%3.0f -> 总俯角 %.2f度 - 像素角 %.2f度 = 俯角 %.2f度"
              % (D, y, math.degrees(alpha), math.degrees(beta), math.degrees(phi)))
    phi = median(phis)
    lo, hi = min(phis), max(phis)
    spread = (hi - lo)
    print("\n>>> CAM_PITCH_DEG = %.2f 度   (各点离散 %.2f 度)"
          % (math.degrees(phi), math.degrees(spread)))
    print(">>> 把这行填进 body_detect.py:  CAM_PITCH_DEG = %.1f" % math.degrees(phi))

    # 校核
    print("\n校核(用算出的俯角反推距离):")
    errs = []
    for D, y in pts:
        a = phi + math.atan((y - cy) / f)
        d_show = hc / math.tan(a) if a > 0.001 else float("inf")
        e = (d_show - D) / D * 100.0
        errs.append(abs(e))
        print("  真实 %.2fm -> 算出 %.2fm  偏差 %+.1f%%" % (D, d_show, e))
    mae = sum(errs) / len(errs)
    print(">>> 平均绝对偏差 %.1f%%" % mae)
    if math.degrees(spread) > 3:
        print(">>> 警告: 各点算出的俯角差超过 3 度。检查——"
              "① 相机高度量错 ② 脚没真的踩在被量距离的那个点上(人站远了/近了) "
              "③ 地面不平 ④ 框底不是脚(被家具挡住/被画面底边切掉)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
