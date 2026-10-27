# -*- coding: utf-8 -*-
"""直接读 F: 卷的引导扇区, 解析 FAT32 BPB 参数(只读)。"""
import struct

f = open(r"\\.\F:", "rb")
bs = f.read(512)
f.close()


def u16(off):
    return struct.unpack_from("<H", bs, off)[0]


def u32(off):
    return struct.unpack_from("<I", bs, off)[0]


print("前 3 字节(跳转) :", bs[0:3].hex())
print("OEM             :", repr(bs[3:11]))

bps = u16(11)                 # 每扇区字节数
spc = bs[13]                  # 每簇扇区数
res = u16(14)                 # 保留扇区
nfat = bs[16]                 # FAT 表个数
rootent = u16(17)             # 根目录条目数
tot16 = u16(19)               # 总扇区数(16 位)
media = bs[21]                # 介质描述
fatsz16 = u16(22)             # FAT 大小(16 位)
hidden = u32(28)              # 隐藏扇区
tot32 = u32(32)               # 总扇区数(32 位)
fatsz32 = u32(36)             # FAT 大小(32 位)
extflags = u16(40)
ver = u16(42)
rootclus = u32(44)
fsinfo = u16(48)
bkbs = u16(50)
volid = u32(67)
label = bs[71:82]
fstype = bs[82:90]
sig = u16(510)

print("每扇区字节      :", bps)
print("每簇扇区数      :", spc, "-> 簇大小", bps * spc, "字节")
print("保留扇区        :", res)
print("FAT 个数        :", nfat)
print("根目录条目数    :", rootent, "(FAT32 应为 0)")
print("总扇区(16)      :", tot16, "(FAT32 应为 0)")
print("介质描述        : 0x%02X" % media)
print("FAT 大小(16)    :", fatsz16, "(FAT32 应为 0)")
print("隐藏扇区        :", hidden)
print("总扇区(32)      :", tot32, "->", tot32 * bps, "字节")
print("FAT 大小(32)    :", fatsz32, "扇区")
print("扩展标志/版本   : 0x%04X / 0x%04X" % (extflags, ver))
print("根目录簇号      :", rootclus)
print("FSInfo 扇区     :", fsinfo)
print("备份引导扇区    :", bkbs)
print("卷序列号        : 0x%08X" % volid)
print("卷标            :", repr(label))
print("文件系统类型串  :", repr(fstype))
print("尾签名          : 0x%04X (小端读, 0x55AA 应为 0xAA55) %s" % (sig, "OK" if sig == 0xAA55 else "缺失!"))

if fatsz32:
    datasec = tot32 - res - nfat * fatsz32
    print("数据区扇区      :", datasec)
    print("总簇数(约)      :", datasec // spc)
    print("=> 这是一个 %s 的 FAT32 卷" % ("合法" if bps == 512 and spc and datasec > 0 else "可疑"))
