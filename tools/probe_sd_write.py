# -*- coding: utf-8 -*-
# ============================================================
#  SD 卡读写能力测试 —— /sd 已挂载, 验证能不能真的存图片
#  (不碰 machine.SPI, 只走固件 VFS 层)
# ============================================================
import gc
import os
import sys

print("SDTEST start gc_free=%d" % gc.mem_free())
print("sys.platform=%s" % sys.platform)

FSTYPE = "none"
try:
    FSTYPE = os.statvfs("/")[0]
except Exception:
    pass

# ---------- 1. 挂载状态 ----------
print("[1] 根目录:", os.listdir("/"))
try:
    st = os.statvfs("/sd")
    total = st[0] * st[2]
    free = st[0] * st[3]
    print("[1] /sd 已挂载")
    print("    f_bsize=%d f_frsize=%d blocks=%d bfree=%d namemax=%d" % (st[0], st[1], st[2], st[3], st[9]))
    print("    总容量=%d B (%.2f GB)  可用=%d B (%.2f GB)  已用=%.1f MB"
          % (total, total / 1e9, free, free / 1e9, (total - free) / 1048576.0))
except Exception as e:
    print("[1] !! /sd 打不开:", repr(e))
    print("SDTEST aborted")
    sys.exit(1)

# ---------- 2. 列目录 ----------
print("[2] listdir /sd ->", os.listdir("/sd"))

# ---------- 3. 小文件读写 ----------
PATH = "/sd/_k210_probe.txt"
PAYLOAD = "hello-k210-" * 100          # 1100 字节
print("[3] 写小文件 %s (%d 字节)" % (PATH, len(PAYLOAD)))
try:
    with open(PATH, "w") as f:
        f.write(PAYLOAD)
    print("    写入 OK")
    with open(PATH) as f:
        back = f.read()
    print("    读回 %d 字节, 一致=%s" % (len(back), back == PAYLOAD))
    os.remove(PATH)
    print("    删除 OK, 现在 /sd =", os.listdir("/sd"))
except Exception as e:
    print("    !! 失败:", repr(e))

# ---------- 4. 真·JPEG 落盘(关键!) ----------
try:
    import sensor
    import image
    print("[4] 初始化摄像头 ...")
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    try:
        sensor.set_hmirror(False)
        sensor.set_vflip(False)
    except Exception as e:
        print("    (hmirror 设置跳过: %r)" % e)
    sensor.skip_frames(time=600)

    ok = 0
    for i in (1, 2, 3):
        img = sensor.snapshot()
        p = "/sd/sdtest_%d.jpg" % i
        img.save(p, quality=90)
        try:
            sz = os.stat(p)[6]
        except Exception:
            sz = -1
        print("    shot %d -> %s  %d 字节" % (i, p, sz))
        if sz > 1000:
            ok += 1
    print("    成功 %d/3 张" % ok)
    print("    /sd 现在 =", os.listdir("/sd"))
    try:
        st2 = os.statvfs("/sd")
        used = (st2[0] * st2[2]) - (st2[0] * st2[3])
        print("    已用空间 = %.2f MB" % (used / 1048576.0))
    except Exception as e:
        print("    statvfs 失败:", repr(e))
except Exception as e:
    print("    !! 拍照落盘失败:", repr(e))

print("SDTEST done gc_free=%d" % gc.mem_free())
print("SDTESTDONE")
