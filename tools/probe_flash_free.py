# -*- coding: utf-8 -*-
# 探测: 有无 flash 读写 API + 查 flash 空闲区域; 顺手把 main.py 改名
import gc
import os

print("=== 找 flash 相关接口 ===")
for name in ("flash", "machine", "Maix", "maix", "fpioa_manager"):
    try:
        mod = __import__(name)
        items = [x for x in dir(mod) if not x.startswith("_")]
        print("%-14s: %s" % (name, items))
    except Exception as e:
        print("%-14s: <ERR> %s" % (name, e))

try:
    from maix import KPU
    print("KPU attrs:", [x for x in dir(KPU) if "flash" in x.lower()])
except Exception:
    pass

print("")
print("=== 顺手处理 main.py ===")
try:
    names = os.listdir("/flash")
    if "main.py" in names:
        os.rename("/flash/main.py", "/flash/main_moon.py.bak")
        print("已改名: main.py -> main_moon.py.bak（开机不再自动跑，可随时改回）")
    else:
        print("main.py 不存在（可能已处理过）")
except Exception as e:
    print("改名失败:", e)

print("")
print("=== 试读 flash 地址（探测是否全空） ===")
addr = 0x800000     # 8MB 处
try:
    import uctypes
    # K210 flash 映射在 0x0 起，直接按物理地址读
    v = uctypes.bytearray_at(addr, 64)
    print("addr 0x%X 前 64 字节: %s" % (addr, bytes(v).hex()))
    print("全 0xFF(空):", all(b == 0xFF for b in v))
except Exception as e:
    print("uctypes 读失败:", repr(e))

for a in (0x600000, 0x700000, 0x800000, 0xC00000, 0xF00000):
    try:
        import uctypes
        v = uctypes.bytearray_at(a, 32)
        bb = bytes(v)
        print("  0x%07X: %s | 全FF=%s" % (a, bb.hex(), all(x == 0xFF for x in bb)))
    except Exception as e:
        print("  0x%07X: <ERR> %s" % (a, e))

print("")
print("listdir:", os.listdir("/flash"))
gc.collect()
print("mem_free:", gc.mem_free())
