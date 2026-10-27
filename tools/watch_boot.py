# -*- coding: utf-8 -*-
"""
验证 /flash/main.py 开机自启：只做 DTR 复位脉冲，不发 Ctrl-C，
让 main.py 自己跑起来，然后流式看串口输出。

用法: python tools/watch_boot.py COM16 80
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM16"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 80

    s = repl.open_port(port)
    try:
        repl.drain(s, 0.3)
        print(">>> 复位脉冲（故意不发 Ctrl-C，让 main.py 自己启动）...")
        s.reset_input_buffer()
        s.dtr = True
        time.sleep(0.3)
        s.dtr = False

        print(">>> 等待 main.py 自动运行，%d 秒 ..." % secs)
        print("-" * 56)
        s.timeout = 0.2
        t0 = time.time()
        text = ""
        last = 0.0
        while time.time() - t0 < secs:
            n = s.in_waiting
            if n:
                d = s.read(n)
                if d:
                    c = d.decode("utf-8", "replace")
                    text += c
                    sys.stdout.write(c)
                    sys.stdout.flush()
            else:
                time.sleep(0.04)
            el = time.time() - t0
            if el - last > 15:
                sys.stdout.write("\n[BOOT %ds/%ds]\n" % (int(el), secs))
                sys.stdout.flush()
                last = el

        print("-" * 56)
        keep = len(sys.argv) > 3 and sys.argv[3] == "keep"
        if not keep:
            print(">>> 发 Ctrl-C 停止检测 ...")
            s.write(repl.CTRL_C)
            time.sleep(0.8)
            e = s.read(65536)
            if e:
                c = e.decode("utf-8", "replace")
                text += c
                sys.stdout.write(c)

        dets = [ln for ln in text.splitlines() if ln.startswith("DET ")]
        real = [ln for ln in dets if not ln.startswith("DET none")]
        print("\n===== 开机自启小结 =====")
        print("模型加载成功: %s" % ("是" if "model load succeed" in text else "否"))
        print("进入检测循环: %s" % ("是" if "开始实时检测" in text else "否"))
        print("DET 上报 %d 行（含目标 %d 行）" % (len(dets), len(real)))
        for ln in real[-5:]:
            print("   ", ln)

        if keep:
            print("\n>>> keep: 重新复位让 main.py 一直跑下去（LCD 保持有画面）...")
            s.reset_input_buffer()
            s.dtr = True
            time.sleep(0.3)
            s.dtr = False
            time.sleep(6)
            tail = s.read(65536)
            if tail:
                sys.stdout.write(tail.decode("utf-8", "replace"))
            print("\n>>> 板子已重新启动，main.py 正在运行。断开串口。")
    finally:
        # 关串口前把控制线放低，避免 close 时拉 DTR 把板子按在复位状态
        try:
            s.dtr = False
            s.rts = False
            time.sleep(0.2)
        except Exception:
            pass
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
