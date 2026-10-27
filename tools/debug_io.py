# -*- coding: utf-8 -*-
"""逐步调试与板子的串口交互，打印每一步的原始字节。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"


def show(tag, data):
    txt = data.decode("utf-8", "replace")
    print("[%s] %d bytes: %r" % (tag, len(data), txt))


s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.25
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False
print("opened, dtr=%s rts=%s" % (s.dtr, s.rts))

print("\n--- 步骤1: 读上电/历史残留 ---")
show("boot", s.read(8192))

print("\n--- 步骤2: 发 \\r 看有没有 friendly REPL 提示符 ---")
s.write(b"\r")
show("resp", s.read(4096))

print("\n--- 步骤3: 发 Ctrl-C x3 ---")
for _ in range(3):
    s.write(b"\x03")
    time.sleep(0.1)
show("after-ctrlc", s.read(4096))

print("\n--- 步骤4: 发 Ctrl-A 进 raw REPL ---")
s.write(b"\x01")
t = time.time()
buf = b""
while time.time() - t < 3:
    c = s.read(1)
    if c:
        buf += c
show("raw-repl", buf)

if b">" not in buf:
    print("!! 没能进入 raw REPL")
    print("--- 再试: Ctrl-B 回 friendly，然后 Ctrl-C ---")
    s.write(b"\x02")
    time.sleep(0.3)
    show("ctrl-b", s.read(4096))
    s.write(b"\r\x03")
    time.sleep(0.3)
    show("ctrl-c", s.read(4096))
    s.close()
    sys.exit(1)

print("\n--- 步骤5: raw REPL 里执行 print('hello') ---")
s.write(b"print('hello_k210')\n")
s.write(b"\x04")
t = time.time()
buf = b""
while time.time() - t < 5:
    c = s.read(1)
    if c:
        buf += c
show("exec", buf)

print("\n--- 步骤6: Ctrl-B 退出 ---")
s.write(b"\x02")
time.sleep(0.2)
show("exit", s.read(4096))
s.close()
print("\ndone")
