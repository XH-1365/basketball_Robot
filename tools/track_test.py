# -*- coding: utf-8 -*-
# 跟踪 + 告警逻辑验证: 同一张静态图连跑 10 帧
# 期望: 每帧 ID 都是 #1, 累计人次 total_in 应该是 1 (不是 10)
# 告警区设成全屏, 连跑后应触发 ALARM
import gc
import os

import image
from maix import KPU

MODEL = "/flash/person_v1.kmodel"
ANCHOR = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
          0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
          2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

SRC = "/flash/test785.jpg"
FRAMES = 10
TRACK_MAX_DIST = 70
TRACK_LOST = 8
ALERT_FRAMES = 3

try:
    import lcd
    lcd.deinit()
except Exception:
    pass
try:
    import sensor
    sensor.run(0)
except Exception:
    pass
gc.collect()

k = KPU()
k.load_kmodel(MODEL)
k.init_yolo2(ANCHOR, anchor_num=9, img_w=320, img_h=240,
             net_w=320, net_h=256, layer_w=10, layer_h=8,
             threshold=0.7, nms_value=0.2, classes=1)
print("model ready")

# --- 复刻 Tracker ---
tracks = []
next_id = 1
total_in = 0


def update(boxes):
    global tracks, next_id, total_in
    old = tracks
    used = [False] * len(old)
    new_tracks = []
    results = []
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
            hits = old[best]["hits"] + 1
            is_new = False
        else:
            tid = next_id
            next_id += 1
            hits = 1
            is_new = True
            total_in += 1
        new_tracks.append({"id": tid, "cx": cx, "cy": cy, "hits": hits, "lost": 0})
        results.append((tid, is_new, hits))
    for i in range(len(old)):
        if not used[i]:
            t = old[i]
            t["lost"] += 1
            if t["lost"] <= TRACK_LOST:
                new_tracks.append(t)
    tracks = new_tracks
    return results


# 告警区 = 全屏, 必触发
zone_hits = 0
alarms = 0
ids_seen = []

od = image.Image(size=(320, 256))
img = image.Image(SRC)
print("source %dx%d" % (img.width(), img.height()))

for f in range(FRAMES):
    od.draw_image(img, 0, 0)
    od.pix_to_ai()
    k.run_with_output(od)
    boxes = k.regionlayer_yolo2()
    boxes = [[b[0], b[1], b[2], b[3], b[5]] for b in (boxes or [])]
    res = update(boxes)
    ids = [r[0] for r in res]
    ids_seen.append(ids)
    if len(res) > 0:
        zone_hits += 1
    if zone_hits >= ALERT_FRAMES:
        alarms += 1
        zone_hits = 0
    print("frame %2d: boxes=%d ids=%s total_in=%d" % (f, len(boxes), ids, total_in))

k.deinit()
del od, img
gc.collect()

print("")
print("=== TRACK TEST ===")
print("ids per frame :", ids_seen)
print("total_in      :", total_in)
first = ids_seen[0]
stable = all(x == first for x in ids_seen)
print("ID 稳定       :", stable)
print("累计人次正确  :", total_in == len(first))
print("ALARM 触发次数:", alarms)
print("PASS" if (stable and total_in == len(first) and alarms > 0) else "FAIL")
