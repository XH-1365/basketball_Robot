# -*- coding: utf-8 -*-
"""验证 /flash 里刚上传的人体模型：加载 + 跑一帧，并做字节校验。"""
import gc

import image
from maix import KPU

PATH = "/flash/person_v1.kmodel"
ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

print("--- 文件信息 ---")
import os
st = os.stat(PATH)
print("size :", st[6])

print("")
print("--- 字节校验 (分块 sum, 与本地对比) ---")
f = open(PATH, "rb")
acc = 0
n = 0
while True:
    d = f.read(16384)
    if not d:
        break
    n += len(d)
    for b in d:
        acc = (acc + b) & 0xFFFFFFFF
f.close()
print("bytes:", n)
print("CKSUM:", acc)

print("")
print("--- KPU 加载 ---")
gc.collect()
k = KPU()
try:
    k.load_kmodel(PATH)
    print("load_kmodel : OK")
except Exception as e:
    print("load_kmodel : <FAIL>", repr(e))
    raise SystemExit

try:
    k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
                 net_w=320, net_h=256, layer_w=10, layer_h=8,
                 threshold=0.7, nms_value=0.2, classes=1)
    print("init_yolo2  : OK")
except Exception as e:
    print("init_yolo2  : <FAIL>", repr(e))

try:
    im = image.Image(size=(320, 256))
    im.pix_to_ai()          # 必须！把 RGB565 转成 KPU 要的 r8g8b8 布局
    k.run_with_output(im)
    boxes = k.regionlayer_yolo2()
    nn = len(boxes) if boxes else 0
    print("run         : OK, 黑图输出 %d 框 (期望 0)" % nn)
    if boxes:
        print("  first:", list(boxes[0]))
    del im
except Exception as e:
    print("run         : <FAIL>", repr(e))

try:
    k.deinit()
    del k
except Exception:
    pass
gc.collect()
print("mem_free:", gc.mem_free())
