# -*- coding: utf-8 -*-
"""
SD 卡挂载探测。config.json 给出的 SPI 引脚: cs=34 mosi=35 sclk=32 miso=33。
逐个试 machine.SDCard 的几种构造姿势, 把报错原样打出来(报错本身就是线索)。
本脚本不写任何文件, 只尝试挂载和列目录。
"""
import os
import machine

print("--- SD 探测开始 ---")


def show(tag, fn):
    try:
        v = fn()
        print("OK  ", tag, "->", v)
        return v
    except Exception as e:
        print("FAIL", tag, "->", repr(e))
        return None


# 0. 现状
show("listdir('/')", lambda: os.listdir("/"))

# 1. 先看 SPI 类怎么用
show("SPI.SPI0", lambda: machine.SPI.SPI0)
show("SPI.SPI1", lambda: machine.SPI.SPI1)

# 2. 各种构造尝试
sd = None
cands = [
    ("SDCard(0, 34)", lambda: machine.SDCard(0, 34)),
    ("SDCard(spi0, 34)", lambda: machine.SDCard(machine.SPI(0), 34)),
    ("SDCard(0)", lambda: machine.SDCard(0)),
    ("SDCard()", lambda: machine.SDCard()),
    ("SDCard(1, 34)", lambda: machine.SDCard(1, 34)),
    ("SDCard(sck=32,mosi=35,miso=33,cs=34)",
     lambda: machine.SDCard(sck=32, mosi=35, miso=33, cs=34)),
    ("SDCard(0, 1, 34)", lambda: machine.SDCard(0, 1, 34)),
]
for name, fn in cands:
    v = show(name, fn)
    if v is not None:
        sd = v
        break

# 3. 挂载
if sd is not None:
    show("mount -> /sd", lambda: os.mount(sd, "/sd"))
    show("listdir('/')", lambda: os.listdir("/"))
    show("listdir('/sd')", lambda: os.listdir("/sd"))
    try:
        s = os.statvfs("/sd")
        print("OK   statvfs /sd  FREE", s[0] * s[3], "TOTAL", s[0] * s[2])
    except Exception as e:
        print("FAIL statvfs /sd ->", repr(e))
else:
    print("!! 所有构造方式都失败, 拿不到 SDCard 对象")

print("--- SD 探测结束 ---")
