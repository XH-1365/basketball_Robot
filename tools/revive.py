# -*- coding: utf-8 -*-
"""抢救: 遍历复位脉冲组合 + 长等待，检查板子能否恢复完整启动（出现 logo 或 >>>）。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"

# (名称, [(dtr, rts), ...])  —— 每个元组是一次电平设置
SEQS = [
    ("DTR 高脉冲", [(True, False), (False, False)]),
    ("RTS 高脉冲", [(False, True), (False, False)]),
    ("双高脉冲", [(True, True), (False, False)]),
    ("双低脉冲", [(False, False), (True, True), (False, False)]),
    ("长 DTR 低", [(False, False)], 3.0),
    ("反向双高", [(False, True), (True, False), (False, False)]),
]

for item in SEQS:
    name = item[0]
    seq = item[1]
    hold = item[2] if len(item) > 2 else 0.3
    print("=" * 56)
    print("[%s]" % name)
    try:
        s = serial.Serial()
        s.port = PORT
        s.baudrate = 115200
        s.timeout = 0.2
        s.dtr = False
        s.rts = False
        s.open()
    except Exception as e:
        print("  打开失败:", e)
        continue

    s.reset_input_buffer()
    for d, r in seq:
        s.dtr = d
        s.rts = r
        time.sleep(hold)
    s.dtr = False
    s.rts = False

    t0 = time.time()
    buf = b""
    while time.time() - t0 < 8:
        d = s.read(4096)
        if d:
            buf += d

    txt = buf.decode("utf-8", "replace")
    has_logo = "____" in txt or "|" in txt and "CanMV" in txt
    print("  收到 %d bytes" % len(buf))
    if len(buf) > 300:
        print("  尾部: %r" % txt[-120:])
    ok = ">>>" in txt or "____" in txt
    print("  恢复迹象: %s" % ("有！" if ok else "无"))
    if ok:
        s.reset_input_buffer()
        for _ in range(6):
            s.write(b"\r\x03")
            time.sleep(0.3)
        time.sleep(0.5)
        r = s.read(8192)
        print("  Ctrl-C 响应: %r" % r[-160:])
    s.close()
    print("")

print("=" * 56)
print("若全部无效 -> 需要手动按板上的 RESET 键，或用 kflash 重烧固件")
