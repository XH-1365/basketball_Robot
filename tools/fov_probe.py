# -*- coding: utf-8 -*-
"""
决定性实验: 同一个 tag、同一距离下, 分别在 QQVGA 和 QVGA 测它的像素宽度。

回答两个问题(之前全靠猜, 现在一次测死):
  Q1. set_framesize(QQVGA) 到底生效没有?      -> 打印每个阶段的 img.width()/height()
  Q2. QQVGA 是 QVGA 的"缩放"还是"中心裁剪"?    -> 看 w_qvga / w_qqvga 的比值
        比值 ≈ 2.0  -> 缩放: 同一物体在 QVGA 里像素数翻倍
        比值 ≈ 1.0  -> 裁剪: 像素比例相同, 只是视野变窄

同时给出绝对焦距:
  QQVGA 用 find_apriltags 拿 w (最准, 有自带的边界精定位)
  QVGA  用灰度阈值 + find_blobs 拿黑框外接矩形 (find_apriltags 有 64K 像素硬上限)

用法: 板子上跑这个脚本(通过 repl.py run), 全程把 tag 举在镜头正前方、
      **距离固定不动**、正对镜头、背景尽量亮(垫张白纸最好)。
输出行: PHASE / TAGW / BLOBW / ROUND / SUMMARY
"""
import gc
import machine
import time

import lcd
import sensor

TAG_MM = 90.0        # tag 黑框外沿边长 (mm) —— 用你的实际打印尺寸改这里
DIST_MM = 500.0      # 卷尺量出来的实际距离 (mm)
ROUNDS = 3           # 交替测几轮
PHASE_SEC = 5        # 每相持续秒数(够稳定出数)

# 保险: main.py 可能已经把看门狗武装上了, 先关掉, 别让它中途复位
try:
    _w = machine.WDT(0, 60000)
    _w.stop()
    print("[prep] WDT 已关闭")
except Exception as e:
    print("[prep] WDT 关闭失败:", repr(e))

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

print("FOVPROBE tag=%dmm dist=%dmm rounds=%d" % (int(TAG_MM), int(DIST_MM), ROUNDS))


def setup_framesize(fs, name):
    sensor.set_framesize(fs)
    sensor.skip_frames(time=1200)      # 先让自动增益/曝光收敛
    sensor.set_auto_gain(False)        # 再冻住(顺序反了会得到一张全黑图)
    sensor.set_auto_whitebal(False)


def measure_qqvga(sec):
    """返回 (w中位数列表, 样本数)。用 find_apriltags, 拿 tag 黑框外沿宽。"""
    setup_framesize(sensor.QQVGA, "QQVGA")
    # 关键诊断: 不管有没有检出 tag, 先把真实分辨率打出来。
    # 之前漏了这一步, 结果"set_framesize 到底生效没有"全靠猜。
    _probe = sensor.snapshot()
    print("PHASE QQVGA actual=%dx%d (期望 160x120)"
          % (_probe.width(), _probe.height()))
    ws = []
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < sec * 1000:
        img = sensor.snapshot()
        tags = img.find_apriltags(fx=138.5, fy=138.5,
                                  cx=img.width() // 2, cy=img.height() // 2)
        for t in tags:
            try:
                r = t.rect()
            except Exception:
                r = (t.x(), t.y(), t.w(), t.h())
            img.draw_rectangle(r, color=(255, 0, 0), thickness=2)
            try:
                z = t.z_translation()
            except Exception:
                z = 0.0
            ws.append(r[2])
            print("TAGW size=%dx%d id=%d w=%d h=%d cx=%d cy=%d z=%.4f"
                  % (img.width(), img.height(), t.id(), r[2], r[3],
                     t.cx(), t.cy(), z))
        img.draw_string(0, 0, "QQ %d" % len(tags), color=(255, 0, 0), scale=2.0)
        lcd.display(img)
        gc.collect()
    return ws


def find_dark_blobs(img):
    """
    找暗色块(black tag)。多路兜底, 因为不同 CanMV 版本 API 细节不同:
      1) 灰度图 + 单通道阈值 (0~80)  —— 最稳
      2) 失败则退回 RGB565 的 LAB L 阈值
    find_blobs 的 merge/margin 关键字也不是所有版本都支持, 再兜一层。
    """
    cands = []
    g = None
    try:
        g = img.to_grayscale(copy=True)
    except TypeError:
        try:
            g = img.copy()
            g.to_grayscale()
        except Exception:
            g = None
    except Exception:
        g = None
    if g is not None:
        cands.append((g, [(0, 80)]))
    cands.append((img, [(0, 70, -40, 40, -40, 40)]))

    for src, thr in cands:
        try:
            bs = src.find_blobs(thr, pixels_threshold=60,
                                area_threshold=60, merge=True, margin=8)
        except TypeError:
            try:
                bs = src.find_blobs(thr, pixels_threshold=60,
                                    area_threshold=60)
            except Exception:
                continue
        except Exception:
            continue
        if bs:
            return bs
    return []


def measure_qvga(sec):
    """返回 (w列表, 样本数)。用灰度阈值 + 最大暗块外接矩形。"""
    setup_framesize(sensor.QVGA, "QVGA")
    ws = []
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < sec * 1000:
        img = sensor.snapshot()
        blobs = find_dark_blobs(img)
        if blobs:
            b = max(blobs, key=lambda z: z.pixels())
            img.draw_rectangle(b.rect(), color=(0, 255, 0), thickness=2)
            ws.append(b.w())
            print("BLOBW size=%dx%d w=%d h=%d cx=%d cy=%d px=%d nblob=%d"
                  % (img.width(), img.height(), b.w(), b.h(),
                     b.cx(), b.cy(), b.pixels(), len(blobs)))
        else:
            print("BLOBW size=%dx%d none" % (img.width(), img.height()))
        img.draw_string(0, 0, "QV %d" % len(blobs), color=(0, 255, 0), scale=2.0)
        lcd.display(img)
        gc.collect()
    return ws


def med(xs):
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return None
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


all_qq = []
all_qv = []
for rnd in range(1, ROUNDS + 1):
    print("ROUND %d qqvga=start" % rnd)
    all_qq += measure_qqvga(PHASE_SEC)
    print("ROUND %d qvga=start" % rnd)
    all_qv += measure_qvga(PHASE_SEC)

w_qq = med(all_qq)
w_qv = med(all_qv)
print("SUMMARY n_qq=%d n_qv=%d w_qq=%s w_qv=%s"
      % (len(all_qq), len(all_qv), w_qq, w_qv))

if w_qq and w_qv:
    ratio = w_qv / w_qq
    f_qq = w_qq * DIST_MM / TAG_MM
    f_qv = w_qv * DIST_MM / TAG_MM
    print("SUMMARY ratio=%.3f  f_qqvga=%.1fpx  f_qvga=%.1fpx" %
          (ratio, f_qq, f_qv))
    if ratio > 1.7:
        print("SUMMARY verdict=DOWNSCALE (QQVGA 是 QVGA 缩放)")
    elif ratio < 1.3:
        print("SUMMARY verdict=CROP (QQVGA 是 QVGA 中心裁剪)")
    else:
        print("SUMMARY verdict=UNCLEAR ratio=%.2f (两种都不是? 再看数据)" % ratio)
else:
    print("SUMMARY 有一样没测到, 没法算。检查 tag 是否正对镜头/距离是否固定。")

try:
    print("GAIN gain_db=%.1f exp_us=%d" % (sensor.get_gain_db(),
                                           sensor.get_exposure_us()))
except Exception as e:
    print("GAIN 读取失败:", repr(e))
print("FOVPROBE DONE")
