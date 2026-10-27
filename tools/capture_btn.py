# -*- coding: utf-8 -*-
# ============================================================
#  K210 CanMV —— 按键拍照 + 次数记录
#
#  按板上 BOOT 键(IO17, 见 /flash/config.json 的 board_info.BOOT_KEY)
#  每按一次: 存一张 JPEG + 次数 +1, 次数大字显示在 LCD 上
#
#  存储位置: 有 /sd 就存 /sd, 没有就退 /flash（本板固件不支持 TF 卡）
#  次数是"持久"的: 启动时扫已有 cap_NNN.jpg 的最大编号接着数,
#                所以断电/重启后接着数, 不会从 1 重来。
#  每存一张立刻 os.stat 校验大小 —— 0 字节 = 文件系统坏了, 当场报警。
#
#  运行: python tools/live_run.py COM16 tools/capture_btn.py 260
#  取回: python tools/fetch_caps.py COM16
# ============================================================

import gc
import os
import time

import lcd
import sensor

# ---------------- 配置 ----------------
BTN_IO    = 17         # /flash/config.json -> board_info.BOOT_KEY = 17
SECS      = 240        # 总运行秒数(到点自己退出, 免得占着串口)
MAX_SHOTS = 30         # 最多存多少张, 防止把 flash 写满
DEBOUNCE_MS = 40       # 消抖
IDLE_BEEP = 20         # 每多少秒打一次状态(用来验证按键是否活着)

# ============================================================
#  阶段 1: 关看门狗
# ============================================================
# 实测: WDT.stop() 真的有效(武装 5 秒后停掉, 板子活满 10 秒)。
# 但必须关 —— main.py 武装的 30 秒狗没人喂, 会在脚本跑到一半时复位板子。
try:
    import machine
    _w = machine.WDT(0, 60000)
    _w.stop()
    print("[1/6] WDT 已关闭")
except Exception as e:
    print("[1/6] WDT 关闭失败(继续):", repr(e))

# ============================================================
#  阶段 2: 选存储目录 + 续号
# ============================================================
SAVE_DIR = None
for d in ("/sd", "/flash"):
    try:
        os.listdir(d)
        SAVE_DIR = d
        break
    except Exception:
        pass
if SAVE_DIR is None:
    raise OSError("既没有 /sd 也没有 /flash")
print("[2/6] 存图目录: %s" % SAVE_DIR)

# 续号: 扫已有 cap_NNN.jpg 的最大编号 —— 这就是"拍照次数"的持久化
shot = 0
old = 0
try:
    for n in os.listdir(SAVE_DIR):
        if n.startswith("cap_") and n.endswith(".jpg"):
            # 0 字节的是上次崩溃留下的烂文件: 不算照片, 也不能计入次数
            try:
                if os.stat("%s/%s" % (SAVE_DIR, n))[6] <= 0:
                    print("[2/6] 跳过 0 字节坏文件: %s" % n)
                    continue
            except Exception:
                continue
            old += 1
            try:
                v = int(n[4:-4])
                if v > shot:
                    shot = v
            except Exception:
                pass
except Exception as e:
    print("[2/6] 扫目录失败:", repr(e))
print("[2/6] 已有 %d 张, 最大编号 %d -> 从 %d 接着数" % (old, shot, shot + 1))

# ============================================================
#  阶段 3: 摄像头 + 屏幕
# ============================================================
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
sensor.skip_frames(time=2000)   # 让自动增益/曝光收敛(冻太早会拍出黑图)
print("[3/6] 摄像头就绪")

# ============================================================
#  阶段 4: 按键
# ============================================================
# 按官方 demo 的写法: GPIOHS1、不用 force=True。
# 实测 fm.register(17, GPIOHS1) 不带 force 就能成功 -> IO17 没被别的外设占用。
# 放在摄像头初始化之后注册, 尽量避免和摄像头抢引脚。
btn = None
try:
    from fpioa_manager import fm
    from maix import GPIO
    fm.register(BTN_IO, fm.fpioa.GPIOHS1)
    btn = GPIO(GPIO.GPIOHS1, GPIO.IN, GPIO.PULL_UP)
    print("[4/6] IO%d 注册为输入(上拉), 按下应为 0, 当前 val=%d"
          % (BTN_IO, btn.value()))
except Exception as e:
    print("[4/6] 按键初始化失败:", repr(e))
    print("[4/6] 降级: 每 6 秒自动拍一张, 流程仍可验证")

# ============================================================
#  阶段 5: 主循环
# ============================================================
saved = []


def save_one(img):
    """存一张并校验大小。成功返回字节数, 失败返回 -1。"""
    global shot
    shot += 1
    path = "%s/cap_%03d.jpg" % (SAVE_DIR, shot)
    try:
        try:
            img.save(path, quality=90)
        except Exception:
            img.save(path)
    except Exception as e:
        print("CAPFAIL %s save_error %r" % (path, e))
        shot -= 1          # 没存成就别占号, 次数要真实
        return -1
    try:
        sz = os.stat(path)[6]
    except Exception as e:
        print("CAPFAIL %s stat_error %r" % (path, e))
        shot -= 1
        return -1
    if sz <= 0:
        print("CAPBAD %s size=0 (文件系统写入失败!)" % path)
        shot -= 1
        return -1
    # 每次按下都打一行, 这行就是"拍照次数"的权威记录
    print("SHOT n=%d file=%s size=%d" % (shot, path, sz))
    return sz


print("[5/6] 就绪: 请按板上 BOOT 键拍照 (当前次数 %d)" % shot)
print("CAPREADY btn_io=%d dir=%s secs=%d" % (BTN_IO, SAVE_DIR, SECS))

t0 = time.ticks_ms()
last_beep = t0
held = False
flash_until = 0
auto_t = t0
last_shot_size = -1

while time.ticks_diff(time.ticks_ms(), t0) < SECS * 1000:
    img = sensor.snapshot()
    now = time.ticks_ms()
    el = time.ticks_diff(now, t0) // 1000

    if btn is not None:
        val = btn.value()               # 按下 = 0
        if val == 0 and not held:
            time.sleep_ms(DEBOUNCE_MS)  # 消抖
            if btn.value() == 0:
                held = True
                sz = save_one(img)
                if sz > 0:
                    saved.append((shot, sz))
                    last_shot_size = sz
                    flash_until = now + 1200
                img.draw_string(6, 150, "SAVED %d" % shot,
                                color=(255, 0, 0), scale=2.0)
        elif val == 1 and held:
            held = False
    else:
        if time.ticks_diff(now, auto_t) > 6000:
            auto_t = now
            sz = save_one(img)
            if sz > 0:
                saved.append((shot, sz))
                last_shot_size = sz
                flash_until = now + 1200

    # ---------- 显示 ----------
    img.draw_string(0, 0, "%ds/%ds" % (el, SECS), color=(0, 60, 128), scale=1.5)
    # 拍照次数: 大字, 这是主要信息
    img.draw_string(6, 30, "N=%d" % shot, color=(255, 255, 0), scale=3.0)
    if btn is not None:
        img.draw_string(6, 110, "BTN=%d" % btn.value(),
                        color=(0, 60, 128), scale=1.5)
    img.draw_string(6, 130, "DIR=%s" % SAVE_DIR, color=(0, 60, 128), scale=1.5)
    if now < flash_until:
        img.draw_string(6, 190, "SAVED %dB" % last_shot_size,
                        color=(255, 0, 0), scale=2.0)
    lcd.display(img)

    # ---------- 周期状态 ----------
    if time.ticks_diff(now, last_beep) >= IDLE_BEEP * 1000:
        last_beep = now
        print("ALIVE t=%ds shots=%d btn=%s"
              % (el, shot, btn.value() if btn else "n/a"))

    if len(saved) >= MAX_SHOTS:
        print("已达 MAX_SHOTS=%d, 退出" % MAX_SHOTS)
        break

    gc.collect()

# ============================================================
#  阶段 6: 收尾
# ============================================================
print("[6/6] 本次会话新拍 %d 张" % len(saved))
total = 0
for n, sz in saved:
    print("   cap_%03d.jpg  %d bytes" % (n, sz))
    total += sz
print("COUNT total_shot=%d session=%d bytes=%d"
      % (shot, len(saved), total))
try:
    if btn is not None:
        from fpioa_manager import fm
        fm.unregister(BTN_IO)
except Exception:
    pass
print("CAPEXIT")
