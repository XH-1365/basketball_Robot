# -*- coding: utf-8 -*-
"""
/ramdisk 内存文件系统能否扛住 JPEG? 换了参数反而更糟(SPIFFS -10028),
说明必须用 demo 原参数。这次认真做对照:

  E1: 文本文件写入/读回   —— 内存 FS 本身可用吗
  E2: 15000 字节二进制写入/读回 —— 二进制大块能写吗 (这是 JPEG 的量级)
  E3: img.save() 存 JPEG  —— 真正要用的路径

只有 E1/E2 都过、E3 不过, 才能断定"是存图这条路径的问题"。
不写 /flash 一个字节。
"""
import gc
import time

import lcd
import sensor

try:
    import machine
    machine.WDT(0, 60000).stop()
    print("[prep] WDT 已关闭")
except Exception as e:
    print("[prep] wdt:", repr(e))

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

import uos


class RAMFlashDev:
    """完全照抄官方 demo_ram_fs.py 的参数和结构。"""
    def __init__(self):
        self.fs_size = 256 * 1024
        self.fs_data = bytearray(256 * 1024)
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


print("--- E: /ramdisk (官方 demo 原参数) ---")
try:
    blk = RAMFlashDev()
    print("E blk ok free=%d" % gc.mem_free())
    vfs = uos.VfsSpiffs(blk)
    try:
        vfs.mkfs(vfs)
    except Exception as e:
        print("E mkfs note", repr(e))
    uos.mount(vfs, "/ramdisk")
    print("E mount ok listdir=%r free=%d" % (uos.listdir("/ramdisk"), gc.mem_free()))
except Exception as e:
    print("E MOUNT FATAL", repr(e))
    print("挂载失败, 下面三段的报错都不可信, 看这一行就够了")

# ---- E1: 文本 ----
try:
    f = open("/ramdisk/t.txt", "w")
    f.write("hello 1234567890")
    f.close()
    f = open("/ramdisk/t.txt", "r")
    s = f.read()
    f.close()
    print("E1 text OK read=%r size=%d" % (s, uos.stat("/ramdisk/t.txt")[6]))
except Exception as e:
    print("E1 text FAIL", repr(e))

# ---- E2: 15000 字节二进制 ----
try:
    blob = bytearray(15000)
    for i in range(len(blob)):
        blob[i] = i & 0xFF
    f = open("/ramdisk/b.bin", "wb")
    f.write(blob)
    f.close()
    n = uos.stat("/ramdisk/b.bin")[6]
    f = open("/ramdisk/b.bin", "rb")
    back = f.read()
    f.close()
    same = (len(back) == 15000 and back[0] == 0 and back[255] == 255
            and back[14999] == (14999 & 0xFF))
    print("E2 bin OK size=%d readlen=%d same=%s" % (n, len(back), same))
except Exception as e:
    print("E2 bin FAIL", repr(e))

# ---- E3: 存 JPEG ----
img = sensor.snapshot()
for q in (90, 60):
    t = time.ticks_ms()
    try:
        img.save("/ramdisk/t%d.jpg" % q, quality=q)
        dt = time.ticks_diff(time.ticks_ms(), t)
        sz = uos.stat("/ramdisk/t%d.jpg" % q)[6]
        print("E3 q=%d save OK %dms size=%d" % (q, dt, sz))
        break
    except Exception as e:
        print("E3 q=%d save FAIL %r" % (q, e))

print("E listdir", uos.listdir("/ramdisk"))
print("PROBE5 DONE free=%d" % gc.mem_free())
