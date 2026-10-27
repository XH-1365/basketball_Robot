# -*- coding: utf-8 -*-
# 在 K210 上: 从 /flash 读测试图 -> 人体检测 -> 画框 -> 存结果图
import gc
import os

import image
from maix import KPU

# main.py 开机跑过 lcd.init()/sensor.reset()，framebuffer 占着系统堆，
# 会挤掉 KPU 1.4MB 的模型缓冲。先释放。
try:
    import lcd
    lcd.deinit()
    print("lcd.deinit OK")
except Exception as e:
    print("lcd.deinit skip:", e)
try:
    import sensor
    sensor.run(0)
except Exception:
    pass
gc.collect()

MODEL = "/flash/person_v1.kmodel"
ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

JOBS = [
    ("/flash/test2153.jpg", "/flash/out2153.jpg"),
]


def run_one(kpu, src, dst):
    print(">>> %s" % src)
    try:
        img = image.Image(src)
    except Exception as e:
        print("   读图失败:", repr(e))
        return None
    if img.width() == 0 or img.height() == 0:
        print("   读图得到空图，跳过")
        del img
        return None
    print("   size: %dx%d fmt=%s" % (img.width(), img.height(), img.format()))

    # 模型输入 320x256，把 320x240 的图贴到顶部
    od = image.Image(size=(320, 256))
    od.draw_image(img, 0, 0)
    od.pix_to_ai()

    kpu.run_with_output(od)
    boxes = kpu.regionlayer_yolo2()
    n = len(boxes) if boxes else 0
    print("   检测到 %d 个人" % n)
    for b in boxes:
        print("     box x=%d y=%d w=%d h=%d prob=%.2f" % (b[0], b[1], b[2], b[3], b[5]))
        img.draw_rectangle(b[0], b[1], b[2], b[3], color=(255, 0, 0), thickness=2)
        ly = b[1] - 12 if b[1] > 14 else b[1] + 2
        img.draw_string(b[0], ly, "person %.0f%%" % (b[5] * 100),
                        color=(255, 0, 0), scale=1.0)
    del od

    try:
        img.save(dst, quality=90)
        print("   已保存:", dst, os.stat(dst)[6], "bytes")
    except Exception as e:
        print("   保存失败:", repr(e))
    del img
    gc.collect()
    return n


gc.collect()
print("mem_free:", gc.mem_free())
k = KPU()
k.load_kmodel(MODEL)
print("model loaded")
k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
             net_w=320, net_h=256, layer_w=10, layer_h=8,
             threshold=0.7, nms_value=0.2, classes=1)
print("yolo2 inited")
print("")

results = {}
for src, dst in JOBS:
    results[src] = run_one(k, src, dst)
    print("")

k.deinit()
del k
gc.collect()
print("RESULT:", results)
print("DONE")
