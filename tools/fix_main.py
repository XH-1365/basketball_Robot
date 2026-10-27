# -*- coding: utf-8 -*-
"""
把 /flash/main.py 清成空脚本。
原因: Yahboom 固件发现 main.py 不存在会自动重新生成欢迎屏脚本,
      而它有 lcd.init() —— 会吃掉 KPU 加载 1.4MB 模型所需的系统堆。
      改内容(而不是删文件/改名)才治本。原内容备份到 main_welcome.py.bak。
"""
import gc
import os

BAK = "/flash/main_welcome.py.bak"
EMPTY = ("# 开机脚本（已清空）: 不做 lcd.init，把内存留给 KPU 模型加载\n"
         "# 原欢迎屏内容备份在 /flash/main_welcome.py.bak\n"
         "pass\n")

try:
    f = open("/flash/main.py", "r")
    src = f.read()
    f.close()
    print("当前 main.py (%d bytes), 开头: %r" % (len(src), src[:60]))

    if src.strip().startswith("# 开机脚本（已清空）"):
        print("已经是空脚本了，跳过")
    else:
        if BAK.lstrip("/") not in os.listdir("/flash"):
            f = open(BAK, "w")
            f.write(src)
            f.close()
            print("原内容已备份到", BAK)
        f = open("/flash/main.py", "w")
        f.write(EMPTY)
        f.close()
        print("main.py 已清空")
except Exception as e:
    print("处理失败:", repr(e))

print("")
print("/flash:", os.listdir("/flash"))
st = os.statvfs("/flash")
print("free: %.2f MB" % (st[3] * st[0] / 1048576.0))
gc.collect()
print("mem_free:", gc.mem_free())
