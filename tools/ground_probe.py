# -*- coding: utf-8 -*-
# ============================================================
#  地面法(GROUND)标定采集 —— 板端脚本
#
#  用途: 人站在【卷尺量准】的距离上正面站直, 本脚本持续输出检测框的
#        脚尖行 y_feet, 事后用 tools/fit_pitch.py 反算相机俯角 CAM_PITCH_DEG。
#
#  为什么需要标定:
#        地面法 D = CAM_H_M / tan(pitch + atan((y脚 - cy) / f))
#        CAM_H_M 卷尺一量就有, 但【俯角量不准】—— 目测差 3 度, 2 米处能差几十厘米。
#
#  【必须和 body_detect.py 用同一套画面设置】
#        QVGA 320x240 / RGB565 / 同一个 ANCHOR_BODY / 同一个模型,
#        否则 h 和 y_feet 的像素尺度对不上, 标定结果直接作废。
#
#  用法(一般由 tools/ground_collect.py 驱动):
#        python tools/live_run.py COM16 tools/ground_probe.py 75
#        python tools/live_run.py COM16 tools/ground_probe.py 75 > gt.log
#        # 然后 ground_collect.py 会自动解析
# ============================================================

import gc
import math
import os
import time

import image
import lcd
import sensor
from maix import KPU

# ------------------------------------------------------------
# 配置区
# ------------------------------------------------------------

# 分段引导: (起秒, 止秒, 真实距离米)。由 PC 端 ground_collect.py 自动改写。
SEGMENTS = []

# 相机镜头离地高度(米)。拿卷尺从【地面】量到【镜头中心】。
CAM_H_M = 1.20

# 当前俯角估值, 只用来在屏幕上实时显示"现在算出多远", 不影响采集。
CAM_PITCH_DEG = 0.0

# 与 body_detect.py 保持一致的两个常量
FOCAL_PX = 277.0
CAM_CY = 120

PERSON_H_M = 1.70        # 仅用于同时显示身高法的对照值

THRESHOLD = 0.70
NMS = 0.20

STAT_EVERY_S = 5         # 每 N 秒打一行 STAT 心跳, 0=关

# 自检开关: True = 检不到人时塞一个固定假框, 走完 FEET/GEST 的打印与画框通路。
# 只用来验证脚本本身(镜头前没人也能确认通路是通的), 正常标定必须 False。
# 假框行的标记是 SIMFT/SIMGT, 不会被 ground_collect.py 当成真实数据收走。
SELFTEST_BOX = False

# 模型路径: 与 body_detect.py 同序(/sd 优先, 原因见那边注释)
MODEL_PATHS = (
    "/sd/person_v1.kmodel",
    "/sd/person_detect.kmodel",
    "/sd/KPU/head_body_detect/uint8_person_detect_v1_old.kmodel",
)

# 与 body_detect.py 的 ANCHOR_BODY 逐字一致
ANCHOR_BODY = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
               0.6287, 0.8052, 0.8129, 0.9384)

NET_W, NET_H = 320, 256
FRAME_W, FRAME_H = 320, 240
CAM_FEET_MARGIN = 2


def file_exists(path):
    try:
        d, name = path.rsplit("/", 1)
        return name in os.listdir(d if d else "/")
    except Exception:
        return False


def load_model(kpu, paths):
    """逐个试, 读不动的跳过(见 body_detect.py 的 /flash EIO 说明)。"""
    for p in paths:
        if not file_exists(p):
            continue
        try:
            print("[GT] 加载模型: %s" % p)
            kpu.load_kmodel(p)
            print("[GT] 模型加载成功: %s" % p)
            return p
        except Exception as e:
            print("[GT] !! 读不了, 换下一个: %s -> %s" % (p, repr(e)))
    raise OSError("[GT] 没有可用模型")


def seg_at(t):
    for a, b, d in SEGMENTS:
        if a <= t < b:
            return d, int(b - t)
    return None, 0


def est_ground(y_feet):
    """和 body_detect.est_dist_ground 同一套公式。"""
    if CAM_H_M <= 0 or FOCAL_PX <= 0:
        return None
    if y_feet >= FRAME_H - CAM_FEET_MARGIN:
        return None
    beta = math.atan((y_feet - CAM_CY) / FOCAL_PX)
    alpha = math.radians(CAM_PITCH_DEG) + beta
    if alpha <= 0.03:
        return None
    return CAM_H_M / math.tan(alpha)


def main():
    print("[GT] 地面法标定采集启动")
    print("[GT] CAM_H_M=%.3f m  CAM_PITCH_DEG(当前估值)=%.2f  FOCAL_PX=%.1f  CAM_CY=%d"
          % (CAM_H_M, CAM_PITCH_DEG, FOCAL_PX, CAM_CY))
    if SEGMENTS:
        print("[GT] 分段计划:")
        for a, b, d in SEGMENTS:
            print("[GT]   %3d~%3ds  ->  站到 %.2f m" % (a, b, d))
    else:
        print("[GT] 未给分段, 纯采集模式(屏幕上不提示距离)")

    # ---- 先停掉自启脚本, 把系统堆留出来 ----
    try:
        sensor.run(0)
    except Exception:
        pass
    gc.collect()
    print("[GT] 加载模型前内存: %d" % gc.mem_free())

    # ---- 铁律: 先加载模型, 后 lcd.init()。lcd.init 会吃掉系统堆, ---
    # ---- 先开屏会让 KPU 那 1.4MB 分配失败。                    ---
    kpu = KPU()
    load_model(kpu, MODEL_PATHS)
    kpu.init_yolo2(ANCHOR_BODY, anchor_num=len(ANCHOR_BODY) // 2,
                   img_w=FRAME_W, img_h=FRAME_H,
                   net_w=NET_W, net_h=NET_H,
                   layer_w=10, layer_h=8,
                   threshold=THRESHOLD, nms_value=NMS,
                   classes=1)
    gc.collect()
    print("[GT] 模型就位, 内存: %d" % gc.mem_free())

    lcd_ok = True
    try:
        lcd.init()
    except Exception as e:
        print("[GT] lcd.init 失败(忽略继续):", repr(e))
        lcd_ok = False

    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.skip_frames(time=1200)
    W, H = sensor.width(), sensor.height()
    print("[GT] 画面 %dx%d" % (W, H))

    od_img = image.Image(size=(NET_W, NET_H))
    clock = time.clock()
    t0 = time.ticks_ms()
    last_stat = t0
    n_frame = 0
    n_box = 0
    cur_seg = None

    while True:
        clock.tick()
        img = sensor.snapshot()
        el = time.ticks_diff(time.ticks_ms(), t0) / 1000.0

        if SEGMENTS:
            d, left = seg_at(el)
            if d != cur_seg:
                cur_seg = d
                if d is None:
                    print("[GT] >>> 采集段结束")
                else:
                    print("[GT] >>> 请站到 %.2f m 处(正面站直, 整个人进画面)"
                          % d)

        got = 0
        try:
            kpu.run_with_output(img)
            boxes = kpu.regionlayer_yolo2()
        except Exception as e:
            print("[GT] KPU 异常:", repr(e))
            boxes = []

        sim = False
        if SELFTEST_BOX and not boxes:
            # 假框: 站在 ~1.2m 处的人大致就是这个位置
            boxes = [(100, 14, 110, 200, 0.99)]
            sim = True

        if boxes:
            for b in boxes:
                try:
                    x, y, w, h = b[0], b[1], b[2], b[3]
                    prob = b[4]
                except Exception:
                    continue
                yf = y + h
                got += 1
                n_box += 1
                # ↓ 这行是给 ground_collect.py 解析的, 字段名别改
                print("[%6.1fs] %s yf=%3d y=%3d h=%3d w=%3d cx=%3d p=%.2f"
                      % (el, "SIMFT" if sim else "FEET",
                         yf, y, h, w, x + w // 2, prob))
                dg = est_ground(yf)
                dh = (PERSON_H_M * FOCAL_PX / h) if h > 0 else None
                print("[%6.1fs] %s %s  %s"
                      % (el, "SIMGT" if sim else "GEST",
                         ("dG=%.2fm" % dg) if dg else "dG=--(脚被切/太远)",
                         ("dH=%.2fm" % dh) if dh else "dH=--"))
                try:
                    img.draw_rectangle(x, y, w, h, color=(255, 0, 0))
                    img.draw_cross(x + w // 2, yf, color=(0, 255, 0), size=3)
                    img.draw_string(x, max(0, y - 12),
                                    "yf%d %s" % (yf, ("%.1f" % dg) if dg else "?"),
                                    color=(255, 255, 0), scale=1.0)
                except Exception:
                    pass

        n_frame += 1

        if lcd_ok:
            try:
                if SEGMENTS:
                    d, left = seg_at(el)
                    msg = ("STAND AT %.2fm  %ds" % (d, left)) if d else "GT CALIB --"
                else:
                    msg = "GT CALIB  %.1fs" % el
                img.draw_string(2, 2, msg, color=(255, 255, 0), scale=1.0)
                img.draw_string(2, H - 12, "boxes=%d fps=%.0f" % (got, clock.fps()),
                                color=(0, 255, 255), scale=1.0)
                lcd.display(img)
            except Exception as e:
                print("[GT] lcd.display 失败, 之后不再显示:", repr(e))
                lcd_ok = False

        if STAT_EVERY_S and time.ticks_diff(
                time.ticks_ms(), last_stat) >= STAT_EVERY_S * 1000:
            last_stat = time.ticks_ms()
            print("[%6.1fs] STAT n_box=%d frames=%d fps=%.1f free=%d"
                  % (el, n_box, n_frame, clock.fps(), gc.mem_free()))

        gc.collect()


main()
