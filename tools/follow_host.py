# -*- coding: utf-8 -*-
"""
跟随链路 PC 端监听/验证工具（联调用）。

两种用法:
  1) 监听 K210 的 USB 串口(COM16), 看 [FOL>] 镜像行 -> 验证帧内容/频率正确
  2) 底盘接线联调时, 用 USB-UART 小板接 K210 扩展口(TXD=IO8/RXD=IO6),
     直收硬件 UART 的原始帧 -> 验证电平和真实发帧

用法:
  python tools/follow_host.py COM16            # 监听并解析
  python tools/follow_host.py COM16 --raw      # 原样打印所有字节
  python tools/follow_host.py COM16 --send "X" # 附加: 往对端发一行(调试回传)

会做的事:
  - 解析 K210,....*hh 帧, 校验异或, 打印状态/目标/偏角/距离
  - 统计帧率, 校验错计数
  - Ctrl-C 退出
"""
import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import follow_link  # noqa: E402  (用它的 parse_frame, 保证与板端同一份解析)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="串口号, 如 COM16")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--raw", action="store_true", help="原样打印收到的行")
    ap.add_argument("--send", default=None, help="启动时先发一行文本(调试)")
    args = ap.parse_args()

    import serial

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    print("监听 %s @%d, Ctrl-C 退出" % (args.port, args.baud))
    if args.send:
        ser.write((args.send + "\n").encode())
        print("已发送: %s" % args.send)

    buf = b""
    n_ok = n_bad = 0
    t0 = time.time()
    last_rep = t0
    last_seq = None
    while True:
        data = ser.read(256)
        if data:
            buf += data
            while b"\n" in buf:
                i = buf.index(b"\n")
                raw = buf[:i].strip()
                buf = buf[i + 1:]
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", "replace")
                except Exception:
                    line = repr(raw)
                if args.raw or not line.startswith("K210,"):
                    print("<< %s" % line)
                p = follow_link.parse_frame(line)
                if p is None:
                    if line.startswith("K210,"):
                        n_bad += 1
                        print("<< 校验/格式错误: %r" % line)
                    continue
                n_ok += 1
                gap = "" if last_seq is None else str(
                    (p["seq"] - last_seq) % 65536)
                last_seq = p["seq"]
                print("<< seq=%-5s %-1s id=%-3d err=%+6.1f deg  dist=%5s m"
                      "  [跳帧:%s]"
                      % (p["seq"], p["state"], p["tid"], p["err_deg"],
                         ("%0.2f" % p["dist_m"]) if p["dist_m"] >= 0 else "?",
                         gap))
        now = time.time()
        if now - last_rep >= 5:
            rate = n_ok / (now - t0)
            print("-- 5s 小结: 好 %d 坏 %d 平均 %.1f 帧/s"
                  % (n_ok, n_bad, rate))
            last_rep = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n退出")
