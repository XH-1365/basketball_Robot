# -*- coding: utf-8 -*-
# ============================================================
#  K210 CanMV —— 按键拍照（串口直传版，不写 flash）
#
#  为什么这么设计 —— 血泪教训：
#    往片内 /flash 写 JPEG 会让整板在写若干张后【彻底挂死在 C 层】。
#    实测: 存 1 张活满 240 秒; 存到第 7 张 -> 挂死, 串口静读/回车/Ctrl-C
#    全部 0 响应, LCD 冻在最后一帧, 必须硬复位才能救。
#    (同源症状: 0 字节 JPEG / SPIFFS Error Code -10002 / OSError(5) /
#     core dump: illegal instruction)
#
#  于是改成:
#    拍照 -> 存【内存盘 /ramdisk】(纯 RAM, 用官方 demo_ram_fs.py 的
#    参数挂 VfsSpiffs) -> 读出来 base64 从串口吐给 PC -> 立刻删掉
#    全程零 flash 写入, PC 端落盘。次数只算一次, 不占空间。
#
#  另外武装看门狗: 万一本板固件仍然偶发挂死, 30 秒后硬件自动复位,
#  main.py 重跑, 板子自己恢复 —— 不会再出现"永久挂死"。
#
#  运行: python tools/live_run.py COM16 tools/capture_stream.py 320 > 日志
#  取回: python tools/parse_stream.py 日志文件 [输出目录]
# ============================================================

import gc
import os
import time

import lcd
import sensor
import ubinascii

# ---------------- 配置 ----------------
BTN_IO    = 17         # /flash/config.json -> board_info.BOOT_KEY = 17
SECS      = 300        # 总运行秒数
MAX_SHOTS = 60         # 本会话最多拍多少张(只受 RAM 盘和耐心限制)
DEBOUNCE_MS = 40
IDLE_BEEP = 20
JPEG_Q    = 90
B64_CHUNK = 1500       # 必须是 3 的倍数, base64 分块拼接才合法
DEBUG_AUTO_SHOT_SEC = 6   # >0 = 每 N 秒自动拍一张。只用于自测, 正常必须 0

# ==================== 阶段 1: 武装看门狗 ====================
# 注意: 这里【武装】而不是关闭。本板固件偶发 C 层挂死, 关掉看门狗 =
# 一旦挂死就是永久挂死(实测发生过)。武装它, 挂死 30 秒后自动复位自愈。
wdt = None
try:
    import machine
    wdt = machine.WDT(0, 30000)
    print("[1/6] WDT 已武装 30000ms (挂死可自愈)")
except Exception as e:
    print("[1/6] WDT 武装失败:", repr(e))

# ==================== 阶段 2: 挂内存盘 /ramdisk ====================
# 关键: 必须用官方 demo_ram_fs.py 的原参数。我自作聪明改成
# log_block_size=erase_block / log_page_size=256, 结果 SPIFFS -10028,
# 连挂载都失败。厂商参数别乱改。
os.mount  # noqa  (确认 os 是 uos)


class RAMFlashDev(object):
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


RAMDIR = None
try:
    blk = RAMFlashDev()
    vfs = os.VfsSpiffs(blk)
    try:
        vfs.mkfs(vfs)
    except Exception:
        pass
    os.mount(vfs, "/ramdisk")
    os.listdir("/ramdisk")
    RAMDIR = "/ramdisk"
    print("[2/6] 内存盘就绪 /ramdisk free=%d" % gc.mem_free())
except Exception as e:
    print("[2/6] 内存盘失败:", repr(e))
    print("[2/6] 回退 /flash (注意: 会写 flash, 有挂死风险)")
    RAMDIR = "/flash"

# ==================== 阶段 3: 次数续号（只读 flash, 不写）====================
# 次数从这里接着数, 保证断电重启后不会从 1 重来。只读, 不写 flash。
shot = 0
try:
    for n in os.listdir("/flash"):
        if n.startswith("cap_") and n.endswith(".jpg"):
            try:
                if os.stat("/flash/" + n)[6] <= 0:
                    continue
            except Exception:
                continue
            try:
                v = int(n[4:-4])
                if v > shot:
                    shot = v
            except Exception:
                pass
except Exception as e:
    print("[3/6] 扫 /flash 失败(忽略):", repr(e))
print("[3/6] 从次数 %d 接着数" % shot)

# ==================== 阶段 4: 摄像头 + 屏幕 ====================
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
print("[4/6] 摄像头就绪")

# ==================== 阶段 5: 按键 ====================
btn = None
try:
    from fpioa_manager import fm
    from maix import GPIO
    fm.register(BTN_IO, fm.fpioa.GPIOHS1)
    btn = GPIO(GPIO.GPIOHS1, GPIO.IN, GPIO.PULL_UP)
    print("[5/6] IO%d 就绪 当前 val=%d (按下=0)" % (BTN_IO, btn.value()))
except Exception as e:
    print("[5/6] 按键失败:", repr(e))


def shoot(img):
    """存到内存盘 -> 校验 -> base64 从串口吐出去 -> 删掉。返回 (名字, 字节数)。"""
    global shot
    shot += 1
    name = "cap_%03d.jpg" % shot
    path = "%s/%s" % (RAMDIR, name)
    try:
        try:
            img.save(path, quality=JPEG_Q)
        except Exception:
            img.save(path)
    except Exception as e:
        print("SHOTFAIL n=%d save %r" % (shot, e))
        shot -= 1
        return None, -1
    try:
        sz = os.stat(path)[6]
    except Exception as e:
        print("SHOTFAIL n=%d stat %r" % (shot, e))
        shot -= 1
        return None, -1
    if sz <= 0:
        print("SHOTFAIL n=%d size=0" % shot)
        shot -= 1
        return None, -1

    print("IMGBEGIN %s %d" % (name, sz))
    try:
        f = open(path, "rb")
        while True:
            d = f.read(B64_CHUNK)
            if not d:
                break
            print("B64 " + ubinascii.b2a_base64(d).decode().strip())
        f.close()
        print("IMGEND %s" % name)
        print("SHOT n=%d size=%d" % (shot, sz))
    except Exception as e:
        print("SHOTFAIL n=%d stream %r" % (shot, e))
        shot -= 1
        sz = -1
    # 立刻删掉, 内存盘只留当前这一张, 不占空间
    try:
        os.remove(path)
    except Exception:
        pass
    return name, sz


print("[6/6] 就绪: 按板上 BOOT 键拍照, 走串口直传 (当前次数 %d)" % shot)
print("STREAMREADY btn_io=%d ram=%s secs=%d" % (BTN_IO, RAMDIR, SECS))

t0 = time.ticks_ms()
last_beep = t0
held = False
flash_until = 0
sent = 0
last_size = -1
last_auto = t0

while time.ticks_diff(time.ticks_ms(), t0) < SECS * 1000:
    img = sensor.snapshot()
    now = time.ticks_ms()
    el = time.ticks_diff(now, t0) // 1000

    if btn is not None:
        v = btn.value()
        if v == 0 and not held:
            time.sleep_ms(DEBOUNCE_MS)
            if btn.value() == 0:
                held = True
                nm, sz = shoot(img)
                if sz > 0:
                    sent += 1
                    last_size = sz
                    flash_until = now + 1500
        elif v == 1 and held:
            held = False
    else:
        # 按键不可用时的兜底: 每 8 秒自动拍一张, 至少保证链路能跑
        if time.ticks_diff(now, last_auto) >= 8000:
            last_auto = now
            nm, sz = shoot(img)
            if sz > 0:
                sent += 1
                last_size = sz
                flash_until = now + 1500

    # 自测开关: DEBUG_AUTO_SHOT_SEC>0 时每 N 秒自动拍一张(交付时必须是 0)
    if DEBUG_AUTO_SHOT_SEC > 0 and             time.ticks_diff(now, last_auto) >= DEBUG_AUTO_SHOT_SEC * 1000:
        last_auto = now
        nm, sz = shoot(img)
        if sz > 0:
            sent += 1
            last_size = sz
            flash_until = now + 1500

    img.draw_string(0, 0, "%ds/%ds" % (el, SECS), color=(0, 60, 128), scale=1.5)
    img.draw_string(6, 30, "N=%d" % shot, color=(255, 255, 0), scale=3.0)
    img.draw_string(6, 110, "sent=%d" % sent, color=(0, 60, 128), scale=1.5)
    if btn is not None:
        img.draw_string(6, 130, "BTN=%d" % btn.value(),
                        color=(0, 60, 128), scale=1.5)
    img.draw_string(6, 150, "RAM %s" % RAMDIR, color=(0, 60, 128), scale=1.5)
    if now < flash_until:
        img.draw_string(6, 190, "SENT %d B" % last_size,
                        color=(255, 0, 0), scale=2.0)
    lcd.display(img)

    if time.ticks_diff(now, last_beep) >= IDLE_BEEP * 1000:
        last_beep = now
        print("ALIVE t=%ds shots=%d sent=%d btn=%s free=%d"
              % (el, shot, sent, btn.value() if btn else "n/a", gc.mem_free()))

    if sent >= MAX_SHOTS:
        print("已达 MAX_SHOTS=%d, 退出" % MAX_SHOTS)
        break

    if wdt:
        wdt.feed()
    gc.collect()

print("STREAMDONE shots=%d sent=%d" % (shot, sent))
try:
    if btn is not None:
        from fpioa_manager import fm
        fm.unregister(BTN_IO)
except Exception:
    pass
print("STREAMEXIT")
