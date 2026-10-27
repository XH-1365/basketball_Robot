# -*- coding: utf-8 -*-
"""
被动抓开机日志: 只做一次 DTR 复位脉冲, 然后【不发 Ctrl-C】, 让 main.py 自己跑。
这样才能看到 LCD 到底是"根本没跑"还是"跑了但报错"。

用法: python tools/_boot_capture.py [COM16] [秒数]
"""
import sys
import time

import serial


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM16"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0

    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.1
    s.dtr = False
    s.rts = False
    s.open()
    s.dtr = False
    s.rts = False

    s.reset_input_buffer()
    print(">>> 复位脉冲 (DTR 高 0.3s) ...")
    s.dtr = True
    time.sleep(0.3)
    s.dtr = False

    t0 = time.time()
    buf = b""
    while time.time() - t0 < secs:
        d = s.read(4096)
        if d:
            buf += d
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
    s.close()
    print("\n\n>>> 抓到 %d 字节, 耗时 %.1fs" % (len(buf), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
