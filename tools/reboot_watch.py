# -*- coding: utf-8 -*-
"""
验证 main.py 开机自启是否正常。

怀疑点：上一次 repl.py 会话在 CH340 缓冲里残留了 Ctrl-C 字节，
下一次复位时被刚启动的 main.py 收到 -> 立刻打断 -> 掉进 REPL。
（所以主脚本自启"看起来"坏了）

做法：先把串口缓冲彻底冲刷干净，然后连做两次复位，只看第二次。

用法: python tools/reboot_watch.py COM16 25
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402


def pulse(s, label):
    s.reset_input_buffer()
    print(">>> [%s] DTR 复位脉冲..." % label)
    s.dtr = True
    time.sleep(0.3)
    s.dtr = False


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM16"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 25

    s = repl.open_port(port)
    try:
        # ---- 0. 彻底冲刷，把上一次会话残留的字节全读掉 ----
        print(">>> 冲刷串口缓冲 (3s)...")
        s.timeout = 0.2
        t0 = time.time()
        junk = b""
        while time.time() - t0 < 3.0:
            d = s.read(65536)
            if d:
                junk += d
            else:
                time.sleep(0.05)
        print(">>> 冲掉了 %d 字节" % len(junk))

        # ---- 1. 第一次复位：只为把板子带到干净状态，不看它 ----
        pulse(s, "第1次/弃用")
        time.sleep(3.0)
        s.reset_input_buffer()
        n = len(s.read(65536))
        print(">>> 第 1 次复位后丢弃 %d 字节" % n)
        # 再狂发 Ctrl-C 确保落到 >>>，尽量把缓冲抽干
        for _ in range(6):
            s.write(repl.CTRL_C)
            time.sleep(0.2)
            s.read(65536)
        time.sleep(0.5)
        s.read(65536)

        # ---- 2. 第二次复位：这次才是真正的观察窗 ----
        pulse(s, "第2次/观察")
        print(">>> 观察 %d 秒 ..." % secs)
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
            if el - last > 10:
                sys.stdout.write("\n[BOOT %ds/%ds]\n" % (int(el), secs))
                sys.stdout.flush()
                last = el
        print("-" * 56)

        dets = [ln for ln in text.splitlines() if ln.startswith("DET ")]
        real = [ln for ln in dets if not ln.startswith("DET none")]
        print("\n===== 结果 =====")
        print("main.py 自启     : %s" % ("是" if "模式:BODY" in text else "否"))
        print("模型加载成功     : %s" % ("是" if "model load succeed" in text else "否"))
        print("进入检测循环     : %s" % ("是" if "开始实时检测" in text else "否"))
        print("WDT 武装         : %s" % ("是" if "[WDT] 已武装" in text else "否"))
        print("掉进裸 REPL      : %s" % ("是" if "MicroPython v2.1.1" in text else "否"))
        print("sdcard 挂载      : %s" % ("ok" if "sdcard mount ok" in text else "失败/未出现"))
        print("DET 上报 %d 行（含目标 %d 行）" % (len(dets), len(real)))
    finally:
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
