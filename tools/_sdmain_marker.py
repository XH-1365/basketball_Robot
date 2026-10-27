# 临时标记脚本：验证固件是否优先执行 /sd/main.py
print("SDMAIN_MARKER_RAN")
try:
    import os
    print("SDMAIN listdir / =", os.listdir("/"))
    print("SDMAIN listdir /sd =", os.listdir("/sd"))
except Exception as e:
    print("SDMAIN err", repr(e))
print("SDMAIN_DONE")
