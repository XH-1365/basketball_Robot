# -*- coding: utf-8 -*-
# 复现 body_detect 的完整顺序, 唯一不去掉的就是 KPU 模型:
#     停看门狗 -> lcd.deinit() -> sensor.run(0) -> 加载 1.4MB 模型
#     -> lcd.init() -> sensor.reset() -> 显示摄像头帧
# 如果这一步屏上没画面而前面 _cam_lcd_test 有, 那就是模型把系统堆吃光后
# lcd.init()/lcd.display() 出了问题 —— 这正是要抓的根因。
import gc
import time

import lcd
import machine
import sensor
from maix import KPU

try:
    machine.WDT(0, 30000).stop()
    print("[W] 看门狗已停")
except Exception as e:
    print("[W] 停看门狗失败(忽略):", repr(e))

N_FRAME = 120

try:
    lcd.deinit()
    print("[1] lcd.deinit ok")
except Exception as e:
    print("[1] lcd.deinit skip:", repr(e))
try:
    sensor.run(0)
    print("[2] sensor.run(0) ok")
except Exception as e:
    print("[2] sensor.run(0) skip:", repr(e))
gc.collect()
print("[3] 加载模型前 gc free=%d" % gc.mem_free())

kpu = KPU()
try:
    kpu.load_kmodel("/sd/person_v1.kmodel")
    print("[4] 模型加载成功")
except Exception as e:
    print("[4] 模型加载失败:", repr(e))
    raise
gc.collect()
print("[5] 加载模型后 gc free=%d" % gc.mem_free())

lcd.init()
print("[6] lcd.init ok")

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)
print("[7] 画面 %dx%d  gc free=%d"
      % (sensor.width(), sensor.height(), gc.mem_free()))

clock = time.clock()
n = 0
while n < N_FRAME:
    clock.tick()
    img = sensor.snapshot()
    img.draw_string(2, 2, "MODEL+CAM %d  %2.1ffps" % (n, clock.fps()),
                    color=(255, 255, 0), scale=2.0)
    img.draw_rectangle(0, 0, 320, 240, color=(255, 0, 255), thickness=2)
    lcd.display(img)
    n += 1

print("[8] 显示 %d 帧完成, %.1f fps" % (n, clock.fps()))
print("MODELCAMDONE gc free=%d" % gc.mem_free())
