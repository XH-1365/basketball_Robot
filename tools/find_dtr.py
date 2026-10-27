# -*- coding: utf-8 -*-
"""DTR/RTS 四组合 × 耐心等待，找哪种电平能让板子回 >>> 提示符。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"

COMBOS = [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
]

for dtr, rts in COMBOS:
    print("=" * 56)
    print("组合 DTR=%s RTS=%s" % (dtr, rts))
    try:
        s = serial.Serial()
        s.port = PORT
        s.baudrate = 115200
        s.timeout = 0.3
        s.dtr = dtr
        s.rts = rts
        s.open()
        s.dtr = dtr
        s.rts = rts
    except Exception as e:
        print("  打开失败:", e)
        continue

    # 耐心等启动
    time.sleep(3.0)
    boot = s.read(16384)
    print("  启动输出 %d bytes: %r" % (len(boot), boot[:120]))

    s.reset_input_buffer()
    got = b""
    for i in range(8):
        s.write(b"\r\x03")
        time.sleep(0.3)
        d = s.read(4096)
        if d:
            got += d
            if got.rstrip().endswith(b">>>"):
                break
    if got:
        print("  响应 %d bytes: %r" % (len(got), got[-200:]))
    else:
        print("  无响应")

    if got.rstrip().endswith(b">>>"):
        print("  >>> 这个组合可用 <<<")
        s.write(b"\r\nprint('HELLO_FROM_K210')\r\n")
        time.sleep(0.8)
        print("  验证:", s.read(4096))
    s.close()
    print("")
