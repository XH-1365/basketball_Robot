# -*- coding: utf-8 -*-
# 1) 查 /sd 和 /flash 挂载状态
# 2) 重新抓一帧 QVGA, 存到能写的地方, 供 PC 侧肉眼确认
import gc
import os

import image
import sensor

try:
    import machine
    machine.WDT(0, 30000).stop()
except Exception:
    pass

print("=== 挂载状态 ===")
for d in ("/", "/flash", "/sd"):
    try:
        fs = os.statvfs(d)
        print("  %-7s OK  总 %.1fMB 可用 %.1fMB  条目=%d"
              % (d, fs[0] * fs[2] / 1048576.0, fs[0] * fs[3] / 1048576.0,
                 len(os.listdir(d))))
    except Exception as e:
        print("  %-7s 失败 %r" % (d, e))

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1500)
img = sensor.snapshot()

try:
    st = img.get_statistics()
    print("=== 亮度 === mean=%d median=%d min=%d max=%d"
          % (st.mean(), st.median(), st.min(), st.max()))
except Exception as e:
    print("统计失败:", repr(e))

saved = None
for d in ("/sd", "/flash"):
    p = d + "/_look.jpg"
    try:
        img.save(p)
        print("已存 %s (%d 字节)" % (p, os.stat(p)[6]))
        saved = p
        break
    except Exception as e:
        print("存 %s 失败: %r" % (p, e))

# 取几个位置采样, 判断是"整片黑"还是"局部物体暗"
pts = [(40, 40), (160, 40), (280, 40),
       (40, 120), (160, 120), (280, 120),
       (40, 200), (160, 200), (280, 200)]
print("=== 九点采样 ===")
for (x, y) in pts:
    print("  (%3d,%3d) -> %r" % (x, y, img.get_pixel(x, y)))

print("LOOKDONE saved=%s gc free=%d" % (saved, gc.mem_free()))
