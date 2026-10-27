# -*- coding: utf-8 -*-
"""K210 串口握手探测：试不同波特率 + DTR/RTS 组合，找到能进 REPL 的方式。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
BAUDS = [115200, 9600, 57600, 230400, 921600]
DTX = [(False, False), (True, True), (True, False), (False, True)]


def probe(baud, dtr, rts, quiet=True):
    try:
        s = serial.Serial()
        s.port = PORT
        s.baudrate = baud
        s.timeout = 0.15
        s.dtr = dtr
        s.rts = rts
        s.open()
    except Exception as e:
        if not quiet:
            print("    open fail: %r" % (e,))
        return None

    s.reset_input_buffer()
    s.reset_output_buffer()
    # 猛发 Ctrl-C 打断可能正在跑的 main.py
    for _ in range(8):
        s.write(b"\r\x03")
        time.sleep(0.06)
    time.sleep(0.4)
    buf = s.read(8192)

    if not buf:
        # 再来一轮 Ctrl-B（退回 friendly REPL）
        s.write(b"\r\x01")     # raw repl
        time.sleep(0.15)
        s.write(b"\r\x02")     # friendly repl
        time.sleep(0.3)
        buf = s.read(8192)

    s.close()
    return buf


def main():
    print("端口 %s —— 开始握手扫描" % PORT)
    for baud in BAUDS:
        for dtr, rts in DTX:
            buf = probe(baud, dtr, rts)
            tag = "baud=%-7d dtr=%-5s rts=%-5s" % (baud, dtr, rts)
            if buf:
                txt = buf[:160].decode("utf-8", "replace").replace("\r", "\\r").replace("\n", "\\n")
                print("  [+] %s -> %d bytes: %s" % (tag, len(buf), txt))
            else:
                print("  [-] %s -> 无响应" % tag)
    print("扫描结束")


if __name__ == "__main__":
    main()
