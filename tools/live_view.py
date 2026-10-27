# -*- coding: utf-8 -*-
"""
棋盘格采集 + PC 端实时画面（串口传帧 -> 本地网页）

板端还是 tools/shot_chess.py, 只是本脚本下发前把它里面的
PREVIEW_FRAMES 改成 True, 于是每 250ms 会额外吐一帧小 JPEG。
本脚本收下来, 起一个本地 HTTP 服务, 用浏览器就能看实时画面。

用法:
  python tools/live_view.py                 # 自动找串口, 端口 8823
  python tools/live_view.py COM16 --port 8823

浏览器看:
  http://127.0.0.1:8823/            实时画面(MJPEG)
  http://127.0.0.1:8823/snap.jpg    当前这一帧的静态图
  http://127.0.0.1:8823/stat        帧数/大小等状态

板上 BOOT 键照常拍照, 存 /sd/chess_NN.jpg, 拍满 25 张脚本自己结束。
"""
import argparse
import io
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import repl as R  # noqa: E402

BOARD_SCRIPT = os.path.join(HERE, "shot_chess.py")

_state = {
    "frame": None,      # bytes: 最新一帧 JPEG
    "seq": 0,
    "size": 0,
    "t": 0.0,
    "lines": [],        # 最近的板端日志行
}
_lock = threading.Lock()
_stop = threading.Event()


def load_board_src():
    """读板端脚本, 把配置区的 PREVIEW_FRAMES 掰成 True。

    锚点必须锚行首: 脚本里 main() 的异常处理里也有一句
    `PREVIEW_FRAMES = False`(带缩进), 不锚行首会命中两次。
    """
    raw = io.open(BOARD_SCRIPT, "r", encoding="utf-8").read()
    pat = re.compile(r"(?m)^PREVIEW_FRAMES = False[ \t]*$")
    n = len(pat.findall(raw))
    assert n == 1, "配置区锚点命中 %d 次(应 1)" % n
    out = pat.sub("PREVIEW_FRAMES = True", raw, count=1)

    # 回归护栏: 函数体内绝不能再出现 `PREVIEW_FRAMES = ...`
    # 一旦出现, Python 会把它当局部变量 -> 上面读它的地方 NameError 直接崩板。
    # 这个坑真实踩过, 所以这里堵死。
    bad = re.findall(r"(?m)^[ \t]+PREVIEW_FRAMES\s*=", out)
    assert not bad, "板端脚本里还有缩进的 PREVIEW_FRAMES 赋值, 会 NameError: %r" % bad
    return out


def reader_loop(s):
    """解析板端 stdout: FRM<len>\\n<b64>\\n, 其它行当普通日志。"""
    buf = ""
    need = 0
    t0 = time.time()
    while not _stop.is_set():
        try:
            n = s.in_waiting
            if not n:
                time.sleep(0.02)
                continue
            buf += s.read(n).decode("utf-8", "replace")
        except Exception:
            break

        while True:
            if need > 0:
                if len(buf) < need:
                    break
                payload = buf[:need]
                buf = buf[need:]
                try:
                    import base64
                    jpg = base64.b64decode(payload)
                    with _lock:
                        _state["frame"] = jpg
                        _state["seq"] += 1
                        _state["size"] = len(jpg)
                        _state["t"] = time.time()
                except Exception as e:
                    _log("[PC] 解帧失败: %r" % e)
                need = 0
                # 吃掉正文后的那个换行
                nl = buf.find("\n")
                if nl >= 0:
                    buf = buf[nl + 1:]
                continue

            nl = buf.find("\n")
            if nl < 0:
                break
            line = buf[:nl].strip("\r")
            buf = buf[nl + 1:]
            m = re.match(r"^FRM(\d+)$", line)
            if m:
                need = int(m.group(1))
                continue
            if line:
                _log(line)


def _log(line):
    with _lock:
        _state["lines"].append(line)
        if len(_state["lines"]) > 200:
            _state["lines"] = _state["lines"][-200:]
    print(line)
    sys.stdout.flush()


PAGE = u"""<!doctype html><html><head><meta charset="utf-8">
<title>K210 live</title>
<style>
 body{margin:0;background:#111;color:#ddd;font:13px/1.5 system-ui,sans-serif}
 .bar{padding:8px 12px;background:#1b1b1b;border-bottom:1px solid #333}
 .wrap{padding:12px}
 img{display:block;image-rendering:pixelated;background:#000;
     border:1px solid #333;max-width:100%}
 .m{color:#888}
</style></head><body>
<div class="bar">K210 摄像头实时画面 &nbsp;<span class="m" id="s">等待第一帧…</span></div>
<div class="wrap"><img id="v" src="/stream.mjpg" width="640" alt="camera"></div>
<script>
var img=document.getElementById('v'),s=document.getElementById('s');
var t0=Date.now(),n=0,useMjpeg=true,_seq=0;
img.onload=function(){n++;};
img.onerror=function(){
  if(useMjpeg){useMjpeg=false;s.textContent='MJPEG 不可用，改用逐帧刷新';}
};
setInterval(function(){
  var dt=(Date.now()-t0)/1000;
  var fps=n/dt;n=0;t0=Date.now();
  if(!useMjpeg){img.src='/snap.jpg?t='+Date.now();}
  s.textContent='已收 '+_seq+' 帧   约 '+fps.toFixed(1)+' fps';
},1000);
setInterval(function(){
  fetch('/stat').then(function(r){return r.text()}).then(function(t){
    var m=t.match(/seq=(\\d+)/); if(m){_seq=+m[1];}
  }).catch(function(){});
},1000);
</script></body></html>
"""


def make_server(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _hdr(self, code, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            if extra:
                for k, v in extra:
                    self.send_header(k, v)
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                b = PAGE.encode("utf-8")
                self._hdr(200, "text/html; charset=utf-8",
                          [("Content-Length", str(len(b)))])
                self.wfile.write(b)
                return
            if path == "/stat":
                with _lock:
                    txt = ("seq=%d size=%d age=%.2f lines=%d\n"
                           % (_state["seq"], _state["size"],
                              time.time() - _state["t"] if _state["t"] else -1,
                              len(_state["lines"])))
                b = txt.encode()
                self._hdr(200, "text/plain; charset=utf-8",
                          [("Content-Length", str(len(b)))])
                self.wfile.write(b)
                return
            if path == "/snap.jpg":
                with _lock:
                    f = _state["frame"]
                if not f:
                    self._hdr(503, "text/plain")
                    self.wfile.write(b"no frame yet")
                    return
                self._hdr(200, "image/jpeg", [("Content-Length", str(len(f)))])
                self.wfile.write(f)
                return
            if path == "/stream.mjpg":
                self._hdr(200, "multipart/x-mixed-replace; boundary=frame")
                last = -1
                try:
                    while not _stop.is_set():
                        with _lock:
                            f = _state["frame"]
                            seq = _state["seq"]
                        if not f or seq == last:
                            time.sleep(0.03)
                            continue
                        last = seq
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            b"Content-Length: %d\r\n\r\n" % len(f))
                        self.wfile.write(f)
                        self.wfile.write(b"\r\n")
                except Exception:
                    pass
                return
            self._hdr(404, "text/plain")
            self.wfile.write(b"not found")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    return srv


def pick_port(want=None):
    import serial.tools.list_ports as lp
    ports = list(lp.comports())
    if want:
        for p in ports:
            if p.device.upper() == want.upper():
                return p.device
        raise SystemExit("!! 找不到串口 %s, 当前: %s"
                         % (want, [p.device for p in ports] or "无"))
    hits = [p for p in ports
            if "CH340" in (p.description or "").upper()
            or "USB-SERIAL" in (p.description or "").upper()]
    if len(hits) == 1:
        print(">>> 自动识别到板子: %s" % hits[0].device)
        return hits[0].device
    raise SystemExit("!! 板子串口不确定: %s"
                     % [(p.device, p.description) for p in hits])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default=None)
    ap.add_argument("--http-port", type=int, default=8823)
    ap.add_argument("--seconds", type=int, default=3600,
                    help="最长跑多久(安全网)")
    args = ap.parse_args()

    port = pick_port(args.port)
    src = load_board_src()

    srv = make_server(args.http_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("=" * 60)
    print("  浏览器打开: http://127.0.0.1:%d/" % args.http_port)
    print("=" * 60)

    s = R.open_port(port)
    try:
        R.drain(s, 0.3)
        print(">>> 硬复位 + 打断 main.py ...")
        if not R.hard_reset(s):
            print("!! 硬复位失败, 继续")
        if not R.enter_raw(s):
            print("!! 进不去 raw REPL")
            return 2
        data = src.encode("utf-8")
        for i in range(0, len(data), R.CHUNK):
            s.write(data[i:i + R.CHUNK])
            time.sleep(0.004)
        s.write(R.CTRL_D)
        print(">>> 已下发采集+预览脚本，板子开始跑")

        th = threading.Thread(target=reader_loop, args=(s,), daemon=True)
        th.start()

        t0 = time.time()
        while time.time() - t0 < args.seconds:
            time.sleep(0.5)
            with _lock:
                lines = list(_state["lines"])
            if any("CHESSDONE" in ln for ln in lines):
                print(">>> 板上采集已结束(拍满 25 张)")
                time.sleep(1.5)
                break
            if any("读不到" in ln for ln in lines):
                print("!! 板上报 /sd 读不到 —— SD 又抽风了, 重启 USB 再来")
                break
    except KeyboardInterrupt:
        print("\n>>> 用户中止")
    finally:
        _stop.set()
        try:
            s.write(R.CTRL_C)
            time.sleep(0.6)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        print(">>> 收尾: 复位板子回 main.py ...")
        try:
            s2 = R.open_port(port)
            s2.reset_input_buffer()
            s2.dtr = True
            time.sleep(0.3)
            s2.dtr = False
            time.sleep(0.4)
            s2.close()
        except Exception as e:
            print("!! 复位失败: %r" % e)
        print(">>> 已复位")
    return 0


if __name__ == "__main__":
    sys.exit(main())
