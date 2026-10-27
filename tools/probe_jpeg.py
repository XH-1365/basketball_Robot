# -*- coding: utf-8 -*-
"""
探测: 能不能【不写文件】直接拿到 JPEG 字节流。
如果有 img.compress(), 就能"拍照 -> 内存里编码 -> 串口吐 base64 给 PC",
完全不碰 /flash, 绕开这块板子最脆弱的一环。

只探测, 不写任何文件。
"""
import gc
import time

import image
import lcd
import sensor

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

names = [x for x in dir(image.Image) if not x.startswith("_")]
hits = [x for x in names if any(k in x.lower()
        for k in ("compr", "save", "jpeg", "jpg", "encod", "byte", "to_"))]
print("IMGMETHODS_HIT", hits)
print("IMGMETHODS_N", len(names))

img = sensor.snapshot()
print("SNAP %dx%d" % (img.width(), img.height()))

import ubinascii

ok = False
# 1) compress(quality=..)
try:
    b = img.compress(quality=90)
    n = len(b)
    head = ubinascii.hexlify(bytes(b[:3]))
    print("COMPRESS quality=90 OK len=%d head=%s" % (n, head))
    ok = True
except Exception as e:
    print("COMPRESS quality=90 FAIL", repr(e))

# 2) compress() 无参
if not ok:
    try:
        b = img.compress()
        print("COMPRESS noargs OK len=%d" % len(b))
        ok = True
    except Exception as e:
        print("COMPRESS noargs FAIL", repr(e))

# 3) to_bytes / save 到内存?
for m in ("to_bytes", "jpeg_encode", "encode"):
    if hasattr(img, m):
        try:
            r = getattr(img, m)()
            print("M_%s OK type=%s len=%s" % (m, type(r), len(r) if r else "?"))
        except Exception as e:
            print("M_%s FAIL" % m, repr(e))

print("JPEGPROBE DONE ok=%s" % ok)
