# -*- coding: utf-8 -*-
"""
一条龙: 跑按键拍照脚本 N 秒 -> 串口日志落盘 -> 解析成图片。

用法:
  python tools/fetch_ram.py COM16 [秒数]        (秒数默认 90)

给你的操作流程:
  1) 本脚本会硬复位板子、下发 capture_ram.py, LCD 亮起后开始
  2) 【短按】板上 BOOT 键 = 拍一张。每拍一张, 板子立刻把这张图按
     512 字节分块(带块号 + 校验和 + '#' 终止符)吐回串口
  3) 拍够了, 【长按】BOOT 键 1.2 秒 = 板子把盘上所有图再吐一遍(补坏块)
     —— 就算你不长按, 时间到了板子自己收尾时也会吐一遍
  4) 本脚本自动解析, 图片落到 testimgs/caps/, 并打印每张的字节数 + 坏块统计

为什么不用 Ctrl-C 硬打断:
  打断会截断正在回传的那张图。所以本脚本把板上的 SECS 改成你要的秒数,
  让脚本【自己跑完】, 收尾时那次整体重吐就一定会执行 —— 等于每张图
  自动拿到两遍, 坏块几乎必然被覆盖。

为什么图像只能走串口(实测三条死路):
  * 写片内 /flash  -> 写几张后整板挂死在 C 层
  * 写 TF 卡       -> machine.SDCard 是空壳; 固件占着 SPI1 且自己都报
                      "sdcard no found"; 我们直接驱动 SPI1 会整板死锁
  * 板上内存盘删文件-> SPIFFS -10007, 整盘永久卡死, 只能只写不删
全程只有一个进程占用 COM16。
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 90

LOG = os.path.join(HERE, "_ram.log")
SRC = os.path.join(HERE, "capture_ram.py")
SESSION = os.path.join(HERE, "_ram_session.py")
OUTDIR = os.path.join(PROJ, "testimgs", "caps")

ANCHOR = "SECS        = 600"
AUTO_ANCHOR = "DEBUG_AUTO_SHOT_SEC = 0"
MAX_ANCHOR = "MAX_SHOTS   = 14"


def build_session():
    with io.open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
    if ANCHOR not in src:
        print("!! %s 里没找到锚点 %r, 直接用原脚本" % (SRC, ANCHOR))
        return SRC
    src = src.replace(ANCHOR, "SECS        = %d" % SECS)
    # 自测用: 不用按键, 让板子自己连拍几张(交付给用户跑时这两个环境变量不设)
    auto = os.environ.get("RAM_SELFTEST_AUTO_SHOT")
    if auto:
        src = src.replace(AUTO_ANCHOR, "DEBUG_AUTO_SHOT_SEC = %s" % auto)
        src = src.replace(MAX_ANCHOR, "MAX_SHOTS   = %s"
                          % os.environ.get("RAM_SELFTEST_MAX_SHOTS", "6"))
        print(">>> [自测] 自动连拍间隔 %ss" % auto)
    with io.open(SESSION, "w", encoding="utf-8") as f:
        f.write(src)
    return SESSION


def main():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"      # 子进程中文别用 GBK 编码

    script = build_session()
    cmd = [sys.executable, os.path.join(HERE, "live_run.py"),
           PORT, script, str(SECS + 30)]
    print(">>> 开始: 板上跑 %d 秒" % SECS)
    print(">>> 现在就按 BOOT 键拍照; 拍完长按 1.2 秒可提前收工")
    print("-" * 62)

    f = open(LOG, "wb")
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=env)
        for raw in iter(p.stdout.readline, b""):
            f.write(raw)
            sys.stdout.write(raw.decode("utf-8", "replace"))
            sys.stdout.flush()
        p.wait()
    finally:
        f.close()

    print("-" * 62)
    print(">>> 日志: %s (%d bytes)" % (LOG, os.path.getsize(LOG)))
    print(">>> 解析 ...")
    subprocess.call([sys.executable, os.path.join(HERE, "parse_stream.py"),
                     LOG, OUTDIR], env=env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
