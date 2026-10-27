# -*- coding: utf-8 -*-
"""回归确认: 看新 main.py 内容 + 验证人体模型仍可用。"""
import gc
import os

import image
from maix import KPU

PATH = "/flash/person_v1.kmodel"
ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

print("=== /flash/main.py 内容 ===")
try:
    n = os.stat("/flash/main.py")[6]
    print("(%d bytes)" % n)
    f = open("/flash/main.py", "r")
    print(f.read())
    f.close()
except Exception as e:
    print("<ERR>", e)
print("=== end main.py ===")
print("")

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

print("mem:", gc.mem_free())
k = KPU()
k.load_kmodel(PATH)
print("model load OK")
k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
             net_w=320, net_h=256, layer_w=10, layer_h=8,
             threshold=0.7, nms_value=0.2, classes=1)
print("yolo2 OK")

# 静态图端到端
img = image.Image("/flash/test785.jpg")
print("test785: %dx%d" % (img.width(), img.height()))
od = image.Image(size=(320, 256))
od.draw_image(img, 0, 0)
od.pix_to_ai()
k.run_with_output(od)
boxes = k.regionlayer_yolo2()
n = len(boxes) if boxes else 0
print("检测到 %d 人" % n)
for b in boxes:
    print("   x%d y%d w%d h%d prob=%.2f" % (b[0], b[1], b[2], b[3], b[5]))
del od, img
k.deinit()
del k
gc.collect()
print("REGRESSION PASS" if n >= 1 else "REGRESSION: 没检出人，需检查")
