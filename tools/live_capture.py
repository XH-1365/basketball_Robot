# -*- coding: utf-8 -*-
# 真机实测采样: 摄像头连拍 N 帧，每帧做人体检测+跟踪+画框，存到 /flash/cap_NN.jpg
# 采完用 tools/repl.py get 取回来直接看。
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

THRESHOLD = 0.70
NMS = 0.20
HMIRROR = True
NET_W, NET_H = 320, 256
ALERT = (107, 0, 106, 240)      # 告警区（画面中间 1/3）

CAPTURE_N = 12
INTERVAL_MS = 1500              # 帧间隔，给人走到镜头前的时间
TRACK_MAX_DIST = 70
TRACK_LOST = 6

C_BODY = (255, 0, 0)
C_ALERT = (255, 160, 0)
C_ZONE = (255, 255, 0)
C_TEXT = (0, 60, 128)

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

# --- 跟踪 ---
tracks = []
next_id = 1
total_in = 0


def track(boxes):
    global tracks, next_id, total_in
    old = tracks
    used = [False] * len(old)
    new_tracks = []
    res = []
    for b in boxes:
        cx = b[0] + b[2] // 2
        cy = b[1] + b[3] // 2
        best = -1
        best_d2 = TRACK_MAX_DIST * TRACK_MAX_DIST
        for i in range(len(old)):
            if used[i]:
                continue
            dx = old[i]["cx"] - cx
            dy = old[i]["cy"] - cy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = i
        if best >= 0:
            used[best] = True
            tid = old[best]["id"]
        else:
            tid = next_id
            next_id += 1
            total_in += 1
        new_tracks.append({"id": tid, "cx": cx, "cy": cy})
        res.append((tid, b))
    for i in range(len(old)):
        if not used[i]:
            new_tracks.append(old[i])
    tracks = new_tracks
    return res


# 清掉旧截图
for n in os.listdir("/flash"):
    if n.startswith("cap_") and n.endswith(".jpg"):
        try:
            os.remove("/flash/" + n)
        except Exception:
            pass

print("CAPTURE START (%d frames, %dms apart)" % (CAPTURE_N, INTERVAL_MS))
for i in range(CAPTURE_N):
    img = sensor.snapshot()
    od.draw_image(img, 0, 0)
    od.pix_to_ai()
    k.run_with_output(od)
    boxes = k.regionlayer_yolo2()
    bl = [[b[0], b[1], b[2], b[3], b[5]] for b in (boxes or [])]
    items = track(bl)

    # 画告警区
    img.draw_rectangle(ALERT[0], ALERT[1], ALERT[2], ALERT[3],
                       color=C_ZONE, thickness=1)
    # 画目标
    for tid, b in items:
        cx = b[0] + b[2] // 2
        cy = b[1] + b[3] // 2
        hot = (ALERT[0] <= cx <= ALERT[0] + ALERT[2] and
               ALERT[1] <= cy <= ALERT[1] + ALERT[3])
        color = C_ALERT if hot else C_BODY
        img.draw_rectangle(b[0], b[1], b[2], b[3], color=color, thickness=2)
        ly = b[1] - 14 if b[1] > 16 else b[1] + 2
        img.draw_string(b[0], ly, "#%d %d%%" % (tid, b[4] * 100),
                        color=color, scale=1.0)
    img.draw_string(0, 0, "f%02d N=%d T=%d" % (i, len(items), total_in),
                    color=C_TEXT, scale=1.5)

    path = "/flash/cap_%02d.jpg" % i
    try:
        img.save(path, quality=85)
        sz = os.stat(path)[6]
    except Exception as e:
        sz = -1
        print("save fail:", e)
    print("frame %2d: %d person(s) ids=%s size=%d"
          % (i, len(items), [t[0] for t in items], sz))
    gc.collect()
    time.sleep_ms(INTERVAL_MS)

del od, img
k.deinit()
del k
gc.collect()
print("CAPTURE DONE, mem:", gc.mem_free())
print("files:", [n for n in os.listdir("/flash") if n.startswith("cap_")])
