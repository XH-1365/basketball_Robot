# -*- coding: utf-8 -*-
# ============================================================
#  LCD 文字渲染专项探针
#
#  背景: 用户反馈"字体没有显示"。不能靠猜, 要拿证据。
#  办法: 把画好字的那一帧【存进内存盘 + 按同一套协议回传】,
#        PC 端取回来直接看图 —— 图上有什么字、什么颜色、什么大小,
#        一目了然。因为 lcd.display() 显示的就是同一个 img 缓冲区,
#        所以"回传的图"= "屏幕上的内容"。
#
#  测的内容:
#    * 6 种鲜艳色 各画一行(带黑色描边), 看哪些颜色能出
#    * 4 种 scale (1.0 / 1.5 / 2.0 / 3.0) 各画一行, 看哪些倍率能出
#    * draw_string 的返回值(True/False)也打印出来 —— 对象级证据
#
#  全程只用 RAM, 不碰 flash, 不碰 SPI1。
# ============================================================
import gc
import os
import time
import ubinascii

import lcd
import sensor

JPEG_Q = 90
CHUNK = 512

# ---------- 内存盘(必须只写不删) ----------
class RAMFlashDev(object):
    def __init__(self, size):
        self.fs_size = size
        self.fs_data = bytearray(size)
        self.erase_block = 32 * 1024
        self.log_block_size = 64 * 1024
        self.log_page_size = 4 * 1024

    def read(self, buf, size, addr):
        for i in range(len(buf)):
            buf[i] = self.fs_data[addr + i]

    def write(self, buf, size, addr):
        for i in range(len(buf)):
            self.fs_data[addr + i] = buf[i]

    def erase(self, size, addr):
        for i in range(size):
            self.fs_data[addr + i] = 0xff


RAMDIR = None
for kb in (512, 256):
    try:
        blk = RAMFlashDev(kb * 1024)
        vfs = os.VfsSpiffs(blk)
        try:
            vfs.mkfs(vfs)
        except Exception:
            pass
        os.mount(vfs, "/ramdisk")
        os.listdir("/ramdisk")
        RAMDIR = "/ramdisk"
        print("内存盘 %dK OK gc_free=%d" % (kb, gc.mem_free()))
        break
    except Exception as e:
        print("内存盘 %dK 失败 %r" % (kb, e))

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
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)
print("摄像头就绪")


def say(img, x, y, s, color, scale):
    """带黑描边地画字, 并回报返回值。"""
    ok = False
    try:
        img.draw_string(x + 1, y, s, color=(0, 0, 0), scale=scale)
        img.draw_string(x - 1, y, s, color=(0, 0, 0), scale=scale)
        img.draw_string(x, y + 1, s, color=(0, 0, 0), scale=scale)
        img.draw_string(x, y - 1, s, color=(0, 0, 0), scale=scale)
        ok = img.draw_string(x, y, s, color=color, scale=scale)
    except Exception as e:
        print("  draw_string 异常 %r" % (e,))
        return False
    print("  draw_string(%s, color=%s, scale=%s) -> %s"
          % (s, color, scale, ok))
    return ok


img = sensor.snapshot()
print("-- 开始画 --")
print("[颜色 6 行, scale=1.5]")
say(img, 6, 6, "CYAN", (0, 255, 255), 1.5)
say(img, 6, 30, "YELLOW", (255, 255, 0), 1.5)
say(img, 6, 54, "GREEN", (0, 255, 0), 1.5)
say(img, 6, 78, "MAGENTA", (255, 0, 255), 1.5)
say(img, 6, 102, "ORANGE", (255, 160, 0), 1.5)
say(img, 6, 126, "RED", (255, 40, 40), 1.5)
print("[倍率 4 行, 亮黄]")
say(img, 6, 150, "s1.0", (255, 255, 0), 1.0)
say(img, 90, 150, "s1.5", (255, 255, 0), 1.5)
say(img, 180, 150, "s2.0", (255, 255, 0), 2.0)
say(img, 260, 150, "s3", (255, 255, 0), 3.0)
print("[白色/黑色对照 + 默认色]")
say(img, 6, 186, "WHITE", (255, 255, 255), 1.5)
say(img, 120, 186, "BLACK", (0, 0, 0), 1.5)
img.draw_rectangle(2, 2, 316, 236, color=(255, 255, 0))
img.draw_string(6, 214, "LCD TEXT TEST", color=(0, 255, 255), scale=1.5)

print("先存盘(必须在 lcd.display 之前!), 再显示 ...")
name = "lcdtest.jpg"
path = "%s/%s" % (RAMDIR, name)
try:
    img.save(path, quality=JPEG_Q)
except Exception as e:
    print("save 失败 %r" % (e,))
    path = None
lcd.display(img)

if path:
    try:
        sz = os.stat(path)[6]
        print("SHOT n=0 name=%s size=%d" % (name, sz))
        print("ITEM %s %d %d" % (name, sz, (sz + CHUNK - 1) // CHUNK))
        f = open(path, "rb")
        i = 0
        while True:
            d = f.read(CHUNK)
            if not d:
                break
            print("B %s %d %d %d %s#"
                  % (name, i, len(d), sum(d) & 0xFFFF,
                     ubinascii.b2a_base64(d).decode().strip()))
            i += 1
        f.close()
        print("E %s %d" % (name, i))
    except Exception as e:
        print("回传失败 %r" % (e,))

time.sleep_ms(3000)
print("LCDTEXTDONE gc_free=%d" % gc.mem_free())
