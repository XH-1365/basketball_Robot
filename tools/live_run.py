# -*- coding: utf-8 -*-
"""
在 raw REPL 里跑一个"死循环"脚本（如 body_detect.py），实时把板上 stdout 流回来，
跑够 SECS 秒后发 Ctrl-C 优雅停止，再退回 friendly REPL。

用法:
  python tools/live_run.py COM16 body_detect.py 150

特殊: 如果板上脚本自己跑完了(默认以 RAM_ALLDONE 为结束标记), 就不会再发 Ctrl-C ——
      因为中途打断会截断正在回传的那张图。第 4 个参数可以改这个标记,
      比如棋盘格采集脚本用 CHESSDONE:
        python tools/live_run.py COM16 tools/shot_chess.py 2400 CHESSDONE
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402


def stream_for(s, secs, tag="RUN", stop_marker=None):
    s.timeout = 0.2
    t0 = time.time()
    text = ""
    last_report = 0.0
    while time.time() - t0 < secs:
        n = s.in_waiting
        if n:
            d = s.read(n)
            if d:
                chunk = d.decode("utf-8", "replace")
                text += chunk
                sys.stdout.write(chunk)
                sys.stdout.flush()
                if stop_marker and stop_marker in text:
                    print("\n>>> 板上脚本已自行跑完 (%s), 提前收工" % stop_marker)
                    break
        else:
            time.sleep(0.04)
        el = time.time() - t0
        if el - last_report > 15:
            sys.stdout.write("\n[%s %ds/%ds]\n" % (tag, int(el), secs))
            sys.stdout.flush()
            last_report = el
    return text


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    port = sys.argv[1]
    script = sys.argv[2]
    secs = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    marker = sys.argv[4] if len(sys.argv) > 4 else "RAM_ALLDONE"

    with io.open(script, "r", encoding="utf-8") as f:
        src = f.read()
    print(">>> 脚本 %s (%d bytes), 计划跑 %d 秒" % (script, len(src), secs))

    s = repl.open_port(port)
    try:
        repl.drain(s, 0.3)
        print(">>> 硬复位 + 打断 main.py ...")
        if not repl.hard_reset(s):
            print("!! 硬复位失败，继续")
        if not repl.enter_raw(s):
            print("!! 进不去 raw REPL")
            return 2

        data = src.encode("utf-8")
        for i in range(0, len(data), repl.CHUNK):
            s.write(data[i:i + repl.CHUNK])
            time.sleep(0.004)
        s.write(repl.CTRL_D)
        print(">>> 已下发，板子开始执行（LCD 现在应该有画面了）")
        print("-" * 56)

        text = stream_for(s, secs, "RUN", marker)

        print("-" * 56)
        if marker in text:
            print(">>> 脚本已自然结束 (%s)，不发 Ctrl-C（避免截断正在回传的图）" % marker)
        else:
            print(">>> 发送 Ctrl-C 停止 ...")
            s.write(repl.CTRL_C)
            time.sleep(0.8)
            extra = s.read(65536)
            if extra:
                sys.stdout.write(extra.decode("utf-8", "replace"))
                text += extra.decode("utf-8", "replace")

        repl.exit_raw(s)

        # --- 小结 ---
        shots = [ln for ln in text.splitlines() if ln.startswith("SHOT ")]
        okfiles = [ln for ln in text.splitlines()
                   if ln.startswith("E ") and len(ln.split()) == 3]
        dets = [ln for ln in text.splitlines() if ln.startswith("DET ")]
        alarms = [ln for ln in text.splitlines() if "ALARM" in ln]
        real = [ln for ln in dets if not ln.startswith("DET none")]
        chess = [ln for ln in text.splitlines() if "[CHESS] SAVED" in ln]
        print("\n===== 小结 =====")
        if chess:
            print("棋盘格照片: %s" % (chess[-1].split("已拍")[-1].strip()
                                      if "已拍" in chess[-1]
                                      else "%d 张" % len(chess)))
            for ln in chess[-5:]:
                print("   ", ln.strip())
        if shots or okfiles:
            print("SHOT 行(拍照次数记录): %d 条" % len(shots))
            for ln in shots[-8:]:
                print("   ", ln)
            print("回传完成 E 行: %d 条" % len(okfiles))
        if dets or alarms:
            print("DET 上报行: %d (其中含目标: %d)" % (len(dets), len(real)))
            print("ALARM 次数: %d" % len(alarms))
            if real:
                print("最后 5 条有目标的上报:")
                for ln in real[-5:]:
                    print("   ", ln)
        if not (shots or okfiles or dets or alarms or chess):
            print("没有 SHOT / CHESS / 回传 / DET 行 —— 脚本可能没跑起来")
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
