# -*- coding: utf-8 -*-
# 连续复位 N 次, 每次抓 6 秒开机日志, 找 "sdcard init ok"
import sys
import time

import serial

port = "COM16"
s = serial.Serial()
s.port = port
s.baudrate = 115200
s.timeout = 0.1
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False

for i in range(5):
    s.reset_input_buffer()
    s.dtr = True
    time.sleep(0.3)
    s.dtr = False
    buf = b""
    t0 = time.time()
    while time.time() - t0 < 6:
        d = s.read(4096)
        if d:
            buf += d
    txt = buf.decode("utf-8", "replace")
    ok = "sdcard init ok" in txt
    print("第 %d 次复位: sdcard init ok = %s" % (i + 1, ok))
    for ln in txt.splitlines():
        if "sdcard" in ln.lower():
            print("    >", ln.strip())
    if ok:
        print(">>> 第 %d 次就认到了, 停" % (i + 1))
        break
s.close()
