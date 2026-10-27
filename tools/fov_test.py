# -*- coding: utf-8 -*-
# 决定性实验: 同一场景分别存 QVGA 和 QQVGA 各一张，
# 用来判断 QQVGA 是"整幅缩小"还是"中心裁剪"——这决定像素比例怎么换算。
import gc
import machine
import time

import image
import lcd
import sensor

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

for name, fs, path in (("QVGA", sensor.QVGA, "/flash/cap_fov_qvga.jpg"),
                       ("QQVGA", sensor.QQVGA, "/flash/cap_fov_qqvga.jpg")):
    sensor.set_framesize(fs)
    sensor.skip_frames(time=2000)
    img = sensor.snapshot()
    print("SHOT %s %dx%d -> %s" % (name, sensor.width(), sensor.height(), path))
    img.save(path, quality=85)
    lcd.display(img)
    del img
    gc.collect()

print("FOVTEST DONE")
