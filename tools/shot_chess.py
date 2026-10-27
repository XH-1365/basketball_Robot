# -*- coding: utf-8 -*-
# ============================================================
#  棋盘格标定采集（板端脚本）
#
#  用途: 给 PC 端 OpenCV 标定用的照片采集。按一下 BOOT 键(IO17)拍一张
#        【干净的】QVGA JPEG 存到 /sd/chess_NN.jpg —— 不画任何 HUD,
#        因为标定要角点, 屏幕上多一行字都可能挡住边缘角点。
#
#  拍摄要点(决定标定质量, 比代码重要):
#    1. 15~25 张, 每张棋盘格姿态都要变: 左右倾斜、上下俯仰、远近、
#       以及把棋盘格放到画面的【各个角落】(尤其四角, 畸变在边缘最大)
#    2. 棋盘格必须【整块都在画面里】, 一个角都不能出画
#    3. 光线要够! 画面太暗角点检测会失败
#    4. 对焦/对准后手要稳, 按键瞬间别晃
#
#  用法: python tools/live_run.py COM16 tools/shot_chess.py 600
#        (跑 600 秒, 期间随便按; 或者用 deploy 思路直接跑)
# ============================================================

import gc
import os
import sys
import time
import ubinascii

import image
import lcd
import sensor
from fpioa_manager import fm
from maix import GPIO

# ------------------------------------------------------------
# 配置区
# ------------------------------------------------------------
SHOT_DIR = "/sd"
SHOT_PREFIX = "chess_"
SHOT_QUALITY = 95        # 标定图要高质量, JPEG 压缩伪影会伤角点精度
SHOT_KEY_IO = 17
DEBOUNCE_MS = 600
LCD_OK = True
# >0 时, 开机这么多秒后自动"虚拟按下"一次, 用来在没人按键的情况下
# 把 拍照->存盘->编号 的代码路径真正走一遍(自检). 正常使用保持 0。
SELFTEST_PRESS_AFTER_S = 0
# 拍到这么多张就自动退出(方便 PC 端一条命令跑完, 不用手动 Ctrl-C)。
# 0 = 不限张数。
MAX_SHOTS = 25

# ---- 实时预览（配合 tools/live_view.py 在 PC 浏览器里看画面）----
# 打开后每次循环会往 stdout 吐一帧 JPEG:
#     FRM<base64长度>\n<base64正文>\n
# PC 端按这个格式解析。用 CanMV IDE 跑的时候保持 False, 否则满屏 base64。
PREVIEW_FRAMES = False
PREVIEW_EVERY_MS = 250      # 最快多久发一帧(发太快会挤掉按键轮询)
PREVIEW_SCALE = 0.5         # 0.5 -> 160x120, 0.25 -> 80x60
PREVIEW_QUALITY = 50        # JPEG 质量, 越低越流畅

# ------------------------------------------------------------
def setup_key():
    fm.register(SHOT_KEY_IO, fm.fpioa.GPIOHS1)
    key = GPIO(GPIO.GPIOHS1, GPIO.IN)
    return key


def next_id(d, prefix):
    """扫已有文件, 返回下一个可用编号(跳过 0 字节坏文件)。"""
    mx = -1
    try:
        for name in os.listdir(d):
            if not name.startswith(prefix):
                continue
            if not name.endswith(".jpg"):
                continue
            try:
                if os.stat(d + "/" + name)[6] == 0:
                    continue
            except Exception:
                continue
            try:
                n = int(name[len(prefix):-4])
            except Exception:
                continue
            if n > mx:
                mx = n
    except Exception:
        pass
    return mx + 1


def send_preview(img):
    """缩一帧成小 JPEG, base64 吐到 stdout。格式: FRM<长度>\\n<正文>\\n

    用 print 而不是 sys.stdout.write: 走同一条已验证过的实时输出通路,
    而且换行由解释器保证。PC 端只认 FRM 头 + 指定长度, 不靠换行猜。
    """
    small = img.copy(x_scale=PREVIEW_SCALE, y_scale=PREVIEW_SCALE)
    jpg = small.compress(quality=PREVIEW_QUALITY).to_bytes()
    b64 = ubinascii.b2a_base64(jpg).decode().strip()
    print("FRM%d" % len(b64))
    print(b64)


def main():
    print("[CHESS] 棋盘格标定采集启动")
    print("[CHESS] 按 BOOT 键拍一张, 存 %s/%sNN.jpg (质量 %d)"
          % (SHOT_DIR, SHOT_PREFIX, SHOT_QUALITY))
    print("[CHESS] 要点: 15~25 张 / 每张姿态都变 / 棋盘格别出画 / 光线要够")

    try:
        lcd.init()
    except Exception as e:
        print("[CHESS] lcd.init 失败(忽略继续):", repr(e))

    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.skip_frames(time=1500)
    print("[CHESS] 画面 %dx%d" % (sensor.width(), sensor.height()))

    try:
        os.listdir(SHOT_DIR)
    except Exception as e:
        print("[CHESS] !! %s 读不到(%r), 没法存图, 退出" % (SHOT_DIR, e))
        return 1

    nid = next_id(SHOT_DIR, SHOT_PREFIX)
    saved = 0
    print("[CHESS] 起始编号 %d" % nid)

    key = setup_key()
    key_down = False
    last_ms = 0
    clock = time.clock()
    t0 = time.ticks_ms()
    selftest_done = False
    last_prev = 0
    preview_on = PREVIEW_FRAMES

    while True:
        clock.tick()
        img = sensor.snapshot()

        v = key.value()
        now = time.ticks_ms()
        want_shot = (v == 0 and not key_down and (now - last_ms) > DEBOUNCE_MS)
        if (not want_shot and SELFTEST_PRESS_AFTER_S > 0
                and not selftest_done
                and time.ticks_diff(now, t0) >= SELFTEST_PRESS_AFTER_S * 1000):
            want_shot = True
            selftest_done = True
            print("[CHESS] >>> 自检: 虚拟按下一次")
        if want_shot:
            key_down = True
            last_ms = now
            name = "%s/%s%03d.jpg" % (SHOT_DIR, SHOT_PREFIX, nid)
            try:
                img.save(name, quality=SHOT_QUALITY)
                sz = os.stat(name)[6]
                if sz == 0:
                    os.remove(name)
                    print("[CHESS] %s 写出 0 字节, 已删(坏文件)" % name)
                else:
                    print("[CHESS] SAVED %s (%d 字节)  已拍 %d 张"
                          % (name, sz, saved + 1))
                    nid += 1
                    saved += 1
            except Exception as e:
                print("[CHESS] 保存失败:", repr(e))
        elif v == 1 and key_down:
            key_down = False

        # 屏幕提示
        try:
            if MAX_SHOTS > 0:
                head = "CHESS %d/%d" % (saved, MAX_SHOTS)
            else:
                head = "CHESS saved=%d" % saved
            img.draw_string(2, 2, head, color=(255, 255, 0), scale=2.0)
            img.draw_string(2, 220, "press BOOT to snap",
                            color=(0, 255, 255), scale=1.0)
            lcd.display(img)
        except Exception as e:
            print("[CHESS] lcd.display 失败, 之后不再显示:", repr(e))

        if MAX_SHOTS > 0 and saved >= MAX_SHOTS:
            print("[CHESS] 已拍满 %d 张, 自动结束" % saved)
            print("CHESSDONE saved=%d" % saved)
            return 0

        # 实时预览(给 PC 端 live_view.py 用)
        # 注意: 这里必须用【局部】变量 preview_on, 不能直接给 PREVIEW_FRAMES 赋值 ——
        # 一旦在函数里对同名全局变量赋值, Python 会把它当局部变量,
        # 上面那句 `if preview_on` 就会 NameError: local variable referenced
        # before assignment。(踩过一次, 板端直接崩)
        if preview_on and time.ticks_diff(now, last_prev) >= PREVIEW_EVERY_MS:
            last_prev = now
            try:
                send_preview(img)
            except Exception as e:
                print("[CHESS] 预览失败, 关掉预览继续: %r" % (e,))
                preview_on = False

        gc.collect()


main()
