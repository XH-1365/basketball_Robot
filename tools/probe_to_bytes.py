# -*- coding: utf-8 -*-
"""
验证 img.to_bytes() 拿到的是不是合法 JPEG 字节流。
如果是, 就能"拍照 -> 内存编码 -> 串口吐 base64 给 PC", 完全不写 /flash。

本脚本不写任何文件, 只往串口打 base64, 由 PC 端解析落盘。
"""
import gc

import lcd
import sensor
import ubinascii

try:
    import machine
    machine.WDT(0, 60000).stop()
    print("[prep] WDT 已关闭")
except Exception as e:
    print("[prep] wdt:", repr(e))

try:
    lcd.deinit()
except Exception:
    pass
try:
    sensor.run(0)
except Exception:
    pass
gc.collect()

lcd.init()
sensor.reset()
sensor.set_hmirror(0)
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

img = sensor.snapshot()
lcd.display(img)

b = img.to_bytes()
n = len(b)
hx = ubinascii.hexlify(bytes(b[:4])).decode()
tx = ubinascii.hexlify(bytes(b[-2:])).decode()
print("TOB len=%d head=%s tail=%s raw_expect=%d" % (n, hx, tx, 320 * 240 * 2))

# 猜: 如果 head 是 ffd8ff 且 tail 是 ffd9, 那就是 JPEG
print("TOB_IS_JPEG %s" % ("YES" if (hx[:4] == "ffd8" and tx == "ffd9") else "NO"))

s = ubinascii.b2a_base64(b).decode().strip()
print("B64LEN %d" % len(s))
for i in range(0, len(s), 512):
    print("B64 " + s[i:i + 512])
print("B64END")
print("PROBE2 DONE")
