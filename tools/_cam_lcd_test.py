# -*- coding: utf-8 -*-
# 摄像头 -> LCD 通路复现测试
# 完全照抄 body_detect.py 的初始化顺序:
#     lcd.deinit() -> sensor.run(0) -> lcd.init() -> sensor.reset()
#     -> set_pixformat(RGB565) -> set_framesize(QVGA) -> skip_frames
# 唯一去掉的是 KPU 模型加载, 用来把"模型/堆"和"sensor->lcd"两类原因分开。
# 跑完不重启, 屏幕停在最后一帧, 便于肉眼确认。
import gc
import time

import image
import lcd
import machine
import sensor

try:
    machine.WDT(0, 30000).stop()
    print("[W] 看门狗已停")
except Exception as e:
    print("[W] 停看门狗失败(忽略):", repr(e))

N_FRAME = 120            # 显示多少帧后停下(约 20s), 之后画面留在屏上

# ---- 照抄 body_detect 的顺序 ----
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
print("[3] 此时 gc free=%d" % gc.mem_free())

lcd.init()
print("[4] lcd.init ok")

sensor.reset()
print("[5] sensor.reset ok")
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)
print("[6] 画面 %dx%d  gc free=%d"
      % (sensor.width(), sensor.height(), gc.mem_free()))

clock = time.clock()
n = 0
saved = False
t0 = time.ticks_ms()
while n < N_FRAME:
    clock.tick()
    img = sensor.snapshot()
    img.draw_string(2, 2, "CAM %d  %2.1ffps" % (n, clock.fps()),
                    color=(255, 255, 0), scale=2.0)
    img.draw_rectangle(0, 0, 320, 240, color=(0, 255, 0), thickness=2)
    lcd.display(img)
    n += 1
    if n == 3 and not saved:
        # 存一张原始帧回来核对: 如果这张有内容而屏上没内容, 那就是显示侧的问题
        try:
            img.save("/sd/_camtest.jpg")
            print("[7] 已存 /sd/_camtest.jpg")
        except Exception as e:
            print("[7] 存图失败:", repr(e))
        saved = True

el = time.ticks_diff(time.ticks_ms(), t0) / 1000.0
print("[8] 显示 %d 帧用了 %.1fs, 平均 %.1f fps" % (n, el, n / el))
print("CAMTESTDONE gc free=%d" % gc.mem_free())
