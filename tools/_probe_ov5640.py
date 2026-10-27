# -*- coding: utf-8 -*-
# OV5640 四探：关 AE 强制长曝光，看亮度能否救回来
import sensor, image, time

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

def luma_now():
    img = sensor.snapshot()
    st = img.get_statistics()
    return img, st.l_mean(), st.l_min(), st.l_max()

# 先关自动增益/曝光（OV 系列常见做法）
for exp_us in (30000, 50000, 70000):
    try:
        sensor.set_auto_exposure(False, exposure_us=exp_us)
        sensor.skip_frames(time=1200)
        img, m, lo, hi = luma_now()
        print("[P4] exp=%dus -> luma %d/%d/%d" % (exp_us, m, lo, hi))
    except Exception as e:
        print("[P4] exp=%dus err %r" % (exp_us, e))
        break

# 恢复 AE 收尾
try:
    sensor.set_auto_exposure(True)
    sensor.skip_frames(time=1500)
    img, m, lo, hi = luma_now()
    print("[P4] AE back -> luma %d/%d/%d" % (m, lo, hi))
except Exception as e:
    print("[P4] AE back err %r" % (e,))

img.save("/sd/probe4.jpg")
print("[P4] DONE")
