# -*- coding: utf-8 -*-
# ============================================================
#  TF 卡决定性探针 —— 不依赖官方 SD 类, 直接在 SPI 上跟卡握手
#
#  背景:
#    * 本板固件里 machine.SDCard 是【空壳】(一直报 cannot create instances)
#    * /flash/config.json 给出 sdcard 引脚: cs=34 mosi=35 sclk=32 miso=33
#      -> 说明硬件是【SPI 模式】的 SD, 四个信号线上都有的接
#    * 所以"能不能用 TF 卡"的真正答案是: 卡在物理层能不能被叫醒
#
#  本脚本做 4 件事:
#    1) 清点固件里跟 SD/SPI/VfsFat 相关的符号 (有没有现成轮子)
#    2) 读 config.json 确认引脚
#    3) 按 SD 协议的原始时序在 SPI 上调卡:
#       80 个时钟 -> CMD0 -> CMD8 -> ACMD41 -> CMD58
#       每一步都打印卡的回应, 失败在哪一步一目了然
#    4) 如果握手成功, 直接读 0 号块(分区表), 看前 16 字节
#
#  全程只读, 不写卡。不碰 flash。
# ============================================================
import gc
import os
import time

print("SD start gc_free=%d" % gc.mem_free())

# ---------- 1. 符号清点 ----------
try:
    import machine
    names = [x for x in dir(machine)]
    print("machine 里的 SD/SPI:", [x for x in names
                                 if "SD" in x.upper() or "SPI" in x.upper()])
except Exception as e:
    print("machine 清点失败:", repr(e))
print("os 里的 Vfs*:", [x for x in dir(os) if x.startswith("Vfs")])
for mod in ("sdcard", "fpioa_manager", "ustruct"):
    try:
        __import__(mod)
        print("模块 %s: 有" % mod)
    except Exception as e:
        print("模块 %s: 没有 (%r)" % (mod, e))

# ---------- 2. config.json 引脚 ----------
SD = {"cs": 34, "mosi": 35, "sclk": 32, "miso": 33}
try:
    import ujson
    cfg = ujson.load(open("/flash/config.json"))
    if "sdcard" in cfg:
        SD = cfg["sdcard"]
    print("config sdcard 引脚:", SD)
except Exception as e:
    print("读 config 失败(用默认引脚):", repr(e))

# ---------- 3. 起 SPI + CS ----------
try:
    from fpioa_manager import fm
    from maix import GPIO
    try:
        print("固件已占用的 GPIO:", fm.get_gpio_used())
    except Exception as e:
        print("get_gpio_used 不可用:", repr(e))
    fm.register(SD["cs"], fm.fpioa.GPIOHS0)
    cs = GPIO(GPIO.GPIOHS0, GPIO.OUT)
    cs.value(1)
    print("CS 就绪 (IO%d)" % SD["cs"])
except Exception as e:
    print("CS 失败:", repr(e))
    cs = None

spi = None
forms = [
    ("machine.SPI(machine.SPI.SPI1, sck=,mosi=,miso=)", lambda: machine.SPI(
        machine.SPI.SPI1, baudrate=400000, polarity=0, phase=0, bits=8,
        firstbit=machine.SPI.MSB, sck=SD["sclk"], mosi=SD["mosi"], miso=SD["miso"])),
    ("machine.SPI(1, sck=,mosi=,miso=)", lambda: machine.SPI(
        1, baudrate=400000, polarity=0, phase=0, bits=8,
        firstbit=machine.SPI.MSB, sck=SD["sclk"], mosi=SD["mosi"], miso=SD["miso"])),
    ("machine.SPI(0, sck=,mosi=,miso=)", lambda: machine.SPI(
        0, baudrate=400000, polarity=0, phase=0, bits=8,
        firstbit=machine.SPI.MSB, sck=SD["sclk"], mosi=SD["mosi"], miso=SD["miso"])),
]
for tag, fn in forms:
    try:
        spi = fn()
        print("SPI 起成功: %s" % tag)
        break
    except Exception as e:
        print("SPI 失败 %s -> %r" % (tag, e))
if spi is None:
    print("SD 结论: 这台固件起不了 SPI, 路走不通")
    print("SDDONE 0")
    raise SystemExit


def xfer(buf):
    """全双工: 发 buf, 同时收等长数据。"""
    rx = bytearray(len(buf))
    spi.write_readinto(buf, rx)
    return bytes(rx)


def xfer1(b):
    return xfer(bytes([b]))[0]


def cmd(c, arg, crc):
    """发一条 SD 命令, 返回 (R1, 后续最多 8 字节)。"""
    if cs:
        cs.value(0)
    # 命令头: 0x40|cmd, arg(4), crc
    hdr = bytes([0x40 | c, (arg >> 24) & 0xFF, (arg >> 16) & 0xFF,
                 (arg >> 8) & 0xFF, arg & 0xFF, crc])
    xfer(hdr)
    r1 = 0xFF
    n = 0
    while n < 16:
        r1 = xfer1(0xFF)
        if not (r1 & 0x80):
            break
        n += 1
    extra = xfer(b"\xff" * 8)
    if cs:
        cs.value(1)
    xfer1(0xFF)
    return r1, extra


def hexs(b):
    return " ".join("%02X" % v for v in b)


# ---------- 4. 原始 SD 时序 ----------
print("-- SD 上电时序 --")
if cs:
    cs.value(1)
xfer(b"\xff" * 12)          # 至少 74 个时钟让卡进入 SPI 模式
print("  已发 96 个时钟(CS 高)")

r1, _ = cmd(0, 0, 0x95)     # CMD0 GO_IDLE_STATE
print("  CMD0  R1=0x%02X %s" % (r1, "(卡就绪, 进了 SPI 模式)" if r1 == 0x01
                                else "(期望 0x01)"))

r1, ex = cmd(8, 0x1AA, 0x87)  # CMD8 SEND_IF_COND
print("  CMD8  R1=0x%02X R7=%s  %s" % (
    r1, hexs(ex[:4]),
    "(v2 卡且电压 OK)" if r1 == 0x01 and ex[2] == 0x01 and ex[3] == 0xAA
    else "(卡没回 R7 -> 可能是 v1 卡或没插好)"))

acmd_ok = False
for i in range(40):
    r1, _ = cmd(55, 0, 0x01)          # CMD55 APP_CMD
    if r1 > 0x01:
        print("  ACMD41 第%d次: CMD55 回了 0x%02X, 停" % (i + 1, r1))
        break
    r1, _ = cmd(41, 0x40000000, 0x77)  # ACMD41 SEND_OP_COND (HCS)
    if r1 == 0x00:
        acmd_ok = True
        print("  ACMD41 第%d次: R1=0x00 (初始化完成!)" % (i + 1))
        break
    time.sleep_ms(20)
if not acmd_ok:
    print("  ACMD41 没成功 (最后 R1=0x%02X)" % r1)

if acmd_ok:
    r1, ex = cmd(58, 0, 0x01)         # CMD58 READ_OCR
    ocr = ex[:4]
    print("  CMD58 R1=0x%02X OCR=%s" % (r1, hexs(ocr)))
    if len(ocr) == 4:
        ccs = (ocr[0] >> 6) & 1
        print("    CCS=%d -> %s" % (ccs, "SDHC/SDXC(块寻址)" if ccs
                                    else "SDSC(字节寻址)"))

    r1, _ = cmd(17, 0, 0x01)          # CMD17 READ_SINGLE_BLOCK
    # 等数据令牌 0xFE
    tok = 0xFF
    n = 0
    while n < 2000:
        tok = xfer1(0xFF)
        if tok != 0xFF:
            break
        n += 1
    if tok == 0xFE:
        blk = xfer(b"\xff" * 512)
        xfer(b"\xff" * 2)              # CRC
        print("  CMD17 读到 0 号块(前 16 字节): %s" % hexs(blk[:16]))
        sig = blk[510:512]
        print("    末 2 字节(应 55 AA): %s" % hexs(sig))
        print("  SD 结论: 卡【可以】用 SPI 读! 下一步可做 VfsFat 挂载")
    else:
        print("  CMD17 没等到数据令牌 (0x%02X), 块读失败" % tok)
else:
    print("  SD 结论: 卡【没能】完成 SPI 初始化")
    print("    可能: 卡没插好 / 卡座接触 / 引脚跟 config 不一致 / 卡是坏的")

print("SDDONE gc_free=%d" % gc.mem_free())
