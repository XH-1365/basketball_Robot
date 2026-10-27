# -*- coding: utf-8 -*-
# 清理: 列出 /flash、删掉不完整的 head_v1.kmodel、报告剩余空间
import gc
import os

print("=== /flash 内容 ===")
for n in os.listdir("/flash"):
    try:
        print("  %-26s %d bytes" % (n, os.stat("/flash/" + n)[6]))
    except Exception as e:
        print("  %-26s <ERR> %s" % (n, e))

stv = os.statvfs("/flash")
print("")
print("total: %.2f MB   free: %.2f MB"
      % (stv[2] * stv[0] / 1048576.0, stv[3] * stv[0] / 1048576.0))

# 删掉残留的 head 模型（没传完的）
for name in ("head_v1.kmodel",):
    if name in os.listdir("/flash"):
        try:
            os.remove("/flash/" + name)
            print("removed:", name)
        except Exception as e:
            print("remove fail:", name, e)

gc.collect()
stv = os.statvfs("/flash")
print("")
print("=== 清理后 ===")
print("listdir:", os.listdir("/flash"))
print("free: %.2f MB" % (stv[3] * stv[0] / 1048576.0))
print("mem_free:", gc.mem_free())
