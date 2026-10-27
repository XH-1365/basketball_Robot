# -*- coding: utf-8 -*-
"""精确诊断: 大块内存分配 / 小文件读 / 大文件读校验 / load_kmodel 分段测。"""
import gc
import os

import image
from maix import KPU

print("gc free:", gc.mem_free())

print("")
print("[1] 大块内存分配测试 (2MB)")
try:
    im = image.Image(size=(1024, 1024))
    print("    alloc OK: %dx%d" % (im.width(), im.height()))
    del im
    gc.collect()
except Exception as e:
    print("    alloc FAIL:", repr(e))

print("")
print("[2] 小文件读取 (/flash/test785.jpg 16KB)")
try:
    f = open("/flash/test785.jpg", "rb")
    n = 0
    while True:
        d = f.read(4096)
        if not d:
            break
        n += len(d)
    f.close()
    print("    ok, %d bytes" % n)
except Exception as e:
    print("    FAIL at %d:" % n, repr(e))

print("")
print("[3] 大文件读取校验 (/flash/person_v1.kmodel 1.4MB)")
n = 0
acc = 0
try:
    f = open("/flash/person_v1.kmodel", "rb")
    while True:
        d = f.read(8192)
        if not d:
            break
        n += len(d)
        for b in d:
            acc = (acc + b) & 0xFFFFFFFF
    f.close()
    print("    read ok: %d bytes, cksum=%d (期望 1463728 / 161167812)" % (n, acc))
except Exception as e:
    print("    FAIL at %d bytes:" % n, repr(e))

print("")
print("[4] 分段 load 测试")
gc.collect()
print("    gc free before:", gc.mem_free())
k = KPU()
try:
    k.load_kmodel("/flash/person_v1.kmodel")
    print("    load_kmodel OK")
    try:
        k.deinit()
    except Exception:
        pass
except Exception as e:
    print("    load_kmodel FAIL:", repr(e))
del k
gc.collect()
print("    gc free after:", gc.mem_free())

print("")
print("[5] 磁盘剩余")
st = os.statvfs("/flash")
print("    free %.2f MB" % (st[3] * st[0] / 1048576.0))
