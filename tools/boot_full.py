# -*- coding: utf-8 -*-
"""DTR 跳变复位 -> 完整捕获 10 秒启动日志，看它卡在哪一步。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.2
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False
time.sleep(0.3)
s.reset_input_buffer()

print("触发 DTR 复位（拉高 0.25s 再放开）...")
s.dtr = True
time.sleep(0.25)
s.dtr = False

t0 = time.time()
buf = b""
while time.time() - t0 < 10:
    d = s.read(4096)
    if d:
        buf += d
        sys.stdout.write(d.decode("utf-8", "replace"))
        sys.stdout.flush()
s.close()

txt = buf.decode("utf-8", "replace")
print("")
print("=" * 56)
print("总计 %d 字节" % len(buf))
print("=" * 56)
checks = [
    ("启动日志", "[CanMV]" in txt),
    ("YAHBOOM 标识", "YAHBOOM" in txt),
    ("文件系统报错", "lfs" in txt.lower() or "filesystem" in txt.lower()),
    ("REPL 提示符", ">>>" in txt),
    ("异常/panic", "panic" in txt.lower() or "fault" in txt.lower() or "Exception" in txt),
]
for name, ok in checks:
    print("  %-14s: %s" % (name, "有" if ok else "无"))
