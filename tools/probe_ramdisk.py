# -*- coding: utf-8 -*-
# ============================================================
#  内存盘容量探针（决定性实验）
#  目标: 回答 3 个问题
#     Q1 能申请多大的内存盘? (256K / 512K / 768K / 1M 逐个试)
#     Q2 每种大小能存多少张 ~17KB 的 JPEG? (第一张失败就停)
#     Q3 "环形删除"(只留最近 N 张, 删最老的) 能否撑住 12 次写?
#  全程只用 RAM, 不碰 flash。
# ============================================================
import gc
import os
import time

print("BOOT gc_free=%d gc_alloc=%d" % (gc.mem_free(), gc.mem_alloc()))

JPEG_BYTES = 17000          # 造一张假 JPEG 的字节数(跟实测 17KB 一致)
KEEP = 3                    # 环形保留张数


def mk_jpeg(n):
    d = bytearray()
    d += b"\xff\xd8\xff\xe0" + b"x" * 8
    x = 12345
    while len(d) < n - 2:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        d.append(x & 0xFF)
    d += b"\xff\xd9"
    return bytes(d)


class RAMFlashDev(object):
    def __init__(self, size):
        self.fs_size = size
        self.fs_data = bytearray(size)
        self.erase_block = 32 * 1024
        self.log_block_size = 64 * 1024
        self.log_page_size = 4 * 1024

    def read(self, buf, size, addr):
        for i in range(len(buf)):
            buf[i] = self.fs_data[addr + i]

    def write(self, buf, size, addr):
        for i in range(len(buf)):
            self.fs_data[addr + i] = buf[i]

    def erase(self, size, addr):
        for i in range(size):
            self.fs_data[addr + i] = 0xff


def try_mount(size):
    """尝试挂载指定大小的内存盘, 成功返回 (vfs, blk, free_before)。"""
    free_before = gc.mem_free()
    try:
        blk = RAMFlashDev(size)
    except Exception as e:
        print("  Q1 size=%dK 分配失败 %r" % (size // 1024, e))
        return None
    gc.collect()
    try:
        vfs = os.VfsSpiffs(blk)
        try:
            vfs.mkfs(vfs)
        except Exception:
            pass
        os.mount(vfs, "/ramdisk")
        os.listdir("/ramdisk")
    except Exception as e:
        print("  Q1 size=%dK 挂载失败 %r" % (size // 1024, e))
        del blk
        gc.collect()
        return None
    free_after = gc.mem_free()
    print("  Q1 size=%dK 挂载OK  占用堆=%d  剩余堆=%d"
          % (size // 1024, free_before - free_after, free_after))
    return blk


def svfs(tag):
    try:
        v = os.statvfs("/ramdisk")
        print("     statvfs %s: %s" % (tag, v))
    except Exception as e:
        print("     statvfs %s 不可用: %r" % (tag, e))


def write_n(tag, blob, n):
    """连续写 n 张, 返回成功张数。第一张失败就停(重现之前的现象)。"""
    ok = 0
    for i in range(n):
        p = "/ramdisk/w_%02d.jpg" % i
        try:
            f = open(p, "wb")
            f.write(blob)
            f.close()
        except Exception as e:
            print("     %s 第%d张 open/write 失败: %r" % (tag, i + 1, e))
            break
        try:
            sz = os.stat(p)[6]
        except Exception as e:
            print("     %s 第%d张 stat 失败: %r" % (tag, i + 1, e))
            break
        if sz != len(blob):
            print("     %s 第%d张 长度不对 %d != %d" % (tag, i + 1, sz, len(blob)))
            break
        ok += 1
    return ok


def wipe():
    try:
        for n in os.listdir("/ramdisk"):
            try:
                os.remove("/ramdisk/" + n)
            except Exception:
                pass
    except Exception:
        pass


def main():
    blob = mk_jpeg(JPEG_BYTES)
    print("假 JPEG %d bytes" % len(blob))

    # ---- Q1 + Q2 ----
    for kb in (256, 512, 768, 1024, 1536):
        print("-- 试 %dK --" % kb)
        blk = try_mount(kb * 1024)
        if blk is None:
            continue
        wipe()
        svfs("空盘")
        n = write_n("%dK" % kb, blob, 20)
        print("  Q2 %dK 能连写 %d 张 (~%d KB 数据)" % (kb, n, n * len(blob) // 1024))
        svfs("写满后")
        # ---- Q3 环形删除 ----
        wipe()
        gc.collect()
        fails = 0
        for i in range(12):
            p = "/ramdisk/r_%02d.jpg" % i
            try:
                f = open(p, "wb")
                f.write(blob)
                f.close()
                if os.stat(p)[6] != len(blob):
                    fails += 1
            except Exception as e:
                print("  Q3 第%d次写失败: %r" % (i + 1, e))
                fails += 1
            # 删掉比对旧的
            if i >= KEEP:
                old = "/ramdisk/r_%02d.jpg" % (i - KEEP)
                try:
                    os.remove(old)
                except Exception as e:
                    print("  Q3 删 %s 失败: %r" % (old, e))
        left = os.listdir("/ramdisk")
        print("  Q3 环形(KEEP=%d) 12 次写: 失败 %d 次, 盘上剩 %d 个" %
              (KEEP, fails, len(left)))
        svfs("环形后")
        # 卸载
        try:
            os.umount("/ramdisk")
        except Exception as e:
            print("  umount 失败: %r" % e)
        del blk
        gc.collect()
        print("  卸载后剩余堆=%d" % gc.mem_free())

    print("PROBEDONE")


main()
