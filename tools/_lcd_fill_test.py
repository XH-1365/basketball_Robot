# -*- coding: utf-8 -*-
# LCD 分层定位测试
#   第 1 层: lcd.fill_rectangle 直接刷屏(完全绕开 image/摄像头)
#   第 2 层: lcd.display(image) 走图像通路
#   同时打印 width/height/backlight 等状态
# 结束时屏上停在白底黑字, 一眼可辨。
import gc
import time

import image
import lcd
import machine

# 关键: main.py 开机武装了 30s 看门狗。不先停掉, 测试结束约 30s 后板子会被复位,
# main.py 重跑, 相机画面立刻盖掉我们摆在屏上的测试图 —— 人就看不到结果了。
try:
    machine.WDT(0, 30000).stop()
    print("[W] 看门狗已停")
except Exception as e:
    print("[W] 停看门狗失败(忽略):", repr(e))


def q(fn, label):
    try:
        v = fn()
        print("  %-12s = %r" % (label, v))
        return v
    except Exception as e:
        print("  %-12s !! %r" % (label, e))
        return None


try:
    lcd.deinit()
    print("[0] lcd.deinit ok")
except Exception as e:
    print("[0] lcd.deinit skip:", repr(e))

gc.collect()
lcd.init()
print("[1] lcd.init ok, gc free=%d" % gc.mem_free())

print("[2] 屏参数:")
q(lcd.width, "width")
q(lcd.height, "height")
q(lcd.type, "type")
q(lcd.freq, "freq")
q(lcd.rotation, "rotation")
q(lcd.direction, "direction")
q(lcd.get_backlight, "backlight")

print("[3] 强制开背光:")
try:
    lcd.set_backlight(1)
    print("  set_backlight(1) ok -> 现在 = %r" % lcd.get_backlight())
except Exception as e:
    print("  set_backlight 失败:", repr(e))

print("[4] 第 1 层: lcd.fill_rectangle 直接刷屏")
for name, col in (("RED", lcd.RED), ("GREEN", lcd.GREEN),
                  ("BLUE", lcd.BLUE), ("WHITE", lcd.WHITE)):
    try:
        # 先试 5 参签名
        lcd.fill_rectangle(0, 0, lcd.width(), lcd.height(), col)
        print("  >>> 屏幕应整片 %s (fill_rectangle 5参)" % name)
    except Exception as e1:
        try:
            lcd.fill_rectangle(0, 0, lcd.width(), lcd.height())
            print("  >>> 屏幕应整片 %s (fill_rectangle 4参, 用当前色)" % name)
        except Exception as e2:
            print("  fill_rectangle 失败: %r / %r" % (e1, e2))
            break
    time.sleep_ms(1200)

print("[5] 第 2 层: lcd.display(image)")
img = image.Image(size=(320, 240))
SEQ = (("A RED", (255, 0, 0), (255, 255, 255)),
       ("B GREEN", (0, 255, 0), (0, 0, 0)),
       ("C BLUE", (0, 0, 255), (255, 255, 255)),
       ("D WHITE", (255, 255, 255), (0, 0, 0)))
for name, fill, fg in SEQ:
    img.draw_rectangle(0, 0, 320, 240, color=fill, fill=True)
    img.draw_string(30, 100, "LCD " + name, color=fg, scale=3.0)
    lcd.display(img)
    print("  >>> 屏幕应是 %s   (缓冲像素(2,2)=%r)"
          % (name, img.get_pixel(2, 2)))
    time.sleep_ms(1200)

try:
    img.save("/sd/_lcdtest.jpg")
    print("[6] 已存 /sd/_lcdtest.jpg 供 PC 侧核对缓冲内容")
except Exception as e:
    print("[6] 存图失败:", repr(e))

# 最后停在白底黑字, 便于肉眼确认
img.draw_rectangle(0, 0, 320, 240, color=(255, 255, 255), fill=True)
img.draw_string(20, 100, "LCD OK", color=(0, 0, 0), scale=3.0)
lcd.display(img)
print("LCDFILLDONE gc free=%d" % gc.mem_free())
