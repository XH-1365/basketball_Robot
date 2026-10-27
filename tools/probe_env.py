# -*- coding: utf-8 -*-
"""轻量探测: 文件系统 + KPU API + 内存，不碰摄像头。"""
import gc
import os
import sys

print("--- sys ---")
print("platform :", sys.platform)
print("impl     :", sys.implementation)
print("mem_free :", gc.mem_free())

print("")
print("--- fs ---")
for d in ("/", "/flash", "/flash/KPU", "/flash/models", "/sd"):
    try:
        print("%-16s: %s" % (d, os.listdir(d)))
    except Exception as e:
        print("%-16s: <ERR> %s" % (d, e))

print("")
print("--- KPU API ---")
try:
    from maix import KPU
    k = KPU()
    print("has Yolo2        :", hasattr(k, "Yolo2"))
    print("has load_kmodel  :", hasattr(k, "load_kmodel"))
    print("has init_yolo2   :", hasattr(k, "init_yolo2"))
    print("has load         :", hasattr(k, "load"))
    try:
        k.deinit()
    except Exception:
        pass
    del k
    gc.collect()
except Exception as e:
    print("<ERR>", e)

print("")
print("--- lcd / sensor module ---")
for m in ("lcd", "sensor", "image", "time", "gc", "os", "ubinascii"):
    try:
        __import__(m)
        print("%-10s: OK" % m)
    except Exception as e:
        print("%-10s: <ERR> %s" % (m, e))

print("")
print("mem_free after:", gc.mem_free())
