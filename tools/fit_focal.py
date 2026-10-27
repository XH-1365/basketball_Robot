# -*- coding: utf-8 -*-
"""
标定求解器: 从 sample.py 的采样日志里反算 FOCAL_PX。

原理: 针孔模型  D = H * f / h   =>  h = (H*f) * (1/D)
      把各测试点 (真实距离 D_i, 框高中位数 h_i) 拿来做"过原点最小二乘",
      解出 f。用 h = k*(1/D) 的过原点拟合是因为误差主要出在 h（框高测量）上，
      而 D 是拿卷尺量出来的、几乎无误差。

用法:
  python tools/fit_focal.py log.txt 1.70 "0,10,1.0" "10,20,2.0" "20,30,3.0"
    log.txt  = sample.py 的完整输出(直接重定向保存)
    1.70     = 被标定者真实身高(米)
    "起s,止s,真实距离m"  可给任意多段，段之间不要重叠

AprilTag 模式(--tag): 优先使用 TAG 行里的 side(四边平均边长, 旋转不变),
没有 side 字段的老日志才退回用 h。详见 calib_tag.py 的注释。

也可以省掉日志文件，直接给"框高中位数"手算:
  python tools/fit_focal.py - 1.70 "h=191,D=2.0" "h=96,D=4.0"
"""
import re
import sys


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return None
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


LINE_RE = re.compile(r"\[\s*([0-9.]+)s\]\s*(.*)")
H_RE = re.compile(r"h(\d+)")
# calib_tag.py 新格式里带的“四边平均边长”。旧日志没有这个字段。
SIDE_RE = re.compile(r"side(\d+(?:\.\d+)?)")


def parse_log(path, want="DET"):
    """-> [(t, [尺寸, 尺寸, ...]), ...]。

    want="DET" 收人体框(用框高 h) / "TAG" 收 AprilTag 的框。
    TAG 模式**优先**用 side(四条边平均长度, 旋转不变); 老日志没有 side
    字段时才退回 h。原因见 calib_tag.py: w()/外接矩形会被倾斜撑大。
    注意字段名不能改, 正则按 side数字 / h数字 取。
    """
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = LINE_RE.search(ln)
            if not m:
                continue
            t = float(m.group(1))
            body = m.group(2)
            if not body.startswith(want):
                continue
            if want == "TAG":
                # "TAGEST" 行也是 TAG 开头, 但它没有 side 字段, 会被下面跳过
                ss = SIDE_RE.findall(body)
                if ss:
                    rows.append((t, [float(x) for x in ss]))
                    continue
            hs = [int(x) for x in H_RE.findall(body)]
            if hs:
                rows.append((t, [float(x) for x in hs]))
    return rows


def main():
    args = sys.argv[1:]
    want = "DET"
    if "--tag" in args:
        want = "TAG"
        args.remove("--tag")
    if len(args) < 3:
        print(__doc__)
        return 1
    src = args[0]
    H = float(args[1])
    segs = args[2:]

    points = []      # (D_true, h_med)
    if src == "-":
        for s in segs:
            kv = dict(p.split("=") for p in s.split(","))
            points.append((float(kv["D"]), float(kv["h"])))
    else:
        rows = parse_log(src, want)
        if not rows:
            if want == "TAG":
                print("日志里没找到任何 TAG 行。检查: "
                      "① tag 有没有进画面 ② 是不是 36h11 家族 "
                      "③ 光线够不够(已关自动增益) ④ tag 太小/太远")
            else:
                print("日志里没找到任何 DET 行(是不是人在画面里但没检到?)")
            return 1
        print("解析到 %d 行检测数据, 时间跨度 %.1fs~%.1fs"
              % (len(rows), rows[0][0], rows[-1][0]))
        for s in segs:
            a, b, d = s.split(",")
            a, b, d = float(a), float(b), float(d)
            hs = [h for t, hh in rows if a <= t < b for h in hh]
            if not hs:
                print("  段 [%.0f,%.0f)s 真实 %.2fm -> 无数据, 跳过" % (a, b, d))
                continue
            points.append((d, median(hs)))
            print("  段 [%.0f,%.0f)s 真实 %.2fm -> %d 个样本, h中位数 %.1f"
                  % (a, b, d, len(hs), median(hs)))

    if len(points) < 2:
        print("有效测点少于 2 个, 只能给出单点估计(仅供参考):")
        if points:
            d, h = points[0]
            print("  FOCAL_PX = %.1f * %.1f / %.1f = %.1f"
                  % (d, h, H, d * h / H))
            print("  建议至少再用 2 个不同距离交叉验证。")
        return 0

    # 过原点最小二乘: h = (H*f) * (1/D)
    sx2 = sum((1.0 / d) ** 2 for d, _ in points)
    sxy = sum((1.0 / d) * h for d, h in points)
    f = sxy / (H * sx2)

    print("\n各测点校核:")
    errs = []
    for d, h in points:
        d_show = H * f / h
        err = (d_show - d) / d * 100.0
        errs.append(abs(err))
        print("  真实 %.2fm  h=%4.1f  -> 算出 %.2fm  偏差 %+.1f%%"
              % (d, h, d_show, err))
    print("\n>>> FOCAL_PX = %.1f   (平均绝对偏差 %.1f%%)"
          % (f, sum(errs) / len(errs)))
    print(">>> 把这行贴进 body_detect.py 的 FOCAL_PX = %.1f" % f)
    if sum(errs) / len(errs) > 25:
        if want == "TAG":
            print(">>> 警告: 偏差偏大。检查——"
                  "① 尺子量的是不是【黑框外沿】(实测 w() 就是量外沿) "
                  "② 打印有没有被缩放 "
                  "③ tag 有没有正对镜头(斜了会被透视压扁) "
                  "④ 距离太远(QQVGA 下像素太少)")
        else:
            print(">>> 警告: 偏差偏大。多半是框高被测错——"
                  "确认人是全身完整在画面里(头顶和脚都没被裁)，且没走动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
