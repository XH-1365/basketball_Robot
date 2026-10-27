# -*- coding: utf-8 -*-
"""
被动偷看板子串口 + 分级探针，判断板子处于什么状态。
不复位。只做：静读 -> 发回车 -> 发 Ctrl-C。

用法: python tools/peek.py COM16
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402

port = sys.argv[1] if len(sys.argv) > 1 else "COM16"


def read_for(s, secs):
    s.timeout = 0.2
    t0 = time.time()
    buf = b""
    while time.time() - t0 < secs:
        n = s.in_waiting
        if n:
            d = s.read(n)
            if d:
                buf += d
        else:
            time.sleep(0.05)
    return buf


s = repl.open_port(port)
try:
    print("--- 1) 静读 4 秒 ---")
    a = read_for(s, 4)
    print("收到 %d 字节: %r" % (len(a), a[:300]))

    print("--- 2) 发一个回车，再读 3 秒（REPL 活着的话会回显提示符）---")
    s.write(b"\r\n")
    b = read_for(s, 3)
    print("收到 %d 字节: %r" % (len(b), b[:300]))

    print("--- 3) 发 Ctrl-C，再读 4 秒 ---")
    s.write(repl.CTRL_C)
    c = read_for(s, 4)
    print("收到 %d 字节: %r" % (len(c), c[:800]))

    print("--- 判定 ---")
    allb = a + b + c
    if b">>>" in allb or b">>>" in b:
        print("板子在 REPL 提示符 —— main.py 已经退出了（崩溃 or 被中断）")
    elif b"DET" in allb:
        print("程序还在跑（有 DET 上报）—— 那问题在显示侧")
    elif len(allb) == 0:
        print("完全无响应 —— 板子挂死了，需要硬复位")
    else:
        print("有反应但不含 >>> 或 DET，看上面的原始内容")
finally:
    try:
        s.dtr = False
        s.rts = False
        time.sleep(0.2)
    except Exception:
        pass
    s.close()
