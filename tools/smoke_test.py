# -*- coding: utf-8 -*-
# body_detect.py 的冒烟测试版: 实时摄像头检测 30 帧后自动退出
# 验证: 模型加载 -> 摄像头 -> 实时推理 -> 干净退出
import gc
import os
import time

import image
import lcd
import sensor

from maix import KPU

BODY_MODEL_PATHS = (
    "/flash/person_v1.kmodel",
    "/sd/KPU/head_body_detect/uint8_person_detect_v1_old.kmodel",
)
THRESHOLD = 0.70
NMS = 0.20
HMIRROR = True
FRAMES = 30

ANCHOR_BODY = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
               0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
               2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

try:
    lcd.deinit()
    print("lcd.deinit OK")
except Exception:
    print("lcd.deinit skip")
try:
    sensor.run(0)
except Exception:
    pass
gc.collect()

print("mem before model:", gc.mem_free())
k = KPU()
loaded = False
for p in BODY_MODEL_PATHS:
    try:
        names = os.listdir(p.rsplit("/", 1)[0])
        if p.rsplit("/", 1)[1] not in names:
            continue
    except Exception:
        continue
    try:
        k.load_kmodel(p)
        print("model:", p)
        loaded = True
        break
    except Exception as e:
        print("load fail:", p, e)
if not loaded:
    print("SMOKE FAIL: no model")
    raise SystemExit

k.init_yolo2(ANCHOR_BODY, anchor_num=9, img_w=320, img_h=240,
             net_w=320, net_h=256, layer_w=10, layer_h=8,
             threshold=THRESHOLD, nms_value=NMS, classes=1)
gc.collect()
print("mem after model:", gc.mem_free())

lcd.init()
sensor.reset()
sensor.set_hmirror(1)
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)
clock = time.clock()

od_img = image.Image(size=(320, 256))
counts = []
t0 = time.ticks_ms()

for i in range(FRAMES):
    clock.tick()
    img = sensor.snapshot()
    od_img.draw_image(img, 0, 0)
    od_img.pix_to_ai()
    k.run_with_output(od_img)
    boxes = k.regionlayer_yolo2()
    n = len(boxes) if boxes else 0
    counts.append(n)
    if boxes:
        print("frame %2d: %d box(es)  %s" % (i, n, [list(b) for b in boxes][:3]))
    img.draw_string(0, 0, "%2.1ffps N=%d" % (clock.fps(), n), scale=1.5)
    lcd.display(img)
    gc.collect()

el = time.ticks_diff(time.ticks_ms(), t0) / 1000.0
avg_fps = FRAMES / el if el else 0
k.deinit()
gc.collect()

print("")
print("=== SMOKE RESULT ===")
print("frames   :", FRAMES)
print("wall time: %.1fs  avg fps: %.1f" % (el, avg_fps))
print("detections per frame:", counts)
print("total frames with person: %d" % sum(1 for c in counts if c > 0))
print("SMOKE PASS")
