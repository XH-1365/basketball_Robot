# -*- coding: utf-8 -*-
# 真机实测: 在 WINDOW_MS 时间窗内持续扫描, 只在检出人时存图到 /flash/cap_*.jpg
# 比盲拍固定帧靠谱: 人随便什么时候走进画面都能抓到。
import gc
import os
import time

import image
import sensor

from maix import KPU

MODEL = "/flash/person_v1.kmodel"
ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

THRESHOLD = 0.55          # 实测用, 比 0.70 松一点先抓灵敏度
NMS = 0.20
HMIRROR = False           # 本板 GC2145 非镜像安装, 设 True 画面会左右反
NET_W, NET_H = 320, 256
ALERT = (107, 0, 106, 240)      # 画面中间 1/3 竖条

WINDOW_MS = 60000               # 扫描窗口 60 秒
MAX_SAVE = 6                    # 最多存 6 张
SAVE_COOLDOWN_MS = 800          # 两张之间最短间隔

C_BODY = (255, 0, 0)
C_ALERT = (255, 160, 0)
C_ZONE = (255, 255, 0)
C_TEXT = (0, 60, 128)

# --- 释放 main.py 占的资源, 把系统堆留给 KPU ---
try:
    import lcd
    lcd.deinit()
except Exception:
    pass
try:
    sensor.run(0)
except Exception:
    pass
gc.collect()
print("mem before model:", gc.mem_free())

k = KPU()
k.load_kmodel(MODEL)
k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
             net_w=NET_W, net_h=NET_H, layer_w=10, layer_h=8,
             threshold=THRESHOLD, nms_value=NMS, classes=1)
gc.collect()
print("model ready, mem:", gc.mem_free())

sensor.reset()
if HMIRROR:
    sensor.set_hmirror(1)
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1500)
print("sensor ready: %dx%d" % (sensor.width(), sensor.height()))

od = image.Image(size=(NET_W, NET_H))

# 清旧截图
for n in os.listdir("/flash"):
    if n.startswith("cap_") and n.endswith(".jpg"):
        try:
            os.remove("/flash/" + n)
        except Exception:
            pass

t_start = time.ticks_ms()
saved = 0
frames = 0
hits = 0
best_conf = 0.0
last_save = -99999
scanned_reported = False

print("SCAN START window=%dms" % WINDOW_MS)

while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
    img = sensor.snapshot()
    od.draw_image(img, 0, 0)
    od.pix_to_ai()
    k.run_with_output(od)
    boxes = k.regionlayer_yolo2() or []
    frames += 1

    el = time.ticks_diff(time.ticks_ms(), t_start)

    if boxes:
        hits += 1
        mx = 0
        for b in boxes:
            if b[5] > mx:
                mx = b[5]
        if mx > best_conf:
            best_conf = mx

        if saved < MAX_SAVE and time.ticks_diff(
                time.ticks_ms(), last_save) > SAVE_COOLDOWN_MS:
            img.draw_rectangle(ALERT[0], ALERT[1], ALERT[2], ALERT[3],
                               color=C_ZONE, thickness=1)
            for b in boxes:
                cx = b[0] + b[2] // 2
                hot = (ALERT[0] <= cx <= ALERT[0] + ALERT[2])
                col = C_ALERT if hot else C_BODY
                img.draw_rectangle(b[0], b[1], b[2], b[3],
                                   color=col, thickness=2)
                ly = b[1] - 14 if b[1] > 16 else b[1] + 2
                img.draw_string(b[0], ly, "%d%%" % (b[5] * 100),
                                color=col, scale=1.0)
            img.draw_string(0, 0, "t%ds N=%d" % (el // 1000, len(boxes)),
                            color=C_TEXT, scale=1.5)
            path = "/flash/cap_%02d.jpg" % saved
            try:
                img.save(path, quality=85)
                sz = os.stat(path)[6]
            except Exception as e:
                sz = -1
                print("save fail:", e)
            print("HIT t=%dms n=%d best=%.2f -> %s (%d bytes)"
                  % (el, len(boxes), mx, path, sz))
            saved += 1
            last_save = time.ticks_ms()

    # 心跳
    if frames % 30 == 0 and not boxes:
        print("scan t=%dms frames=%d hits=%d saved=%d mem=%d"
              % (el, frames, hits, saved, gc.mem_free()))
    if not scanned_reported and el > 8000 and hits == 0:
        print("NOTE 8s 内零检出(可能没人 / 光照差 / 阈值高)")
        scanned_reported = True

    gc.collect()
    time.sleep_ms(150)

# 一张都没存 -> 存一张空画面当诊断
if saved == 0:
    try:
        img = sensor.snapshot()
        img.draw_string(0, 0, "NO DETECTION", color=(255, 0, 0), scale=1.5)
        img.save("/flash/cap_none.jpg", quality=85)
        print("NO DETECTION - saved /flash/cap_none.jpg")
    except Exception as e:
        print("diag save fail:", e)

del od
try:
    del img
except Exception:
    pass
k.deinit()
del k
gc.collect()
print("SCAN DONE frames=%d fps=%.1f hits=%d saved=%d best=%.2f mem=%d"
      % (frames, frames / (WINDOW_MS / 1000.0), hits, saved, best_conf,
         gc.mem_free()))
print("files:", sorted(n for n in os.listdir("/flash")
                       if n.startswith("cap_")))
