# -*- coding: utf-8 -*-
"""长时间监听: 打开串口后耐心等待 + 定时发 Ctrl-C，打印板子的一切输出。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 25

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.25
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False
print("opened (dtr=False rts=False), 监听 %d 秒..." % SECONDS)

t0 = time.time()
last_beep = -1
total = 0
while time.time() - t0 < SECONDS:
    el = time.time() - t0
    # 前 3 秒先什么都不发，让板子安静启动
    if el > 3.0 and int(el) != last_beep:
        last_beep = int(el)
        s.write(b"\r\x03")
    d = s.read(16384)
    if d:
        total += len(d)
        print("[t=%4.1fs] RX %4d bytes: %r" % (el, len(d), d[:300]))
s.close()
print("总计收到 %d 字节" % total)
if total == 0:
    print("=> 板子完全没有输出。可能需要手动按板上的复位键，或 DTR 电平不对。")
