# -*- coding: utf-8 -*-
"""
K210 被动串口采样器 —— 只读、不复位、不发 Ctrl-C、不写 flash。

用途: 板子正在跑 main.py（人体检测）时，抓它串口输出的一段时间样本，
      拿去算标定/看稳定性。全程不打断板子，所以 LCD 画面不会停。

用法:
  python tools/sample.py COM16 45               # 采 45 秒
  python tools/sample.py COM16 45 只留DET行关键字   # 可选: 只回显含该关键字的行

输出每行前面带相对时间戳 [  12.3s]，方便按"第几秒到第几秒"给数据分段。
例如标定时按套路来:
  0~10s 站 1.0m / 10~20s 站 2.0m / 20~30s 站 3.0m
事后按时间戳切段，每段取 h 的中位数即可反算焦距。
"""
import sys
import time

import serial

CTRL_C = b"\x03"


def open_port(port, baud=115200):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.2
    s.dtr = False
    s.rts = False
    s.open()
    s.dtr = False
    s.rts = False
    return s


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    port = sys.argv[1]
    dur = float(sys.argv[2])
    filt = sys.argv[3] if len(sys.argv) > 3 else None

    s = open_port(port)
    # 先清掉打开瞬间的残留，但绝不主动发任何东西
    time.sleep(0.3)
    s.read(65536)

    t0 = time.time()
    buf = b""
    nlines = 0
    ndet = 0
    print("[sample] %s 采样 %.0f 秒, 只读不打扰..." % (port, dur))
    try:
        while time.time() - t0 < dur:
            chunk = s.read(4096)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.rstrip(b"\r")
                if not line:
                    continue
                nlines += 1
                txt = line.decode("utf-8", "replace")
                if filt and filt not in txt:
                    continue
                if txt.startswith("DET ") or "total=" in txt:
                    ndet += 1
                print("[%6.1fs] %s" % (time.time() - t0, txt))
    except KeyboardInterrupt:
        print("[sample] 手动中断")
    finally:
        s.dtr = False
        s.rts = False
        s.close()

    print("[sample] 结束: 共 %d 行, 其中检测行 %d 行" % (nlines, ndet))
    if nlines == 0:
        print("[sample] 一行都没收到 -> 板子不在跑/串口被 IDE 占用/线掉了。"
              "用 tools/peek.py 判断具体状态。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
