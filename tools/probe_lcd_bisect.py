# -*- coding: utf-8 -*-
# ============================================================
#  二分探针: 到底是谁把图像下半幅弄成灰色的?
#  一次上板, 存 4 张, 逐张对比:
#    A_纯拍.jpg   snapshot 后立刻存, 什么都不画
#    B_画一行.jpg 画 1 行字(y=200, 在下半幅)
#    C_画多行.jpg 画 6 行带描边的字(含 y=214)
#    D_画框.jpg   再加 draw_rectangle 整幅边框
#  哪一张出现灰带, 就是谁干的。
# ============================================================
import gc
import os
import time
import ubinascii

import lcd
import sensor

JPEG_Q = 90
CHUNK = 512


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
        print("内存盘 %dK OK" % kb)
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


def outline(img, x, y, s, color, scale):
    img.draw_string(x + 1, y, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x - 1, y, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y + 1, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y - 1, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y, s, color=color, scale=scale)


def save_and_send(name, img):
    p = "%s/%s" % (RAMDIR, name)
    img.save(p, quality=JPEG_Q)
    sz = os.stat(p)[6]
    print("SHOT n=0 name=%s size=%d" % (name, sz))
    print("ITEM %s %d %d" % (name, sz, (sz + CHUNK - 1) // CHUNK))
    f = open(p, "rb")
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


# ---- A: 纯拍 ----
img = sensor.snapshot()
time.sleep_ms(100)
img = sensor.snapshot()
save_and_send("A_pure.jpg", img)
lcd.display(img)
print("A 完成 gc_free=%d" % gc.mem_free())

# ---- B: 画一行(下半幅) ----
img = sensor.snapshot()
outline(img, 6, 200, "B_ONE_LINE", (255, 255, 0), 1.5)
save_and_send("B_one.jpg", img)
lcd.display(img)
print("B 完成 gc_free=%d" % gc.mem_free())

# ---- C: 画多行 ----
img = sensor.snapshot()
outline(img, 6, 6, "C_MUL", (0, 255, 255), 1.5)
outline(img, 6, 30, "C_MUL", (255, 255, 0), 1.5)
outline(img, 6, 54, "C_MUL", (0, 255, 0), 1.5)
outline(img, 6, 78, "C_MUL", (255, 0, 255), 1.5)
outline(img, 6, 102, "C_MUL", (255, 160, 0), 1.5)
outline(img, 6, 214, "C_BOTTOM", (255, 255, 0), 1.5)
save_and_send("C_mul.jpg", img)
lcd.display(img)
print("C 完成 gc_free=%d" % gc.mem_free())

# ---- D: 再加整幅边框 ----
img = sensor.snapshot()
outline(img, 6, 6, "D_RECT", (255, 255, 0), 1.5)
img.draw_rectangle(2, 2, 316, 236, color=(255, 255, 0))
save_and_send("D_rect.jpg", img)
lcd.display(img)
print("D 完成 gc_free=%d" % gc.mem_free())

print("BISECTDONE")
