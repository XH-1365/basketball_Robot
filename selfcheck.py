# -*- coding: utf-8 -*-
# ============================================================
#  K210 板上自检 —— 一次性摸清固件 / 文件系统 / KPU API / 模型可用性
#  在 CanMV IDE 里运行，或通过 tools/repl.py 远程执行。
#  全程只读，不改板子任何东西。
# ============================================================

import sensor, image, time, gc, os, sys

try:
    from maix import KPU
except Exception as e:
    print("!! import maix.KPU 失败:", e)

LINE = "=" * 56


def sec(t):
    print("")
    print(LINE)
    print("  " + t)
    print(LINE)


def safe(label, fn):
    try:
        v = fn()
        print("  %-22s: %s" % (label, v))
        return v
    except Exception as e:
        print("  %-22s: <ERR> %s" % (label, e))
        return None


# ------------------------------------------------------------
sec("1. 系统信息")
safe("sys.platform", lambda: sys.platform)
safe("sys.implementation", lambda: sys.implementation)
safe("sys.version", lambda: sys.version)
safe("gc.mem_free", lambda: gc.mem_free())

# ------------------------------------------------------------
sec("2. 文件系统")
for d in ("/", "/sd", "/flash", "/sd/KPU", "/sd/KPU/head_body_detect",
          "/sd/models", "/sd/examples"):
    safe("listdir " + d, (lambda p=d: os.listdir(p)))

# ------------------------------------------------------------
sec("3. 摄像头")
try:
    sensor.reset()
    print("  sensor.reset          : OK")
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.skip_frames(time=800)
    img = sensor.snapshot()
    print("  snapshot              : OK  %dx%d fmt=%s" % (img.width(), img.height(), img.format()))
    print("  sensor id (0=OV,1=GC) : %s" % (sensor.get_id() if hasattr(sensor, "get_id") else "n/a"))
    del img
except Exception as e:
    print("  sensor                : <ERR> %s" % e)

# ------------------------------------------------------------
sec("4. KPU / 显示 API")
try:
    _k = KPU()
    print("  hasattr KPU.Yolo2     : %s" % hasattr(_k, "Yolo2"))
    print("  -> 固件 API 版本      : %s" % ("新版 load()/Yolo2()" if hasattr(_k, "Yolo2") else "旧版 load_kmodel()/init_yolo2()"))
    print("  hasattr load_kmodel   : %s" % hasattr(_k, "load_kmodel"))
    print("  hasattr init_yolo2    : %s" % hasattr(_k, "init_yolo2"))
    _k.deinit()
    del _k
    gc.collect()
except Exception as e:
    print("  KPU                   : <ERR> %s" % e)

try:
    import lcd
    print("  import lcd            : OK")
except Exception as e:
    print("  import lcd            : <ERR> %s" % e)


# ------------------------------------------------------------
# 5. 模型能否加载 + 跑通一帧（关键验证）
# ------------------------------------------------------------
ANCHOR_BODY = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
               0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
               2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

CANDIDATES = [
    ("SD /sd/KPU/head_body_detect/uint8_person_detect_v1_old.kmodel",
     "/sd/KPU/head_body_detect/uint8_person_detect_v1_old.kmodel"),
    ("SD /sd/models/person_detect.kmodel", "/sd/models/person_detect.kmodel"),
    ("SD /sd/uint8_person_detect_v1_old.kmodel", "/sd/uint8_person_detect_v1_old.kmodel"),
    ("FLASH 0x300000", 0x300000),
]


def probe_model(desc, target):
    print("")
    print("  --- %s" % desc)
    gc.collect()
    k = KPU()
    try:
        k.load(target)
    except Exception as e:
        print("      load  : <FAIL> %s" % e)
        try:
            k.deinit()
            del k
        except Exception:
            pass
        gc.collect()
        return None

    ok = False
    try:
        if hasattr(k, "Yolo2"):
            y = k.Yolo2()
            y.init(ANCHOR_BODY, 0.7, 0.2)
            im = image.Image(size=(320, 256))
            k.run(im)
            boxes = y.run()
        else:
            k.init_yolo2(ANCHOR_BODY, anchor_num=9, img_w=320, img_h=256,
                         net_w=320, net_h=256, layer_w=10, layer_h=8,
                         threshold=0.7, nms_value=0.2, classes=1)
            im = image.Image(size=(320, 256))
            k.run_with_output(im)
            boxes = k.regionlayer_yolo2()
        n = len(boxes) if boxes else 0
        print("      load  : OK")
        print("      run   : OK  (空图输出 %d 个框，正常应为 0)" % n)
        if boxes:
            print("      first : %s" % (list(boxes[0]),))
        ok = True
        del im
    except Exception as e:
        print("      run   : <FAIL> %s" % e)

    try:
        k.deinit()
        del k
    except Exception:
        pass
    gc.collect()
    print("      free after: %d" % gc.mem_free())
    return ok


sec("5. 人体模型可用性探测")
any_ok = False
for desc, tgt in CANDIDATES:
    if probe_model(desc, tgt):
        any_ok = True

sec("结论")
print("  可用的人体模型来源: %s" % ("有 (见上)" if any_ok else "无 !!"))
print("  自检结束")
