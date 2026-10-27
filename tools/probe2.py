# -*- coding: utf-8 -*-
"""探测 /flash 剩余空间、现有脚本内容、KPU.load_kmodel 用法。"""
import gc
import os
import sys

print("=== /flash 空间 ===")
try:
    st = os.statvfs("/flash")
    print("statvfs:", st)
    print("block size :", st[0])
    print("total      : %d bytes (%.2f MB)" % (st[2] * st[0], st[2] * st[0] / 1048576.0))
    print("free       : %d bytes (%.2f MB)" % (st[3] * st[0], st[3] * st[0] / 1048576.0))
except Exception as e:
    print("statvfs <ERR>", e)

print("")
print("=== /flash/main.py ===")
try:
    f = open("/flash/main.py", "r")
    src = f.read()
    f.close()
    print("size:", len(src))
    print(src[:1500])
except Exception as e:
    print("<ERR>", e)

print("")
print("=== /flash/config.json ===")
try:
    f = open("/flash/config.json", "r")
    print(f.read()[:400])
    f.close()
except Exception as e:
    print("<ERR>", e)

print("")
print("=== /flash/freq.conf ===")
try:
    f = open("/flash/freq.conf", "r")
    print(f.read()[:400])
    f.close()
except Exception as e:
    print("<ERR>", e)

print("")
print("=== KPU.load_kmodel 用法 ===")
try:
    from maix import KPU
    print(KPU.load_kmodel.__doc__)
except Exception as e:
    print("<ERR>", e)
try:
    from maix import KPU
    print("dir(KPU):", [x for x in dir(KPU) if not x.startswith("_")])
except Exception as e:
    print("<ERR>", e)

print("")
print("mem_free:", gc.mem_free())
