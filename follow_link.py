# -*- coding: utf-8 -*-
"""
K210 -> 底盘(下位机) 跟随链路模块。部署时随 body_detect.py 一起推到
/flash 和 /sd（与 main.py 同目录, import 才能找到）。

职责分三层:
  1) 纯逻辑(无板端依赖, PC 可直接 import 单测):
       xor_cs / build_frame / parse_frame / FollowState
  2) 板端串口 FollowLink: 扩展口硬件 UART(丝印 TXD=IO8 / RXD=IO6),
       TX 周期发跟随帧, RX 非阻塞收底盘回传并限速回显到 USB 串口
  3) 协议: 一行文本 + 异或校验, 见 docs/底盘跟随串口协议.md
       K210,<seq>,<state>,<id>,<err_deg>,<dist_m>*<hh>\\n
     state: L=锁定跟踪  S=画面里没人(底盘应停转)  X=视觉不可用
     err_deg: 人相对画面中心的水平偏角(度), 正=人在画面右侧 -> 底盘右转(顺时针)
     dist_m:  HEIGHT 法估距(米), 未知为 -1

注意: 本模块刻意不用 f-string、不用 ticks_ms 之外的板端 API 出现在纯逻辑层。
"""
import time

# ---------------------------------------------------------------- 纯逻辑


def xor_cs(s):
    """异或校验: 对字符串每个字符的 ord 逐个异或, 返回两位小写 hex。"""
    c = 0
    for ch in s:
        c ^= ord(ch)
    return "%02x" % c


def build_frame(seq, state, tid, err_deg, dist_m):
    """构造一帧跟随报文(带 \\n 结尾)。

    seq     : 帧序号(自动 & 0xFFFF)
    state   : 'L' / 'S' / 'X'
    tid     : 锁定目标 id, 无目标时 0
    err_deg : 水平偏角(度), 正=人在画面右侧
    dist_m  : 距离(米)或 None(未知 -> 发 -1)
    """
    if dist_m is None:
        ds = "-1"
    else:
        ds = "%.2f" % dist_m
    body = "K210,%d,%s,%d,%.1f,%s" % (seq & 0xFFFF, state, tid, err_deg, ds)
    return "%s*%s\n" % (body, xor_cs(body))


def parse_frame(line):
    """解析一帧(容忍首尾空白与 \\r)。校验失败/字段异常返回 None。

    返回 dict: {seq, state, tid, err_deg, dist_m}
    """
    line = line.strip()
    if not line or "*" not in line:
        return None
    body, cs = line.rsplit("*", 1)
    if xor_cs(body) != cs.lower():
        return None
    p = body.split(",")
    if len(p) != 6 or p[0] != "K210":
        return None
    try:
        seq = int(p[1])
        state = p[2]
        tid = int(p[3])
        err_deg = float(p[4])
        dist_m = float(p[5])
    except Exception:
        return None
    if state not in ("L", "S", "X"):
        return None
    return {"seq": seq, "state": state, "tid": tid,
            "err_deg": err_deg, "dist_m": dist_m}


class FollowState(object):
    """目标锁定状态机(纯逻辑)。

    update(items, cam_cx, vision_ok) -> (state, tid, err_px, dist_m)
      items   : body_detect 的跟踪结果 [(tid, b, is_new, hits, dist, dmode)]
                b = (x, y, w, h)
      cam_cx  : 画面中心 x(像素)
      vision_ok: False = 模型没加载(预览模式) -> 发 'X'

    锁定规则:
      - 上一帧锁定的 id 还在 -> 继续锁它(人不换目标)
      - 不在 -> 选中心最接近画面中心的那个
      - 连续 lost_frames 帧没看到任何人 -> 放弃锁定, 重新选人时再定
    """

    def __init__(self, lost_frames=5):
        self.lost_frames = lost_frames
        self.locked = None
        self.gap = 0
        self.switches = 0        # 换锁次数(统计/调试用)

    def update(self, items, cam_cx, vision_ok=True):
        if not vision_ok:
            self.locked = None
            self.gap = 0
            return ("X", 0, 0.0, None)

        if not items:
            self.gap += 1
            if self.gap > self.lost_frames:
                self.locked = None
            return ("S", 0, 0.0, None)
        self.gap = 0

        pick = None
        if self.locked is not None:
            for it in items:
                if it[0] == self.locked:
                    pick = it
                    break
        if pick is None:
            best = None
            for it in items:
                b = it[1]
                d = abs(b[0] + b[2] // 2 - cam_cx)
                if best is None or d < best[0]:
                    best = (d, it)
            pick = best[1] if best is not None else None
        if pick is None:
            return ("S", 0, 0.0, None)

        if pick[0] != self.locked:
            self.switches += 1
        self.locked = pick[0]
        b = pick[1]
        err_px = (b[0] + b[2] // 2) - cam_cx
        return ("L", pick[0], err_px, pick[4])


# ---------------------------------------------------------------- 板端串口


class FollowLink(object):
    """扩展口 UART 收发。只在板上实例化(PC 没有 machine/fpioa_manager)。

    用法(board 端):
        fol = FollowLink(2, 8, 6, 115200, mirror=True)
        n = fol.send(line)     # 发一帧, 返回写入字节数(<=0 为异常)
        fol.poll()             # 非阻塞收底盘回传, 收到行会限速打印 [CHAS]
    """

    def __init__(self, uart_id=2, tx_io=8, rx_io=6, baud=115200,
                 mirror=True, echo_ms=500):
        from machine import UART
        import fpioa_manager as _fmm

        fm = _fmm.fm
        fm.register(tx_io, getattr(fm.fpioa, "UART%d_TX" % uart_id))
        fm.register(rx_io, getattr(fm.fpioa, "UART%d_RX" % uart_id))
        self.uart = UART(getattr(UART, "UART%d" % uart_id), baud)
        self.mirror = mirror
        self.echo_ms = echo_ms
        self.sent = 0          # 已发帧数
        self.wr_errs = 0       # write 异常次数
        self.rx_bytes = 0
        self.rx_lines = 0
        self.buf = b""
        self.last_echo = 0
        self.last_line = ""

    def send(self, line):
        """发一帧(\\n 结尾的 str), 返回写入字节数, 异常返回 -1。"""
        try:
            n = self.uart.write(line.encode())
        except Exception:
            self.wr_errs += 1
            return -1
        if n is not None and n > 0:
            self.sent += 1
        else:
            self.wr_errs += 1
        return n if n is not None else -1

    def poll(self):
        """非阻塞收底盘回传。完整行限速回显 [CHAS], 便于确认链路通。"""
        try:
            n = self.uart.any()
            if not n:
                return
            data = self.uart.read(n)
        except Exception:
            return
        if not data:
            return
        self.rx_bytes += len(data)
        self.buf += data
        if len(self.buf) > 512:            # 防御: 底盘狂刷但没换行
            self.buf = self.buf[-256:]
        while True:
            i = self.buf.find(b"\n")
            if i < 0:
                break
            raw = self.buf[:i].strip()
            self.buf = self.buf[i + 1:]
            if not raw:
                continue
            self.rx_lines += 1
            try:
                line = raw.decode()
            except Exception:
                line = repr(raw)
            now = time.ticks_ms()
            if (line != self.last_line or
                    time.ticks_diff(now, self.last_echo) >= self.echo_ms):
                if self.mirror:
                    print("[CHAS] %s" % line)
                self.last_echo = now
                self.last_line = line
