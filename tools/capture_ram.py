# -*- coding: utf-8 -*-
# ============================================================
#  K210 CanMV —— 按键拍照（内存盘 + 分块校验回传）
#
#  【为什么是这套架构 —— 四轮实测结论】
#
#  1. 写片内 /flash 存图 -> 写几张后【整板挂死在 C 层】(实测第 9 张挂死,
#     串口静读/回车/Ctrl-C 全 0 响应, 必须硬复位)。-> 拍照链路禁止写 flash。
#
#  2. 写 TF 卡 -> 根本走不通(实测):
#       - machine.SDCard 是空壳: TypeError cannot create 'SDCard' instances
#       - /sd 直接 OSError(19)  (固件没挂上来)
#       - 固件自己占着 SPI1(IO32/33/34/35) 且每次开机都报 sdcard no found
#         -> 固件自己都没看见卡
#       - 我们绕过固件直接驱动 SPI1 跟卡握手 -> 整板 C 层死锁
#     -> 结论: TF 卡在这块板 + 这套固件上是死结, 只能走串口。
#
#  3. 图留在内存, 拍完裸拼 base64 吐串口 -> 5 张里坏 1 张, 而且 PC 端
#     【看不出哪块坏了】(固件的杂行会插进 base64 中间)。
#
#  4. 内存盘方案(本脚本) —— 实测容量与坑:
#       - 启动 gc heap 只有 768432 字节; 内存盘只能开到 512K
#         (768K/1024K 直接 MemoryError)
#       - 256K 盘只能存 4 张 17KB 图; 512K 盘能存 14 张 (SPIFFS 块粒度问题)
#       - 【绝对不能删文件】: 一删就 SPIFFS Error Code -10007 / OSError(24),
#         整盘永久卡死(实测环形删除 12 次全失败)
#     -> 所以: 512K 盘, 只写不删, 上限 14 张。
#
#  回传协议(带校验, PC 端能定位到块):
#      B <名字> <块号> <块字节数> <校验和> <base64>#
#    末尾的 '#' 是终止符(不在 base64 字母表里)。PC 端按【字符流】攒够
#    该块应有的 base64 字符数再校验 —— 板子偶尔会在长行中间莫名插一个
#    换行, 字符流读法对此完全免疫。
#
#  长按 BOOT 键 1.2 秒 = 把盘上所有图再吐一遍, 给 PC 补坏块的机会。
#  看门狗武装(30s): 万一再挂死, 硬件自动复位, main.py 重跑, 板子自愈。
#
#  运行: python tools/live_run.py COM16 tools/capture_ram.py 240
#    或: python tools/fetch_ram.py COM16 240      (跑+收+解析 一条龙)
# ============================================================

import gc
import os
import time
import ubinascii

import lcd
import sensor

# ---------------- 配置 ----------------
BTN_IO      = 17        # /flash/config.json -> board_info.BOOT_KEY = 17
SECS        = 600       # 循环最长跑多少秒(PC 那边可提前 Ctrl-C)
MAX_SHOTS   = 14        # 512K 内存盘实测上限(写满再写就 size=0)
DEBOUNCE_MS = 30
LONG_MS     = 1200      # 按住多久算"长按"(= 重吐全部图)
IDLE_BEEP   = 20
JPEG_Q      = 90
CHUNK       = 512       # 分块大小 -> base64 684 字符
RAMDISK_KB  = 512       # 内存盘大小(实测 768K 就 MemoryError 了)
WDT_MS      = 30000
DEBUG_AUTO_SHOT_SEC = 0  # >0 = 每 N 秒自动拍一张。只用于自测, 正常必须 0

# ---------------- 屏幕配色 ----------------
# 用户指定: 【用黄色】。全部文字统一亮黄, 在实拍画面上最醒目。
C_PROG  = (255, 255, 0)     # 进度
C_COUNT = (255, 255, 0)     # 次数(最大号)
C_KEEP  = (255, 255, 0)     # 已收张数
C_BTN   = (255, 255, 0)     # 按键电平
C_RAM   = (255, 255, 0)     # 内存盘路径
C_HINT  = (255, 255, 0)     # 提示
C_MSG   = (255, 255, 0)     # 成功/失败提示

# ==================== 阶段 1: 武装看门狗 ====================
wdt = None
try:
    import machine
    wdt = machine.WDT(0, WDT_MS)
    print("[1/7] WDT 已武装 %dms (挂死可自愈)" % WDT_MS)
except Exception as e:
    print("[1/7] WDT 武装失败:", repr(e))

# ==================== 阶段 2: 挂内存盘 ====================
# 必须用官方 demo_ram_fs.py 的原参数(log_block_size 改小过 -> SPIFFS -10028)。
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
for kb in (RAMDISK_KB, 256):
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
        print("[2/7] 内存盘就绪 %dK /ramdisk gc_free=%d" % (kb, gc.mem_free()))
        break
    except Exception as e:
        print("[2/7] 内存盘 %dK 失败: %r" % (kb, e))
if RAMDIR is None:
    print("[2/7] 回退 /flash (注意: 会写 flash, 有挂死风险)")
    RAMDIR = "/flash"

# ==================== 阶段 3: 次数续号（只读, 不写）====================
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
    print("[3/7] 扫 /flash 失败(忽略):", repr(e))
print("[3/7] 从次数 %d 接着数" % shot)

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
sensor.set_hmirror(0)          # GC2145 非镜像安装, 必须 0
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)
print("[4/7] 摄像头就绪")

# ==================== 阶段 5: 按键 ====================
btn = None
try:
    from fpioa_manager import fm
    from maix import GPIO
    fm.register(BTN_IO, fm.fpioa.GPIOHS1)   # 官方写法: GPIOHS1, 不要 force
    btn = GPIO(GPIO.GPIOHS1, GPIO.IN, GPIO.PULL_UP)
    print("[5/7] IO%d 就绪 当前 val=%d (按下=0)" % (BTN_IO, btn.value()))
except Exception as e:
    print("[5/7] 按键失败:", repr(e))


# ==================== 阶段 6: 回传 ====================
def feed_wdt():
    if wdt:
        wdt.feed()


def dump_file(name):
    """把一个文件按块吐回串口。每块 = 块号 + 字节数 + 校验和 + base64 + '#'"""
    path = "%s/%s" % (RAMDIR, name)
    try:
        sz = os.stat(path)[6]
    except Exception as e:
        print("SERVEERR stat %s %r" % (name, e))
        return -1
    if sz <= 0:
        print("SERVEERR %s size=0" % name)
        return -1
    nch = (sz + CHUNK - 1) // CHUNK
    print("ITEM %s %d %d" % (name, sz, nch))
    try:
        f = open(path, "rb")
    except Exception as e:
        print("SERVEERR open %s %r" % (name, e))
        print("E %s 0" % name)
        return -1
    i = 0
    try:
        while True:
            d = f.read(CHUNK)
            if not d:
                break
            ck = sum(d) & 0xFFFF
            print("B %s %d %d %d %s#"
                  % (name, i, len(d), ck,
                     ubinascii.b2a_base64(d).decode().strip()))
            i += 1
            feed_wdt()
    except Exception as e:
        print("SERVEERR read %s %r" % (name, e))
    try:
        f.close()
    except Exception:
        pass
    print("E %s %d" % (name, i))
    return i


def dump_all(tag):
    names = []
    try:
        for n in os.listdir(RAMDIR):
            if n.startswith("cap_") and n.endswith(".jpg"):
                names.append(n)
    except Exception as e:
        print("SERVEERR list %r" % (e,))
    names.sort()
    print("SERVE count=%d tag=%s" % (len(names), tag))
    for n in names:
        dump_file(n)
        feed_wdt()
    print("SERVEDONE count=%d tag=%s gc_free=%d"
          % (len(names), tag, gc.mem_free()))


def shoot(img):
    """存到内存盘并校验。返回 (名字, 字节数)。图不删, 等重传。"""
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
        # 内存盘写满的典型症状。别再原地死循环重试(之前就是这么卡住的)。
        print("SHOTFAIL n=%d size=0 (内存盘满?)" % shot)
        shot -= 1
        return None, -2
    print("SHOT n=%d name=%s size=%d" % (shot, name, sz))
    return name, sz


print("[6/7] 就绪: 短按 BOOT 拍照 / 长按 BOOT %dms 重吐全部图 (当前次数 %d)"
      % (LONG_MS, shot))
print("[7/7] RAMREADY btn_io=%d ram=%s secs=%d chunk=%d max=%d"
      % (BTN_IO, RAMDIR, SECS, CHUNK, MAX_SHOTS))

t0 = time.ticks_ms()
last_beep = t0
press_t = 0
long_fired = False
saved = 0
last_size = -1
msg = ""
msg_until = 0
last_auto = t0
full = False

while time.ticks_diff(time.ticks_ms(), t0) < SECS * 1000:
    img = sensor.snapshot()
    now = time.ticks_ms()
    el = time.ticks_diff(now, t0) // 1000

    if btn is not None and not full:
        v = btn.value()
        if v == 0:
            if press_t == 0:
                press_t = now
            elif (not long_fired) and \
                    time.ticks_diff(now, press_t) >= LONG_MS:
                # ---- 长按: 重吐全部图 ----
                long_fired = True
                print("LONGPRESS_DUMP t=%ds" % el)
                img.draw_string(6, 190, "DUMPING...", color=C_MSG, scale=1.6)
                lcd.display(img)
                dump_all("longpress")
                msg = "DUMPED"
                msg_until = time.ticks_ms() + 1500
                gc.collect()
        else:
            if press_t != 0 and not long_fired:
                # ---- 短按松手: 拍一张并立刻回传 ----
                time.sleep_ms(DEBOUNCE_MS)
                if btn.value() == 1:
                    nm, sz = shoot(img)
                    if sz > 0:
                        saved += 1
                        last_size = sz
                        msg = "SENT %d B" % sz
                        msg_until = time.ticks_ms() + 1500
                        img.draw_string(6, 190, "SENDING...",
                                        color=C_MSG, scale=1.6)
                        lcd.display(img)
                        feed_wdt()
                        dump_file(nm)
                        gc.collect()
                    elif sz == -2:
                        msg = "DISK FULL"
                        msg_until = time.ticks_ms() + 3000
                        if saved >= MAX_SHOTS:
                            full = True
            press_t = 0
            long_fired = False

    # 自测开关(交付时必须是 0)
    if DEBUG_AUTO_SHOT_SEC > 0 and not full and \
            time.ticks_diff(now, last_auto) >= DEBUG_AUTO_SHOT_SEC * 1000:
        last_auto = now
        nm, sz = shoot(img)
        if sz > 0:
            saved += 1
            last_size = sz
            msg = "AUTO %d B" % sz
            msg_until = time.ticks_ms() + 1500
            dump_file(nm)
            gc.collect()
        elif sz == -2:
            msg = "DISK FULL"
            msg_until = time.ticks_ms() + 3000
            full = True

    now = time.ticks_ms()
    img.draw_string(0, 0, "%ds/%ds" % (el, SECS), color=C_PROG, scale=1.5)
    img.draw_string(6, 30, "N=%d" % shot, color=C_COUNT, scale=3.0)
    img.draw_string(6, 110, "kept=%d" % saved, color=C_KEEP, scale=1.5)
    if btn is not None:
        img.draw_string(6, 130, "BTN=%d" % btn.value(), color=C_BTN, scale=1.5)
    img.draw_string(6, 150, "%s" % RAMDIR, color=C_RAM, scale=1.5)
    img.draw_string(6, 170, "hold=re-send", color=C_HINT, scale=1.5)
    if now < msg_until:
        img.draw_string(6, 190, msg, color=C_MSG, scale=2.0)
    lcd.display(img)

    if time.ticks_diff(now, last_beep) >= IDLE_BEEP * 1000:
        last_beep = now
        print("ALIVE t=%ds shots=%d kept=%d btn=%s gc_free=%d"
              % (el, shot, saved, btn.value() if btn else "n/a", gc.mem_free()))

    if saved >= MAX_SHOTS:
        print("已达 MAX_SHOTS=%d" % MAX_SHOTS)
        break

    feed_wdt()
    gc.collect()

print("RAM_FINISHING shots=%d kept=%d" % (shot, saved))
try:
    dump_all("exit")
except Exception as e:
    print("SERVEERR dump_all %r" % (e,))
try:
    print("RAM_LIST %s" % os.listdir(RAMDIR))
except Exception as e:
    print("RAM_LIST ERR", repr(e))
try:
    if btn is not None:
        from fpioa_manager import fm
        fm.unregister(BTN_IO)
except Exception:
    pass
print("RAMDONE shots=%d kept=%d" % (shot, saved))
# 注意: 这个结束标记必须【唯一】, 不能被别的输出行包含。
# 踩过的坑: 原本收尾第一行叫 RAMEXIT_BEGIN, 里面含了 "RAMEXIT",
# 结果 PC 端一看到就提前收工, 收尾那次整体重吐根本没跑到。
print("RAM_ALLDONE")
