# -*- coding: utf-8 -*-
# 探清: 缩放 API 名 / JPEG 字节怎么取 / 灰度转换
import gc
import time

import image
import sensor
import ubinascii

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)
img = sensor.snapshot()
print("[P] img %dx%d" % (img.width(), img.height()))

names = [a for a in dir(img) if not a.startswith("_")]
print("[P] 相关方法: %s"
      % [a for a in names if a in ("compress", "to_bytes", "bytearray",
                                   "copy", "resize", "save", "replace",
                                   "to_grayscale", "format", "scale",
                                   "set_pixel", "get_pixel", "draw_image")])
try:
    print("[P] format = %r" % img.format())
except Exception as e:
    print("[P] format 失败: %r" % e)

# --- 缩放: 试各种参数名 ---
for kw in ({"x_scale": 0.5, "y_scale": 0.5},
           {"x_scale": 0.25, "y_scale": 0.25},
           {"scale": 0.5}):
    try:
        t = time.ticks_ms()
        o = img.copy(**kw)
        dt = time.ticks_diff(time.ticks_ms(), t)
        print("[P] copy(%s) -> %dx%d  %d ms"
              % (kw, o.width(), o.height(), dt))
    except Exception as e:
        print("[P] copy(%s) 失败: %r" % (kw, e))

# --- JPEG 字节怎么取 ---
t = time.ticks_ms()
try:
    j = img.compress(quality=40)
    print("[P] compress -> %r  %d ms" % (type(j), time.ticks_diff(time.ticks_ms(), t)))
except Exception as e:
    print("[P] compress 失败: %r" % e)
    j = None

if j is not None:
    for meth in ("bytearray", "to_bytes", "bytes"):
        try:
            if meth == "bytes":
                b = bytes(j)
            else:
                b = getattr(j, meth)()
            print("[P]   %s() -> %d 字节" % (meth, len(b)))
            print("[P]   头两字节 %r (jpg 应是 ffd8)"
                  % ubinascii.hexlify(b[:2]))
        except Exception as e:
            print("[P]   %s() 失败: %r" % (meth, e))

# --- 灰度 ---
try:
    g = img.to_grayscale(copy=True)
    print("[P] to_grayscale ok %dx%d format=%r"
          % (g.width(), g.height(), g.format()))
except Exception as e:
    print("[P] to_grayscale 失败: %r" % e)

print("PROBEDONE gc=%d" % gc.mem_free())
