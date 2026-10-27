# -*- coding: utf-8 -*-
"""用 DTR/RTS 脉冲尝试复位 K210 并捕获启动日志（用来判断板子是否活着）。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.3
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False
time.sleep(0.2)
s.reset_input_buffer()
print("opened")


def pulse(label, dtr_seq, rts_seq, hold=0.15):
    """按序列拨 DTR/RTS，然后读串口。"""
    s.reset_input_buffer()
    for d, r in zip(dtr_seq, rts_seq):
        s.dtr = d
        s.rts = r
        time.sleep(hold)
    s.dtr = False
    s.rts = False
    t = time.time() + 2.5
    buf = b""
    while time.time() < t:
        c = s.read(4096)
        if c:
            buf += c
    tag = "DTR=%s RTS=%s" % ("".join("1" if x else "0" for x in dtr_seq),
                             "".join("1" if x else "0" for x in rts_seq))
    if buf:
        print("[+] %-28s -> %d bytes" % (tag, len(buf)))
        print("    " + buf[:400].decode("utf-8", "replace").replace("\r\n", " | "))
    else:
        print("[-] %-28s -> 无输出" % tag)
    return buf


print("\n=== 试探各种复位脉冲 ===")
pulse("dtr脉冲", [True, False], [False, False], 0.2)
pulse("rts脉冲", [False, False], [True, False], 0.2)
pulse("dtr+rts脉冲", [True, False], [True, False], 0.2)
pulse("dtr低rts低", [False], [False], 0.3)
pulse("dtr高rts低", [True], [False], 0.3)
pulse("dtr低rts高", [False], [True], 0.3)
pulse("dtr高rts高", [True], [True], 0.3)

print("\n=== 最后: 直接发 Ctrl-C 序列 ===")
s.reset_input_buffer()
for _ in range(10):
    s.write(b"\r\x03")
    time.sleep(0.08)
time.sleep(0.5)
buf = s.read(8192)
if buf:
    print("[+] 收到 %d bytes: %r" % (len(buf), buf[:400]))
else:
    print("[-] 无响应 —— 板子的 REPL 可能没在跑，或需要按板子上的复位键")

s.close()
