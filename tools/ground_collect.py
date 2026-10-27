# -*- coding: utf-8 -*-
"""
地面法(GROUND)标定 —— PC 端一键驱动。

做三件事:
  1. 按你给的分段计划生成板端会话脚本 tools/_ground_session.py
     （屏幕上实时显示"站到 X.XX m 处 + 倒计时"）
  2. 在板子上跑满指定秒数，把完整日志存到 testimgs/ground_<时间戳>.log
  3. 按分段把 FEET 行的 y_feet 取中位数，自动调用 fit_pitch.py 反算
     相机俯角 CAM_PITCH_DEG

用法:
  python tools/ground_collect.py COM16 90 "0,20,1.0" "20,40,2.0" "40,60,3.0" "60,80,4.0"
  python tools/ground_collect.py COM16 90 --hc=1.35 "0,20,1.0" "20,40,2.0" "40,60,3.0"

参数:
  COM16               串口
  90                  总时长(秒)，要 >= 最后一段的结束秒
  "起s,止s,真实距离m"   至少给 3 段（未知数有 1 个，3 点起才看得见离散度）
  --hc=1.20           相机镜头离地高度(米)，默认 1.20，**一定要拿卷尺量**
  --f=277.0 --cy=120  焦距 / 主点行，默认沿用 body_detect.py 的值

现场要求（不满足标定必废）:
  - 人【正面站直、不低头】，整双脚都在画面里（脚尖不能被画面底边切掉）
  - 站在卷尺量准的位置上，脚后跟对准刻度
  - 相机固定死，标定全程不要碰
  - 地面平整，别站在台阶/地毯边
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "ground_probe.py")
SESSION = os.path.join(HERE, "_ground_session.py")
LIVE = os.path.join(HERE, "live_run.py")
FIT = os.path.join(HERE, "fit_pitch.py")
LOGDIR = os.path.join(ROOT, "testimgs")

# 与 ground_probe.py / body_detect.py 一致的默认值
DEF_F = 277.0
DEF_CY = 120.0

FEET_RE = re.compile(r"\]\s*FEET\s+yf=\s*(-?\d+)\s+y=\s*(-?\d+)\s+h=\s*(\d+)"
                     r"\s+w=\s*(\d+)\s+cx=\s*(-?\d+)\s+p=([\d.]+)")


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return None
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def parse_feet(out):
    """返回 [(秒, yf, y, h, w, cx, p), ...]"""
    rows = []
    for m in FEET_RE.finditer(out):
        # 秒数在行首的 [  12.3s] 里。注意 FEET_RE 从 "]" 开始匹配,
        # 所以不能拿 m.start() 之前那半截去找 —— 那样会把 "]" 切掉,
        # 正则永远匹配不上, 结果全部退化成 t=-1(踩过一次)。
        # 正确做法: 取【整行】再搜。
        line_start = out.rfind("\n", 0, m.start())
        line_end = out.find("\n", m.end())
        if line_end < 0:
            line_end = len(out)
        line = out[line_start + 1:line_end]
        mt = re.search(r"\[\s*([\d.]+)s\]", line)
        t = float(mt.group(1)) if mt else -1.0
        rows.append((t, int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), float(m.group(6))))
    return rows


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__)
        return 1

    port = args[0]
    secs = int(args[1])
    segs = []
    hc = 1.20
    f = DEF_F
    cy = DEF_CY
    for a in args[2:]:
        if a.startswith("--hc="):
            hc = float(a[5:])
        elif a.startswith("--f="):
            f = float(a[4:])
        elif a.startswith("--cy="):
            cy = float(a[5:])
        else:
            parts = a.split(",")
            assert len(parts) == 3, "分段格式应为 起s,止s,距离m : %s" % a
            segs.append((float(parts[0]), float(parts[1]), float(parts[2])))

    if len(segs) < 3:
        print("!! 至少要给 3 段（1 个未知数，3 点起才看得出离散度）")
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
    b = a.replace("CAM_H_M = 1.20", "CAM_H_M = %.3f" % hc)
    assert b != a, "没找到 CAM_H_M = 1.20"
    open(SESSION, "w", encoding="utf-8").write(b)
    print(">>> 已生成会话脚本, SEGMENTS = %s, CAM_H_M = %.3f m" % (seg_lit, hc))

    print("\n>>> 分段计划（按屏幕提示走到对应位置）：")
    for a_, b_, d in segs:
        print("      %3.0f ~ %3.0f s  ->  站到 %.2f m" % (a_, b_, d))
    print(">>> 即将开始，共 %d 秒。要求：正面站直、双脚完整在画面里、"
          "脚后跟踩准刻度、相机全程不动。\n" % secs)
    time.sleep(2)

    # ---- 2. 跑板子 ----
    py = sys.executable
    p = subprocess.run([py, LIVE, port, SESSION, str(secs)], capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    sys.stdout.write(out)

    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)
    logp = os.path.join(LOGDIR, "ground_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    with open(logp, "w", encoding="utf-8") as fh:
        fh.write(out)

    rows = parse_feet(out)
    print("\n>>> 日志已存 %s（FEET 行 %d 条）" % (logp, len(rows)))
    if not rows:
        print("!! 一行 FEET 都没有。检查：模型是否加载成功 / 人有没有进画面 / "
              "阈值 THRESHOLD 是不是太高")
        return 1

    # ---- 3. 分段聚合 ----
    print("\n>>> 分段聚合（每段取 y_feet 中位数，已剔掉脚被画面底边切掉的样本）：")
    pts = []
    for a_, b_, d in segs:
        sel = [r for r in rows
               if a_ <= r[0] < b_ and r[1] < 240 - 2 and r[1] > 0]
        if not sel:
            print("      %3.0f~%3.0f s  %.2f m : 无有效样本" % (a_, b_, d))
            continue
        yf = median([r[1] for r in sel])
        hs = median([r[3] for r in sel])
        ps = median([r[6] for r in sel])
        spread = max(r[1] for r in sel) - min(r[1] for r in sel)
        pts.append((d, yf))
        flag = ""
        if spread > 12:
            flag = "  <- 离散大(%d px)，这段数据不太可信" % spread
        print("      %3.0f~%3.0f s  %.2f m : n=%3d  y_feet=%6.1f  h=%5.1f  "
              "p=%.2f  离散=%d px%s"
              % (a_, b_, d, len(sel), yf, hs, ps, spread, flag))

    if len(pts) < 3:
        print("\n!! 有效段不足 3 段，没法拟合。先确认每段都能稳定检出人。")
        return 1

    # ---- 4. 拟合 ----
    print("\n>>> 反算相机俯角 ...")
    fit_args = [py, FIT, "%.3f" % hc, "--f=%.1f" % f, "--cy=%.1f" % cy]
    fit_args += ["D=%.2f,y=%.1f" % (d, y) for d, y in pts]
    q = subprocess.run(fit_args, capture_output=True)
    sys.stdout.write((q.stdout + q.stderr).decode("utf-8", "replace"))

    print("\n>>> 下一步: 把上面算出的 CAM_PITCH_DEG 填进 body_detect.py 的配置区,")
    print(">>> 同时把 DIST_MODE 改成 \"GROUND\"(或 \"AUTO\")，")
    print(">>> 然后跑 python tools/deploy.py COM16 推到板子上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
