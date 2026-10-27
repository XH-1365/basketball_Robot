# -*- coding: utf-8 -*-
"""串口通断探针: 不写任何东西, 先纯听; 再打 Ctrl-C; 再听。

用来区分三种情况:
  A. 板子根本没在吐数据(卡死/没上电)
  B. 板子在吐数据但吃不到 Ctrl-C(比如跑在 C 层死循环里)
  C. 口子本身被别的进程占着 / 打不开
"""
import sys
import time

import serial
import serial.tools.list_ports as lp

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

print("--- 当前串口列表 ---")
for p in lp.comports():
    print("  %-8s %s" % (p.device, p.description))

print("--- 打开 %s @ %d ---" % (PORT, BAUD))
try:
    s = serial.Serial(PORT, BAUD, timeout=0.2)
except Exception as e:
    print("!! 打开失败: %r" % (e,))
    sys.exit(2)

try:
    # 铁律: 两个都拉低, 否则板子会复位/无响应
    s.dtr = False
    s.rts = False
    time.sleep(0.3)
    s.reset_input_buffer()

    print("--- 阶段1: 纯听 3s (不发任何字节) ---")
    t0 = time.time()
    n = 0
    while time.time() - t0 < 3.0:
        d = s.read(4096)
        if d:
            n += len(d)
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
    print("\n--- 阶段1 收到 %d 字节 ---" % n)

    print("--- 阶段2: 打 3 次 Ctrl-C ---")
    for _ in range(3):
        s.write(b"\x03\x03\x03")
        time.sleep(0.15)
    s.reset_input_buffer()

    print("--- 阶段3: 听 3s ---")
    t0 = time.time()
    n2 = 0
    while time.time() - t0 < 3.0:
        d = s.read(4096)
        if d:
            n2 += len(d)
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
    print("\n--- 阶段3 收到 %d 字节 ---" % n2)

    print("--- 阶段4: 发一次回车, 听 1.5s ---")
    s.write(b"\r\n")
    time.sleep(1.5)
    d = s.read(8192)
    print(repr(d[:400]))
    print("阶段4 收到 %d 字节" % len(d))
finally:
    s.close()
