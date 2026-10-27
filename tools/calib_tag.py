# -*- coding: utf-8 -*-
# ============================================================
#  AprilTag 标定采集（板端脚本）
#
#  用途: 把打印好的 tag 摆在【卷尺量准的距离】上, 本脚本持续输出检测到的
#        tag 像素尺寸, 事后用过原点最小二乘反算相机焦距 FOCAL_PX。
#
#  【硬限制, 必须知道】find_apriltags 在本板固件上处理分辨率必须 < 64K 像素:
#        QVGA(320x240) = 76800 -> OSError: The maximum supported resolution ...
#        所以这里强制 QQVGA(160x120)。也意味着【标定和人体检测不能同帧跑】,
#        标定是独立的一轮。
#
#  用法(由 tools/calib_collect.py 驱动, 一般不用手跑):
#        python tools/live_run.py COM16 tools/calib_tag.py 90 > calib.log
#        然后 python tools/fit_focal.py calib.log 0.100 --tag "0,15,0.5" "15,30,1.0"
# ============================================================

import gc
import math
import os
import time

import image
import lcd
import sensor

# ------------------------------------------------------------
# 配置区
# ------------------------------------------------------------

# 分段引导: (起秒, 止秒, 真实距离米)。由 PC 端 calib_collect.py 自动改写。
# 留着空列表就只是单纯采集, 屏幕上不给提示。
SEGMENTS = []

# 你手上那张 tag 的【黑框外沿】真实边长(米)。
# 仓库里 tag/tag36h11_id0_A4.svg 是按 100.0 mm 生成的 —— 打印时务必
# 【按 100% 比例、不要"适应页面"】, 打完用尺子量一下黑框外沿, 是多少就填多少。
TAG_W_M = 0.100

# 当前 FOCAL_PX 的估值: 用来在屏幕上实时显示"现在这个 tag 估出来多远",
# 方便你肉眼判断标定是否收敛。不影响采集数据。
FOCAL_PX = 277.0

# 每多少秒打一行 STAT(心跳 + fps), 0 = 关闭
STAT_EVERY_S = 5

# ------------------------------------------------------------
# 实现
# ------------------------------------------------------------

def seg_at(t):
    """t 秒时应该摆多少米。返回 (距离 或 None, 该段剩余秒数)。"""
    for a, b, d in SEGMENTS:
        if a <= t < b:
            return d, int(b - t)
    return None, 0


def side_from_corners(tg):
    """取 tag 四条边的平均长度(像素)。比 tg.w() 稳。

    为什么不用 w(): 实测 w() 返回的是检测四边形的【外接矩形宽度】,
    tag 稍微歪一点, 外接矩形就被撑大(cell=17 那档真值 136px, w() 报 159px,
    偏差 17%)。而四条边的平均长度是旋转不变的, 同样那档只差 2px。

    返回 None 表示这个固件没有 corners() 可用, 调用方应退回 w()。
    """
    try:
        cs = tg.corners()
    except Exception:
        return None
    if not cs or len(cs) < 4:
        return None
    tot = 0.0
    for i in range(4):
        x0, y0 = cs[i]
        x1, y1 = cs[(i + 1) % 4]
        tot += math.sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0))
    return tot / 4.0


def main():
    print("[TAG] AprilTag 标定采集启动")
    print("[TAG] TAG_W_M=%.4f m  FOCAL_PX(当前估值)=%.1f" % (TAG_W_M, FOCAL_PX))
    if SEGMENTS:
        print("[TAG] 分段计划:")
        for a, b, d in SEGMENTS:
            print("[TAG]   %3d~%3ds  ->  %.2f m" % (a, b, d))
    else:
        print("[TAG] 未给分段, 纯采集模式")

    lcd_ok = True
    try:
        lcd.init()
    except Exception as e:
        print("[TAG] lcd.init 失败(忽略继续):", repr(e))
        lcd_ok = False

    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    # !!! 必须 QQVGA, 见文件头说明 !!!
    sensor.set_framesize(sensor.QQVGA)
    try:
        # 官方例程要求关掉, 否则画面过曝/偏色会影响检测
        sensor.set_auto_gain(False)
        sensor.set_auto_whitebal(False)
    except Exception as e:
        print("[TAG] 关自动增益/白平衡失败(忽略):", repr(e))
    sensor.skip_frames(time=1500)

    W, H = sensor.width(), sensor.height()
    print("[TAG] 画面 %dx%d (QQVGA)" % (W, H))

    clock = time.clock()
    t0 = time.ticks_ms()
    last_stat = t0
    n_tag = 0
    n_frame = 0
    cur_seg = None

    while True:
        clock.tick()
        img = sensor.snapshot()
        el = time.ticks_diff(time.ticks_ms(), t0) / 1000.0

        # 分段提示
        if SEGMENTS:
            d, left = seg_at(el)
            if d != cur_seg:
                cur_seg = d
                if d is None:
                    print("[TAG] >>> 采集段结束")
                else:
                    print("[TAG] >>> 请把 tag 摆到 %.2f m 处" % d)

        got = 0
        try:
            tags = img.find_apriltags()
        except Exception as e:
            print("[TAG] find_apriltags 异常:", repr(e))
            tags = []

        for tg in tags:
            try:
                w = tg.w()
                h = tg.h()
                cx = tg.cx()
                cy = tg.cy()
                tid = tg.id()
            except Exception:
                continue
            got += 1
            n_tag += 1
            # 像素尺寸优先用 corners() 的平均边长(旋转不变), 拿不到才退回 w()。
            side = side_from_corners(tg)
            if side is None:
                side = float(w)
            measure = side if side > 0 else float(w)
            # 这行的格式是给 tools/fit_focal.py 的 --tag 模式吃的:
            # 它优先取 side数字, 没有才退回 h数字。别改字段名。
            print("[%6.1fs] TAG id%d side%.1f w%d h%d cx%d cy%d"
                  % (el, tid, side, w, h, cx, cy))
            if measure > 0:
                dist = FOCAL_PX * TAG_W_M / measure
                print("[%6.1fs] TAGEST id%d d%.3fm (按 FOCAL_PX=%.1f 反推, "
                      "边长用 %.1fpx)"
                      % (el, tid, dist, FOCAL_PX, measure))
            try:
                img.draw_rectangle(tg.rect(), color=(255, 0, 0))
                img.draw_cross(cx, cy, color=(0, 255, 0), size=4)
                img.draw_string(cx - 10, cy - 20, "w%d" % w,
                                color=(255, 255, 0), scale=1.0)
            except Exception:
                pass

        n_frame += 1

        # 屏幕提示
        if lcd_ok:
            try:
                if SEGMENTS:
                    d, left = seg_at(el)
                    if d is None:
                        msg = "PUT TAG AT --"
                    else:
                        msg = "PUT TAG AT %.2fm  %ds" % (d, left)
                else:
                    msg = "TAG CALIB  %.1fs" % el
                img.draw_string(2, 2, msg, color=(255, 255, 0), scale=1.0)
                img.draw_string(2, H - 12, "tags=%d fps=%.0f"
                                % (got, clock.fps()),
                                color=(0, 255, 255), scale=1.0)
                lcd.display(img)
            except Exception as e:
                print("[TAG] lcd.display 失败, 之后不再显示:", repr(e))
                lcd_ok = False

        # 心跳
        if STAT_EVERY_S and time.ticks_diff(
                time.ticks_ms(), last_stat) >= STAT_EVERY_S * 1000:
            last_stat = time.ticks_ms()
            print("[%6.1fs] STAT n_tag=%d frames=%d fps=%.1f free=%d"
                  % (el, n_tag, n_frame, clock.fps(), gc.mem_free()))

        gc.collect()


main()
