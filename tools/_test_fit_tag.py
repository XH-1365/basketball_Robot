# -*- coding: utf-8 -*-
"""
fit_focal.py --tag 的离线自测（不需要板子、不需要打印 tag）。

覆盖三件事:
 1) 新格式日志（TAG 行带 side 字段）-> 应当【优先】用 side
 2) 老格式日志（没有 side, 只有 h）-> 应当【退回】用 h, 仍然能反算
 3) TAGEST 行也是 "TAG" 开头, 不能被当成样本收进去

真值: FOCAL_PX = 277.0,  TAG_W_M = 0.100 m
      某距离 D 上 tag 的像素边长 side = f * TAG_W_M / D
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fit_focal  # noqa: E402

F_TRUE = 277.0
TAG_W_M = 0.100

# (真实距离 m, 该段时间起点 s, 该段时间终点 s) —— 必须和传给 fit_focal 的分段一致
CASES = ((0.5, 0.0, 20.0), (1.0, 20.0, 40.0), (1.5, 40.0, 60.0), (2.0, 60.0, 80.0))

SEG_ARGS = ["%.0f,%.0f,%.2f" % (t0, t1, d) for d, t0, t1 in CASES]

# 每段的预期像素边长
EXPECT = [F_TRUE * TAG_W_M / d for d, _, _ in CASES]

# 每段塞几帧
PER_SEG = 6


def build_log(with_side):
    lines = ["[CanMV] boot ...", "[TAG] AprilTag 标定采集启动"]
    for (d, t0, t1), s in zip(CASES, EXPECT):
        for k in range(PER_SEG):
            t = t0 + (t1 - t0) * k / float(PER_SEG)
            if with_side:
                # 新格式: side 一位小数 + 保留 w/h 兼容
                lines.append("[%6.1fs] TAG id%d side%.1f w%d h%d cx80 cy60"
                             % (t, 0, s, int(round(s)), int(round(s))))
                # 干扰行: 也是 TAG 开头, 但没有 side 字段
                lines.append("[%6.1fs] TAGEST id%d d%.3fm (按 FOCAL_PX=277.0 反推, "
                             "边长用 %.1fpx)" % (t, 0, d, s))
            else:
                lines.append("[%6.1fs] TAG id%d w%d h%d cx80 cy60"
                             % (t, 0, int(round(s)), int(round(s))))
    return "\n".join(lines) + "\n"


def write_tmp(text, tag):
    p = os.path.join(HERE, "_tmp_%s.log" % tag)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def run_fit(log_text, tag):
    p = write_tmp(log_text, tag)
    args = [sys.executable, os.path.join(HERE, "fit_focal.py"), p,
            "%.4f" % TAG_W_M, "--tag"] + SEG_ARGS
    q = subprocess.run(args, capture_output=True)
    out = (q.stdout + q.stderr).decode("utf-8", "replace")
    os.remove(p)
    return out


def check(name, with_side):
    print("=" * 64)
    print("用例: %s" % name)
    print("=" * 64)

    log = build_log(with_side)
    p = write_tmp(log, "parse")
    rows = fit_focal.parse_log(p, "TAG")
    os.remove(p)

    vals = [v for _, vs in rows for v in vs]
    n_tagest = len(re.findall(r"\]\s*TAGEST", log))
    print("  日志: TAG 有效行 %d, 每段 %d 帧, TAGEST 干扰行 %d"
          % (len(rows), PER_SEG, n_tagest))
    print("  解析到样本 %d 个 (期望 %d)" % (len(vals), len(CASES) * PER_SEG))
    assert len(vals) == len(CASES) * PER_SEG, \
        "样本数不对: TAGEST 被误收了? (期望 %d, 实得 %d)" \
        % (len(CASES) * PER_SEG, len(vals))

    print("  各段第一个样本: %s" % [round(v, 1) for v in vals[::PER_SEG]])
    print("  各段理论边长  : %s" % [round(v, 1) for v in EXPECT])

    first_want = EXPECT[0]
    if with_side:
        assert abs(vals[0] - first_want) < 0.06, \
            "没有优先用 side: 拿到 %s, 期望 %.1f" % (vals[0], first_want)
        print("  OK 优先取 side 字段 (%.1f, 理论 %.1f)" % (vals[0], first_want))
    else:
        want = int(round(first_want))
        assert abs(vals[0] - want) < 0.5, \
            "退回 h 失败: 拿到 %s, 期望 %d" % (vals[0], want)
        print("  OK 无 side 时退回 h 字段 (%d, 理论取整 %d)" % (vals[0], want))

    out = run_fit(log, "fit")
    print(out)
    m = re.search(r"FOCAL_PX\s*=\s*(-?[\d.]+)", out)
    assert m, "没解析到 FOCAL_PX"
    f = float(m.group(1))
    err = abs(f - F_TRUE) / F_TRUE * 100
    print("  真值 %.1f -> 反算 %.1f   偏差 %.2f%%" % (F_TRUE, f, err))
    assert err < 3.0, "偏差过大 %.2f%%" % err
    print("  通过\n")
    return err


def main():
    e1 = check("新格式(带 side)", True)
    e2 = check("老格式(只有 h)", False)
    print("=" * 64)
    print("两个用例都通过:  side 优先偏差 %.2f%%,  h 兼容偏差 %.2f%%" % (e1, e2))
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
