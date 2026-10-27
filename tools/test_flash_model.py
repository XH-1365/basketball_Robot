# -*- coding: utf-8 -*-
"""测试: 固件 flash 地址里是否已经烧了人体模型（只读，不写 flash）。"""
import gc

import image
from maix import KPU

ADDR = 0x300000
SIZE = 1463728

ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

gc.collect()
print("mem_free start:", gc.mem_free())

k = KPU()
loaded = False

for desc, args in (("load_kmodel(addr, size)", (ADDR, SIZE)),
                   ("load_kmodel(addr)", (ADDR,))):
    try:
        print("尝试 %s ..." % desc)
        k.load_kmodel(*args)
        print("  -> OK")
        loaded = True
        break
    except Exception as e:
        print("  -> <FAIL> %r" % (e,))

if not loaded:
    try:
        k.deinit()
    except Exception:
        pass
    gc.collect()
    print("RESULT: flash 这段没有可加载的模型")
else:
    try:
        k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=256,
                     net_w=320, net_h=256, layer_w=10, layer_h=8,
                     threshold=0.7, nms_value=0.2, classes=1)
        print("init_yolo2: OK")
        im = image.Image(size=(320, 256))
        k.run_with_output(im)
        boxes = k.regionlayer_yolo2()
        n = len(boxes) if boxes else 0
        print("run: OK, 全黑图输出 %d 个框 (正常应为 0)" % n)
        if boxes:
            print("first:", list(boxes[0]))
            print("RESULT: 可疑 —— 黑图有输出，段内容不是该模型")
        else:
            print("RESULT: 可用 —— flash 0x%X 有正常的人体模型" % ADDR)
        del im
    except Exception as e:
        print("run: <FAIL> %r" % (e,))
    try:
        k.deinit()
        del k
    except Exception:
        pass

gc.collect()
print("mem_free end:", gc.mem_free())
