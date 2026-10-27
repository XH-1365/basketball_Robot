# -*- coding: utf-8 -*-
"""纯听: 不发任何字节(不复位、不 Ctrl-C), 看板子现在处于什么状态。

用途: 用户断电重插之后, 想确认 SD 挂没挂上、模型加载没加载。
      这时不能复位 —— 复位会把"刚上电那一次"的状态冲掉, 而且 SD 挂载
      有抽风, 多复位一次反而可能把好的搞坏。
判据:
  · 看到 "DET ..."        -> 模型加载成功, SD 正常
  · 看到 "PREVIEW no_model" -> SD 没挂上, 模型加载失败
用法: python tools/_listen.py [COM16] [秒数]
"""
import sys
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM16"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0

s = serial.Serial()
s.port = port
s.baudrate = 115200
s.timeout = 0.2
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False

print(">>> 纯听 %.0f 秒(不发任何字节) ..." % secs)
t0 = time.time()
buf = b""
while time.time() - t0 < secs:
    d = s.read(4096)
    if d:
        buf += d
        sys.stdout.write(d.decode("utf-8", "replace"))
        sys.stdout.flush()
s.close()

txt = buf.decode("utf-8", "replace")
print("\n" + "-" * 50)
print("收到 %d 字节" % len(buf))
n_det = txt.count("DET ")
n_prev = txt.count("PREVIEW no_model")
print("DET 行 %d 条 / PREVIEW no_model %d 条" % (n_det, n_prev))
if n_det and not n_prev:
    print(">>> 判定: 模型已加载, SD 正常")
elif n_prev:
    print(">>> 判定: SD 没挂上(模型加载失败)")
else:
    print(">>> 判定: 没收到可判定的行 —— 板子可能没在跑 / 串口没对上")
