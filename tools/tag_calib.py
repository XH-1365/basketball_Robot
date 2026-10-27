# -*- coding: utf-8 -*-
# AprilTag 标定采样：读 tag 在画面里的像素尺寸 + pose，用来反算焦距
# 前置: 关掉自动增益/白平衡（否则 tag 阈值不稳）
import gc
import machine
import time

import image
import lcd
import sensor

TAG_MM = 90.0      # tag 黑框外沿边长 (mm)
DIST_MM = 500.0    # 实测距离 (mm)
SECS = 40
# QQVGA(160x120) 下焦距是 QVGA 的一半
FX0 = 138.5
FY0 = 138.5

# 保险: 如果前面 main.py 已经把看门狗武装上了，先关掉，别让它中途复位
try:
    _w = machine.WDT(0, 60000)
    _w.stop()
    print("[prep] WDT 已关闭")
except Exception as e:
    print("[prep] WDT 关闭失败:", repr(e))

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
sensor.set_framesize(sensor.QQVGA)   # find_apriltags 要求 < 64K 像素
sensor.skip_frames(time=2500)        # 顺序关键: 先让自动增益/曝光收敛
sensor.set_auto_gain(False)          # 再把已收敛的增益冻住(否则画面全黑)
sensor.set_auto_whitebal(False)
try:
    print("GAIN gain_db=%.1f exp_us=%d" % (sensor.get_gain_db(),
                                           sensor.get_exposure_us()))
except Exception as e:
    print("GAIN 读取失败:", repr(e))

print("TAGCAL tag=%dmm dist=%dmm fx0=%.1f" % (int(TAG_MM), int(DIST_MM), FX0))

shown = False
t0 = time.ticks_ms()
n = 0
found = 0
while time.ticks_diff(time.ticks_ms(), t0) < SECS * 1000:
    img = sensor.snapshot()
    n += 1
    tags = img.find_apriltags(fx=FX0, fy=FY0,
                              cx=img.width() // 2, cy=img.height() // 2)
    if tags and not shown:
        print("TAGATTR", [x for x in dir(tags[0]) if not x.startswith("_")])
        shown = True
    for t in tags:
        found += 1
        try:
            r = t.rect()
        except Exception:
            r = (t.x(), t.y(), t.w(), t.h())
        img.draw_rectangle(r, color=(255, 0, 0))
        img.draw_cross(t.cx(), t.cy(), color=(0, 255, 0), size=4)
        try:
            fam = t.family()
        except Exception:
            fam = -1
        try:
            z = t.z_translation()
            x = t.x_translation()
            rot = t.rotation()
        except Exception as e:
            z = x = rot = 0.0
        print("TAG n=%d id=%d fam=%d rect=%d,%d,%d,%d w=%d h=%d cx=%d cy=%d "
              "rot=%.3f z=%.5f x=%.5f"
              % (n, t.id(), fam, r[0], r[1], r[2], r[3], r[2], r[3],
                 t.cx(), t.cy(), rot, z, x))
    img.draw_string(0, 0, "tags=%d" % len(tags), color=(255, 0, 0), scale=2.0)
    if n % 30 == 0:
        print("HEART n=%d tags=%d" % (n, len(tags)))
    lcd.display(img)
    gc.collect()

print("TAGDONE frames=%d detections=%d" % (n, found))
