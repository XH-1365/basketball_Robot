# -*- coding: utf-8 -*-
"""
AprilTag 标定 —— PC 端一键驱动。

做三件事:
  1. 按你给的分段计划生成板端会话脚本 tools/_calib_session.py
     （屏幕上会实时显示"请把 tag 摆到 X.XX m 处 + 倒计时"）
  2. 在板子上跑满指定秒数，把完整日志存到 testimgs/calib_<时间戳>.log
  3. 自动调用 fit_focal.py 反算 FOCAL_PX

用法（距离要摆近！实测见 --help 末尾说明）:
  python tools/calib_collect.py COM16 100 --w=0.100 "0,20,0.30" "20,40,0.40" \
                                          "40,60,0.50" "60,80,0.60" "80,100,0.70"
  # 少给几段也行, 但至少 3 段; 没检出的那档会被自动跳过

参数:
  COM16              串口
  60                 总时长(秒)，要 >= 最后一段的结束秒
  "起s,止s,真实距离m"  可给任意多段，段之间别重叠
  --w=0.100          tag 黑框外沿真实边长(米)，默认 0.100

打印并【按 100% 比例】打印 tag/tag36h11_id0_A4.svg，打完用尺子量黑框外沿核对。

【距离怎么定 —— 必须看】
  标定靠像素边长反算: side_px = FOCAL_PX * TAG_W_M / D。
  QQVGA(160x120) 下 find_apriltags 的检出能力【非单调】(实测 16/24px 能检,
  32px 反而检不到, 40px 以上稳定)。保守按"外沿 >= 40px"算, 100mm 的 tag
  最远只能摆到 277*0.100/40 = 0.69 m。
  => 推荐摆 0.30 / 0.40 / 0.50 / 0.60 / 0.70 m 这几档
     (外沿约 92/69/55/46/40 px, 全部 >= 40px, 都在实测能稳定检出的区间里)。
  => 想标更远就【把 tag 印大一点】, 量出新的黑框外沿边长填 --w=。
  => 某一档没有 TAG 行很正常(尺寸谐振), 跳过就行, 所以多给几段。
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "calib_tag.py")
SESSION = os.path.join(HERE, "_calib_session.py")
LIVE = os.path.join(HERE, "live_run.py")
FIT = os.path.join(HERE, "fit_focal.py")
LOGDIR = os.path.join(ROOT, "testimgs")

# TAG 行形如: [  12.3s] TAG id0 side80.3 w81 h81 cx80 cy60
LINE_T_RE = re.compile(r"\[\s*([\d.]+)s\]\s*TAG\s")
SIDE_RE = re.compile(r"side(\d+(?:\.\d+)?)")


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return None
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__)
        return 1

    port = args[0]
    secs = int(args[1])
    segs = []
    tag_w = 0.100
    for a in args[2:]:
        if a.startswith("--w="):
            tag_w = float(a[4:])
        else:
            parts = a.split(",")
            assert len(parts) == 3, "分段格式应为 起s,止s,距离m : %s" % a
            segs.append((float(parts[0]), float(parts[1]), float(parts[2])))

    if not segs:
        print("!! 至少要给一段")
        return 1
    last_end = max(b for _, b, _ in segs)
    if secs < last_end + 3:
        secs = int(last_end + 5)
        print(">>> 时长自动延长到 %d 秒（要覆盖到最后一段结束）" % secs)

    # ---- 1. 生成会话脚本 ----
    src = open(SRC, "r", encoding="utf-8").read()
    seg_lit = "[" + ", ".join("(%.0f, %.0f, %.2f)" % s for s in segs) + "]"
    a = src.replace("SEGMENTS = []", "SEGMENTS = " + seg_lit)
    assert a != src, "没找到 SEGMENTS = []"
    b = a.replace("TAG_W_M = 0.100", "TAG_W_M = %.4f" % tag_w)
    assert b != a, "没找到 TAG_W_M = 0.100"
    open(SESSION, "w", encoding="utf-8").write(b)
    print(">>> 已生成会话脚本, SEGMENTS = %s, TAG_W_M = %.4f m" % (seg_lit, tag_w))

    print("\n>>> 分段计划（按屏幕提示移动 tag）：")
    for a_, b_, d in segs:
        print("      %3.0f ~ %3.0f s  ->  %.2f m" % (a_, b_, d))
    print(">>> 即将开始，共 %d 秒。请把 tag 正对镜头（别斜），放到量准的距离上。\n" % secs)
    time.sleep(2)

    # ---- 2. 跑板子 ----
    py = sys.executable
    p = subprocess.run([py, LIVE, port, SESSION, str(secs)],
                       capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    sys.stdout.write(out)

    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)
    logp = os.path.join(LOGDIR, "calib_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    with open(logp, "w", encoding="utf-8") as f:
        f.write(out)
    # 收集每个 TAG 行: (秒, 像素边长)。边长优先取 side 字段(见 calib_tag.py)
    rows = []
    for m in LINE_T_RE.finditer(out):
        t = float(m.group(1))
        e = out.find("\n", m.end())
        if e < 0:
            e = len(out)
        sm = SIDE_RE.search(out[m.end():e])
        rows.append((t, float(sm.group(1)) if sm else None))
    ntag = len([r for r in rows if r[1] is not None])
    print("\n>>> 日志已存 %s（有效 TAG 行 %d 条）" % (logp, ntag))
    if ntag == 0:
        print("!! 一条 tag 都没检到，先别拟合。检查：")
        print("   - tag 有没有进画面、是不是正对镜头（别斜）")
        print("   - tag 够不够大：QQVGA 下外沿要到 40px 左右才稳，")
        print("     100mm 的 tag 请摆到 0.7m 以内")
        print("   - 光线够不够（脚本已关自动增益/白平衡）")
        print("   - 是不是 36h11 家族")
        return 1

    # ---- 逐段报告: 每段检到几帧、边长中位数、以及"只用这一段算出的焦距" ----
    print("\n>>> 逐段检查（单点焦距指的是【只用这一段】反算的 FOCAL_PX，"
          "各段接近才说明标定可信）：")
    solo = []
    for a_, b_, d in segs:
        sel = [r[1] for r in rows if a_ <= r[0] < b_ and r[1]]
        if not sel:
            print("      段 %3.0f~%3.0f s  %.2f m : 没有 TAG 行"
                  "（该尺寸检不到，或 tag 没摆到位）→ 跳过" % (a_, b_, d))
            continue
        med = median(sel)
        f_solo = d * med / tag_w
        solo.append(f_solo)
        spread = max(sel) - min(sel)
        flag = "  <- 边长离散 %.1fpx，别动它再采一次" % spread if spread > 2 else ""
        print("      段 %3.0f~%3.0f s  %.2f m : %3d 帧  边长中位数 %6.2f px"
              "  -> 单点 FOCAL_PX = %6.1f%s"
              % (a_, b_, d, len(sel), med, f_solo, flag))
    if len(solo) >= 2:
        lo, hi = min(solo), max(solo)
        print("      各段单点 FOCAL_PX 范围 %.1f ~ %.1f（极差 %.1f%%）"
              % (lo, hi, (hi - lo) / (sum(solo) / len(solo)) * 100))
        if (hi - lo) / (sum(solo) / len(solo)) * 100 > 10:
            print("      !! 极差超过 10%%，多半是某段距离量错 / tag 摆斜了 / 没站稳。")
    if len(solo) < 2:
        print("\n!! 有效段不足 2 段，没法做最小二乘。先把 tag 摆近一点再跑一次。")
        return 1

    # ---- 3. 拟合 ----
    seg_args = ["%.0f,%.0f,%.2f" % s for s in segs]
    print("\n>>> 拟合 ...")
    q = subprocess.run([py, FIT, logp, "%.4f" % tag_w, "--tag"] + seg_args,
                       capture_output=True)
    sys.stdout.write((q.stdout + q.stderr).decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
