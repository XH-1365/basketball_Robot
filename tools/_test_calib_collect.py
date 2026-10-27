# -*- coding: utf-8 -*-
"""
calib_collect.py 的离线整链自测（不需要板子、不需要打印 tag）。

做法: 把 calib_collect.LIVE 换成一个小假脚本, 它只打印一段【合成的 TAG 日志】
      (按真值 FOCAL_PX=277 正着算出来的像素边长), 然后照常走:
        生成会话脚本 -> 跑"板子" -> 存日志 -> 逐段统计 -> 调 fit_focal 拟合
      看最终反算出的 FOCAL_PX 是否是 277, 以及逐段表格是否正常。

顺带覆盖: 某一档【没有 TAG 行】时应当走"跳过"分支, 而不是崩掉。

真值: FOCAL_PX = 277.0, TAG_W_M = 0.100 m
      side_px = FOCAL_PX * TAG_W_M / D
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import calib_collect as cc  # noqa: E402

F_TRUE = 277.0
TAG_W_M = 0.100
PER_SEG = 5

# (真实距离, 起秒, 止秒, 该段是否放 TAG 行)
SEGS = ((0.30, 0.0, 20.0, True),
        (0.45, 20.0, 40.0, True),
        (0.60, 40.0, 60.0, True),
        (0.70, 60.0, 80.0, True),
        (0.90, 80.0, 100.0, False))     # 故意留一档空的, 验证"跳过"分支


def build_log():
    lines = ["[TAG] AprilTag 标定采集启动",
             "[TAG] TAG_W_M=0.1000 m  FOCAL_PX(当前估值)=277.0"]
    for d, t0, t1, has_tag in SEGS:
        if not has_tag:
            continue
        side = F_TRUE * TAG_W_M / d
        for k in range(PER_SEG):
            t = t0 + (t1 - t0) * k / float(PER_SEG)
            lines.append("[%6.1fs] TAG id%d side%.1f w%d h%d cx80 cy60"
                         % (t, 0, side, int(round(side)), int(round(side))))
            lines.append("[%6.1fs] TAGEST id%d d%.3fm (按 FOCAL_PX=277.0 反推, "
                         "边长用 %.1fpx)" % (t, 0, d, side))
    lines.append("[ 101.0s] STAT n_tag=20 frames=600 fps=23.0 free=657888")
    return "\n".join(lines) + "\n"


def main():
    # ---- 造一个假"板端执行器" ----
    fake = os.path.join(HERE, "_tmp_fake_live.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write("# 假 live_run: 只把合成日志打出来\n")
        f.write("import sys\n")
        f.write("sys.stdout.write(%r)\n" % build_log())
    cc.LIVE = fake

    seg_args = ["%.0f,%.0f,%.2f" % (t0, t1, d) for d, t0, t1, _ in SEGS]
    sys.argv = ["calib_collect.py", "COM16", "100", "--w=%.3f" % TAG_W_M] + seg_args

    print("=" * 66)
    print("调用 calib_collect.main(), 分段: %s" % seg_args)
    print("=" * 66)

    # 注意: 拟合结果是用 sys.stdout.write 打在控制台上的, 不写进日志文件,
    # 所以这里把 stdout 接管下来才能检查 FOCAL_PX。
    import io as _io
    buf = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    t0 = time.time()
    try:
        rc = cc.main()
    finally:
        sys.stdout = old_stdout
    dt = time.time() - t0
    console = buf.getvalue()

    print("=" * 66)
    print("main() 返回 %s, 耗时 %.1fs" % (rc, dt))
    print("--- 捕获到的控制台输出 ---")
    print(console)
    print("--- 输出结束 ---")

    assert rc == 0, "main() 返回非 0: %s" % rc

    # 最新的 ground/calib 日志
    logdir = os.path.join(os.path.dirname(HERE), "testimgs")
    logs = sorted(f for f in os.listdir(logdir) if f.startswith("calib_"))
    assert logs, "没生成 calib 日志"
    newest = os.path.join(logdir, logs[-1])
    txt = open(newest, encoding="utf-8").read()
    print("最新日志: %s (%d 字节)" % (logs[-1], len(txt)))

    rows = cc.LINE_T_RE.findall(txt)
    print("日志里 TAG 行 %d 条 (期望 %d)" % (len(rows), 4 * PER_SEG))
    assert len(rows) == 4 * PER_SEG, "TAG 行数不对"

    # ---- 复算逐段单点焦距, 确认各段都收敛到真值 ----
    print("\n逐段复核（用 calib_collect 的正则自己算一遍）:")
    ok = 0
    for d, t0s, t1s, has_tag in SEGS:
        sel = []
        for m in cc.LINE_T_RE.finditer(txt):
            t = float(m.group(1))
            if not (t0s <= t < t1s):
                continue
            e = txt.find("\n", m.end())
            sm = cc.SIDE_RE.search(txt[m.end():e])
            if sm:
                sel.append(float(sm.group(1)))
        if not has_tag:
            print("  段 %.2f m : 样本 %d 个  -> 应当是 0(空档)" % (d, len(sel)))
            assert len(sel) == 0, "空档居然有样本"
            continue
        med = cc.median(sel)
        f_solo = d * med / TAG_W_M
        err = abs(f_solo - F_TRUE) / F_TRUE * 100
        print("  段 %.2f m : 样本 %d 个  边长中位数 %.2f px  -> 单点 FOCAL_PX %.1f"
              " (偏差 %.2f%%)" % (d, len(sel), med, f_solo, err))
        assert err < 2.0, "单点偏差过大"
        ok += 1

    m = re.search(r"FOCAL_PX\s*=\s*(-?[\d.]+)", console)
    assert m, "控制台输出里没找到 FOCAL_PX(拟合那步没跑?)"
    f_fit = float(m.group(1))
    err = abs(f_fit - F_TRUE) / F_TRUE * 100
    print("整链拟合: 真值 %.1f -> 反算 %.1f   偏差 %.2f%%" % (F_TRUE, f_fit, err))
    assert err < 2.0, "整链拟合偏差过大 %.2f%%" % err

    # 逐段表格应当出现过
    assert "单点 FOCAL_PX" in console, "逐段报告没打出来"
    assert "没有 TAG 行" in console or "跳过" in console, "空档的跳过分支没走到"
    print("OK 逐段报告与空档跳过分支都走到了")

    os.remove(fake)
    print("=" * 66)
    print("通过: %d 个有效段全部收敛, 空档被正确跳过, 整链偏差 %.2f%%" % (ok, err))
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
