# -*- coding: utf-8 -*-
"""
继续找"不写 flash 拿 JPEG"的路。三段对照:

  C: 灰度图 + compress() —— 如果灰度能压成 JPEG, 就是最干净的方案
  D1: /ramdisk 写普通文本文件 —— 验证内存文件系统本身是否可用(对照)
  D2: /ramdisk 存 JPEG —— 修正 SPIFFS 参数(log_block_size 应等于 erase_block,
      log_page_size 用 256), 再试

不写 /flash 一个字节。
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
        return "ERR"


# ==================== C: 灰度 + compress ====================
print("--- C: GRAYSCALE + compress ---")
try:
    sensor.set_pixformat(sensor.GRAYSCALE)
    sensor.skip_frames(time=1500)
    g = sensor.snapshot()
    print("C snap %dx%d" % (g.width(), g.height()))
    for how in ("kw", "pos", "noarg"):
        try:
            if how == "kw":
                c = g.compress(quality=90)
            elif how == "pos":
                c = g.compress(90)
            else:
                c = g.compress()
            print("C compress(%s) len=%d head=%s" % (how, len(c), hx(c, 2)))
            try:
                print("C compress(%s) tail=%s" % (how, hx(c, 2, True)))
            except Exception:
                pass
            break
        except Exception as e:
            print("C compress(%s) FAIL" % how, repr(e))
    # 灰度能不能显示
    try:
        lcd.display(g)
        print("C lcd.display(gray) OK")
    except Exception as e:
        print("C lcd.display(gray) FAIL", repr(e))
except Exception as e:
    print("C FATAL", repr(e))

try:
    sensor.set_pixformat(sensor.RGB565)
    sensor.skip_frames(time=1500)
except Exception as e:
    print("C 切回 RGB565 失败", repr(e))

# ==================== D: /ramdisk 对照 ====================
print("--- D: /ramdisk ---")
try:
    import uos

    class RamDev:
        def __init__(self, n=128 * 1024):
            self.fs_size = n
            self.fs_data = bytearray(n)
            self.erase_block = 32 * 1024
            self.log_block_size = 32 * 1024      # 修正: 应与 erase_block 一致
            self.log_page_size = 256             # 修正: SPIFFS 典型页大小

        def read(self, buf, size, addr):
            for i in range(len(buf)):
                buf[i] = self.fs_data[addr + i]

        def write(self, buf, size, addr):
            for i in range(len(buf)):
                self.fs_data[addr + i] = buf[i]

        def erase(self, size, addr):
            for i in range(size):
                self.fs_data[addr + i] = 0xff

    blk = RamDev()
    vfs = uos.VfsSpiffs(blk)
    try:
        vfs.mkfs(vfs)
    except Exception as e:
        print("D mkfs note", repr(e))
    uos.mount(vfs, "/ramdisk")
    print("D mount ok free=%d" % gc.mem_free())

    # D1: 文本文件 —— 内存 FS 本身可用吗
    try:
        f = open("/ramdisk/t.txt", "w")
        f.write("hello ramdisk 12345")
        f.close()
        f = open("/ramdisk/t.txt", "r")
        s = f.read()
        f.close()
        print("D1 text OK read=%r" % s)
    except Exception as e:
        print("D1 text FAIL", repr(e))

    # D2: 存 JPEG
    img = sensor.snapshot()
    t = time.ticks_ms()
    try:
        try:
            img.save("/ramdisk/t.jpg", quality=90)
        except Exception:
            img.save("/ramdisk/t.jpg")
        print("D2 save OK %dms size=%d" % (
            time.ticks_diff(time.ticks_ms(), t), uos.stat("/ramdisk/t.jpg")[6]))
        f = open("/ramdisk/t.jpg", "rb")
        raw = f.read()
        f.close()
        print("D2 read len=%d head=%s tail=%s IS_JPEG=%s" % (
            len(raw), hx(raw, 2), hx(raw, 2, True),
            "YES" if hx(raw, 2) == "ffd8" and hx(raw, 2, True) == "ffd9" else "NO"))
    except Exception as e:
        print("D2 save FAIL", repr(e))
    print("D listdir", uos.listdir("/ramdisk"))
except Exception as e:
    print("D FATAL", repr(e))

print("PROBE4 DONE free=%d" % gc.mem_free())
