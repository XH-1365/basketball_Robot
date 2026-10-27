# -*- coding: utf-8 -*-
# 验证 /flash/head_v1.kmodel（人头模型）: 加载 + 静态图检测
import gc
import os

import image
from maix import KPU

MODEL = "/flash/head_v1.kmodel"
ANCHOR = (0.1074, 0.1458, 0.1367, 0.2137, 0.1758, 0.2824,
          0.2441, 0.3333, 0.2188, 0.4167, 0.2969, 0.5000,
          0.4102, 0.6667, 0.6094, 0.9722, 1.2364, 1.6915)

JOBS = [("/flash/test785.jpg", "/flash/outhead785.jpg")]

try:
    import lcd
    lcd.deinit()
except Exception:
    pass
try:
    import sensor
    sensor.run(0)
except Exception:
    pass
gc.collect()

print("size:", os.stat(MODEL)[6])
k = KPU()
k.load_kmodel(MODEL)
print("head model load OK")
k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
             net_w=320, net_h=256, layer_w=10, layer_h=8,
             threshold=0.6, nms_value=0.2, classes=1)

for src, dst in JOBS:
    img = image.Image(src)
    if img.width() == 0:
        print("read fail:", src)
        continue
    od = image.Image(size=(320, 256))
    od.draw_image(img, 0, 0)
    od.pix_to_ai()
    k.run_with_output(od)
    boxes = k.regionlayer_yolo2()
    n = len(boxes) if boxes else 0
    print("%s -> %d head(s)" % (src, n))
    for b in boxes:
        print("   x%d y%d w%d h%d prob=%.2f" % (b[0], b[1], b[2], b[3], b[5]))
        img.draw_rectangle(b[0], b[1], b[2], b[3], color=(0, 255, 0), thickness=2)
        ly = b[1] - 12 if b[1] > 14 else b[1] + 2
        img.draw_string(b[0], ly, "head %.0f%%" % (b[5] * 100),
                        color=(0, 255, 0), scale=1.0)
    img.save(dst, quality=90)
    print("   saved", dst, os.stat(dst)[6])
    del od, img
    gc.collect()

k.deinit()
gc.collect()
print("mem_free:", gc.mem_free())
print("DONE")
