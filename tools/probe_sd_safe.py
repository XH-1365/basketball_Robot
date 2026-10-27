# -*- coding: utf-8 -*-
# ============================================================
#  安全版 SD 状态探针 —— 【完全不碰 SPI】
#  (上一版一碰 SPI1 就整板挂死, 因为固件的 SD 任务占着 SPI1)
#
#  只回答: 固件到底有没有把卡挂上来? Python 层还能不能碰到它?
# ============================================================
import gc
import os
import sys

print("SAFE start gc_free=%d" % gc.mem_free())
print("sys.platform=%s  version=%s" % (sys.platform, sys.version))

print("根目录 / :", os.listdir("/"))
for p in ("/sd", "/sdcard", "/sd0", "/flash", "/ramdisk"):
    try:
        print("  listdir %-10s -> %s" % (p, os.listdir(p)))
    except Exception as e:
        print("  listdir %-10s -> %r" % (p, e))
    try:
        print("  statvfs %-10s -> %s" % (p, os.statvfs(p)))
    except Exception as e:
        print("  statvfs %-10s -> %r" % (p, e))

try:
    import machine
    print("machine.SDCard =", repr(machine.SDCard))
    try:
        x = machine.SDCard()
        print("  machine.SDCard() 竟然成功了:", repr(x))
    except Exception as e:
        print("  machine.SDCard() ->", repr(e))
    for attr in ("SDCard", "SPI", "reset_cause", "freq", "unique_id"):
        print("  machine.%-12s = %s" % (attr, repr(getattr(machine, attr, "<没有>"))))
except Exception as e:
    print("machine 失败:", repr(e))

try:
    import ujson
    cfg = ujson.load(open("/flash/config.json"))
    print("config.json 顶层键:", list(cfg.keys()))
    print("  board_info:", cfg.get("board_info"))
    print("  sdcard    :", cfg.get("sdcard"))
except Exception as e:
    print("config 失败:", repr(e))

print("SAFEDONE gc_free=%d" % gc.mem_free())
