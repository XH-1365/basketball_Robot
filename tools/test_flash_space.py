# -*- coding: utf-8 -*-
"""写入测试: /flash 能否容纳 1.4MB 单文件（人体模型大小）。测完自动删除。"""
import gc
import os

TARGET = "/flash/_spacetest.bin"
SIZE = 1463728
CHUNK = 4096

print("目标文件:", TARGET, "大小:", SIZE)

try:
    f = open(TARGET, "wb")
    chunk = b"\x00" * CHUNK
    written = 0
    n = SIZE // CHUNK
    for i in range(n):
        f.write(chunk)
        written += CHUNK
    rest = SIZE - written
    if rest:
        f.write(b"\x00" * rest)
        written += rest
    f.close()
    print("写入完成:", written, "bytes")

    st = os.stat(TARGET)
    print("os.stat  :", st)
    print("实际大小 :", st[6])

    stv = os.statvfs("/flash")
    print("写入后 statvfs:", stv)
    print("剩余: %.2f MB" % (stv[3] * stv[0] / 1048576.0))
    print("RESULT: OK —— /flash 可以放 1.4MB 文件")
except Exception as e:
    print("RESULT: FAIL ->", repr(e))
    try:
        stv = os.statvfs("/flash")
        print("statvfs:", stv)
    except Exception:
        pass
finally:
    try:
        os.remove(TARGET)
        print("已删除测试文件")
        print("删除后 /flash:", os.listdir("/flash"))
    except Exception as e:
        print("删除失败:", e)

gc.collect()
print("mem_free:", gc.mem_free())
