# -*- coding: utf-8 -*-
"""
从官方 tag36_11_00000.png 的 10x10 位图生成：
  1) tag36h11_id0_A4.svg   —— A4 页面，tag 黑框外沿精确 100.0 mm，带 100mm 校验线
  2) tag36h11_id0_big.png  —— 1000x1000 高清图，手机屏幕显示用（自己量边长）

用法: python tools/make_tag.py
"""
import io
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "tag", "tag36_11_00000.png")
OUT_DIR = os.path.join(ROOT, "tag")

GRID = [
    "..........",
    ".########.",
    ".#..#.#.#.",
    ".##...#.#.",
    ".##..####.",
    ".#.#.####.",
    ".##.#..##.",
    ".####.###.",
    ".########.",
    "..........",
]


def load_official():
    """验证官方图还是这 10x10 布局，防止上游换了。"""
    d = open(SRC, "rb").read()
    pos, idat, w, h, ct = 8, b"", None, None, None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat += data
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4
    rows = []
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        rows.append(line)
        prev = line
    g = []
    for y in range(h):
        s = ""
        for x in range(w):
            s += "#" if rows[y][x * 4] < 128 else "."
        g.append(s)
    return g


def write_png(path, w, h, fn):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(fn(x, y))
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def build_svg(grid, tag_mm=100.0):
    n = len(grid)                 # 10
    cell = tag_mm / (n - 2)       # 8 格 = tag 边长
    total = cell * n              # 125 mm
    a4w, a4h = 210.0, 297.0
    ox = (a4w - total) / 2.0
    oy = 40.0

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" '
                 'width="%.1fmm" height="%.1fmm" viewBox="0 0 %.1f %.1f">'
                 % (a4w, a4h, a4w, a4h))
    parts.append('<rect x="0" y="0" width="%.1f" height="%.1f" fill="#ffffff"/>'
                 % (a4w, a4h))
    # 黑格（索引 1..n-2 是 tag 本体）
    for r in range(1, n - 1):
        for c in range(1, n - 1):
            if grid[r][c] == "#":
                parts.append(
                    '<rect x="%.4f" y="%.4f" width="%.4f" height="%.4f" fill="#000000"/>'
                    % (ox + c * cell, oy + r * cell, cell, cell))
    # tag 外框标注尺寸
    parts.append(
        '<rect x="%.4f" y="%.4f" width="%.4f" height="%.4f" fill="none" '
        'stroke="#cc0000" stroke-width="0.25" stroke-dasharray="2,1.5"/>'
        % (ox + cell, oy + cell, tag_mm, tag_mm))
    y = oy + total + 12.0
    parts.append('<text x="%.1f" y="%.1f" font-size="4.6" text-anchor="middle" '
                 'font-family="sans-serif" fill="#000000">'
                 'AprilTag 36h11  ID 0   (红色虚线框内黑边外沿 = 100.0 mm)</text>'
                 % (a4w / 2.0, y))
    # 100mm 校验线
    y2 = y + 14.0
    x0 = (a4w - 100.0) / 2.0
    parts.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#000000" '
                 'stroke-width="0.6"/>' % (x0, y2, x0 + 100.0, y2))
    for xx in (x0, x0 + 100.0):
        parts.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#000000" '
                     'stroke-width="0.6"/>' % (xx, y2 - 3.5, xx, y2 + 3.5))
    parts.append('<text x="%.1f" y="%.1f" font-size="4.2" text-anchor="middle" '
                 'font-family="sans-serif" fill="#000000">'
                 '校验线：用尺量这段应为 100.0 mm；若不对，打印时选「实际大小 / 100%%」</text>'
                 % (a4w / 2.0, y2 + 10.0))
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    g = load_official()
    if g != GRID:
        print("!! 官方图布局和预期不一致，实际是：")
        for row in g:
            print("   " + row)
        return 1

    svg = build_svg(GRID)
    p1 = os.path.join(OUT_DIR, "tag36h11_id0_A4.svg")
    io.open(p1, "w", encoding="utf-8", newline="\n").write(svg)
    print("写好", p1)

    # 手机用高清 PNG：1000x1000，一格 100px，tag 边 = 800px
    N, CELL = 1000, 100
    def fn(x, y):
        r, c = y // CELL, x // CELL
        if 0 <= r < 10 and 0 <= c < 10 and GRID[r][c] == "#":
            return (0, 0, 0)
        return (255, 255, 255)
    p2 = os.path.join(OUT_DIR, "tag36h11_id0_big.png")
    write_png(p2, N, N, fn)
    print("写好", p2)
    print("tag 黑边 = %d px / %d px 全图" % (800, N))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
