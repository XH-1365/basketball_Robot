# -*- coding: utf-8 -*-
"""
找一条"不写 flash 也能拿到 JPEG 字节"的路。两个方案一起测:

  方案 A: sensor.set_pixformat(sensor.JPEG) -> snapshot -> to_bytes()
          (compress() 只对 JPEG 格式的图有效, 所以先切 JPEG 格式)
  方案 B: 纯内存块设备 RAMFlashDev + VfsSpiffs 挂 /ramdisk, 存进去再读出来
          (复用手上已验证能产出合法 JPEG 的 img.save() 路径, 只是不落 flash)

本脚本不写 /flash 一个字节。
"""
import gc
import time

import lcd
import sensor
import ubinascii

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
sensor.set_framesize(sensor.QVGA)


def hx(b, n=4, tail=False):
    try:
        return ubinascii.hexlify(bytes(b[-n:] if tail else b[:n])).decode()
    except Exception as e:
        return "ERR:%r" % (e,)


# ==================== 方案 A: JPEG pixformat ====================
print("--- A: sensor.JPEG ---")
try:
    sensor.set_pixformat(sensor.JPEG)
    try:
        sensor.set_jb_quality(90)
        print("A set_jb_quality(90) OK")
    except Exception as e:
        print("A set_jb_quality FAIL", repr(e))
    sensor.skip_frames(time=1500)
    t = time.ticks_ms()
    img = sensor.snapshot()
    dt = time.ticks_diff(time.ticks_ms(), t)
    print("A snap ok %dx%d %dms" % (img.width(), img.height(), dt))
    b = img.to_bytes()
    print("A to_bytes len=%d head=%s tail=%s" % (len(b), hx(b), hx(b, 2, True)))
    print("A IS_JPEG %s" % ("YES" if hx(b, 2) == "ffd8" and hx(b, 2, True) == "ffd9" else "NO"))
    # 顺便测 compress()
    try:
        c = img.compress()
        print("A compress len=%d head=%s" % (len(c), hx(c, 2)))
    except Exception as e:
        print("A compress FAIL", repr(e))
    try:
        lcd.display(img)
        print("A lcd.display(jpeg) OK")
    except Exception as e:
        print("A lcd.display FAIL", repr(e))
except Exception as e:
    print("A FATAL", repr(e))

# 回到 RGB565
try:
    sensor.set_pixformat(sensor.RGB565)
    sensor.skip_frames(time=1500)
    print("A 已切回 RGB565")
except Exception as e:
    print("A 切回失败", repr(e))

# ==================== 方案 B: 内存 RAM 盘 ====================
print("--- B: /ramdisk ---")
try:
    import uos

    class RAMFlashDev:
        def __init__(self, n=128 * 1024):
            self.fs_size = n
            self.fs_data = bytearray(n)
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

    blk = RAMFlashDev()
    print("B blkdev ok free=%d" % gc.mem_free())
    vfs = uos.VfsSpiffs(blk)
    print("B VfsSpiffs ok")
    try:
        vfs.mkfs(vfs)
        print("B mkfs ok")
    except Exception as e:
        print("B mkfs FAIL(可能有旧内容, 继续)", repr(e))
    uos.mount(vfs, "/ramdisk")
    print("B mount ok ->", uos.listdir("/ramdisk"))

    img2 = sensor.snapshot()
    t = time.ticks_ms()
    try:
        img2.save("/ramdisk/t.jpg", quality=90)
    except Exception:
        img2.save("/ramdisk/t.jpg")
    dt = time.ticks_diff(time.ticks_ms(), t)
    print("B save %dms" % dt)
    sz = uos.stat("/ramdisk/t.jpg")[6]
    print("B stat size=%d" % sz)
    f = open("/ramdisk/t.jpg", "rb")
    raw = f.read()
    f.close()
    print("B read len=%d head=%s tail=%s" % (len(raw), hx(raw), hx(raw, 2, True)))
    print("B IS_JPEG %s" % ("YES" if hx(raw, 2) == "ffd8" and hx(raw, 2, True) == "ffd9" else "NO"))
except Exception as e:
    print("B FATAL", repr(e))

print("PROBE3 DONE free=%d" % gc.mem_free())
