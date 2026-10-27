# -*- coding: utf-8 -*-
"""构建《K210 视觉标定与测距手册》独立成册版 (v1.0)。

路径与用法：
  K210_FID=<新建文档的 file_id> python3 -u _k210_docbuild.py

顺序：样式 -> 封面 -> 正文 -> 目录标题+目录 -> 把目录搬到正文前 -> 分页/分节 -> 页眉页码 -> 保存。

坐标系说明（踩过的坑，写在最前面）：
  · doc_insert_* 回包的 last_edit_index 可能比"文档最后一个可操作位置"大 1，
    直接拿它当下一次 idx 会 out of range；统一改用 doc_get_last_operable_pos 的 position。
  · doc_update_named_style 的 jc 映射是**反的**：left->end、right->start、both->end。
    所以正文/表格/列表/代码块一律用 HTML 内联 text-align，不依赖命名样式。
  · doc_resolve_document_structure 默认 limit=150 会**截断**，必须传 limit=0。
"""
import io
import json
import os
import sys

SKILL = (r"D:/Users/ASUS/AppData/Local/Programs/WorkBuddy/resources/app.asar.unpacked"
         r"/resources/plugins/workbuddy-builtin/skills/workbuddy-local-office-edit")
sys.path.insert(0, SKILL)
import edsdk  # noqa: E402

FID = os.environ["K210_FID"]
OUT = "E:/K210/docs/K210视觉标定与测距手册.docx"
HERE = "E:/K210/"


def call(tool, **kw):
    kw.setdefault("file_id", FID)
    res = edsdk._rpc("tools/call", {"name": tool, "arguments": kw})
    txt = "\n".join(str(c.get("text", "")) for c in (res.get("content") or [])
                    if isinstance(c, dict))
    print("---- %s ----" % tool)
    print(txt[:700])
    print()
    try:
        return json.loads(txt)
    except Exception:
        return {"_raw": txt}


def tail():
    return call("doc_get_last_operable_pos").get("position")


def nodes_of():
    r = call("doc_resolve_document_structure", limit=0, text_preview_length=14)
    return r.get("nodes") or []


def find_node(ns, pred):
    for i, n in enumerate(ns):
        if pred(n):
            return i
    return -1


j = json.load(io.open(HERE + "_standalone.json", encoding="utf-8"))
COVER, BODY = j["cover"], j["body"]
TOC_TITLE = ('<p style="font-family:SimHei;font-size:18pt;color:#111827;text-align:center;'
             'line-height:150%;margin:0pt 0pt 16pt 0pt">目&#12288;&#12288;录</p>')

# ============================================================
# A 页面设置
# ============================================================
call("doc_modify_section", section_index=0,
     page_width=595.3, page_height=841.9,
     left_margin=85.0, right_margin=85.0, top_margin=72.0, bottom_margin=72.0,
     header_distance=42.0, footer_distance=42.0)

# ============================================================
# B 文档默认样式
# ============================================================
call("doc_set_document_style",
     default_text_style={"font_family": "SimSun", "font_east_asia": "SimSun",
                         "font_ascii": "Times New Roman", "font_size": 12,
                         "color": "111827"},
     default_paragraph_style={"line_spacing": 1.5, "line_spacing_rule": 1,
                              "spacing_before": 0, "spacing_after": 6})

# ============================================================
# C 命名样式
# ============================================================
SANS = {"font_ascii": "Arial", "font_east_asia": "SimHei"}
SERIF = {"font_ascii": "Times New Roman", "font_east_asia": "SimSun"}


def _s(base, **kw):
    d = dict(base)
    d.update(kw)
    return d


STYLES = [
    ("TITLE", {"jc": "center", "spacing_before": 0, "spacing_after": 10,
               "line_spacing": 1.3, "line_spacing_rule": 1},
     _s(SANS, font_family="SimHei", bold=True, font_size=26, color="111827")),
    ("SUBTITLE", {"jc": "center", "spacing_before": 0, "spacing_after": 6,
                  "line_spacing": 1.4, "line_spacing_rule": 1},
     _s(SERIF, font_family="SimSun", bold=False, font_size=13, color="4B5563")),
    ("HEADING_1",
     {"jc": "center", "spacing_before": 18, "spacing_after": 10,
      "line_spacing": 1.3, "line_spacing_rule": 1, "keep_with_next": True},
     _s(SANS, font_family="SimHei", bold=True, font_size=18, color="111827")),
    ("HEADING_2",
     {"jc": "left", "spacing_before": 12, "spacing_after": 6,
      "line_spacing": 1.3, "line_spacing_rule": 1, "keep_with_next": True},
     _s(SANS, font_family="SimHei", bold=True, font_size=14, color="1F2937")),
    ("HEADING_3",
     {"jc": "left", "spacing_before": 10, "spacing_after": 5,
      "line_spacing": 1.35, "line_spacing_rule": 1, "keep_with_next": True},
     _s(SERIF, font_family="SimSun", bold=True, font_size=12, color="374151")),
    ("HEADING_4",
     {"jc": "left", "spacing_before": 8, "spacing_after": 4,
      "line_spacing": 1.35, "line_spacing_rule": 1, "keep_with_next": True},
     _s(SERIF, font_family="SimSun", bold=True, font_size=12, color="374151")),
    ("NORMAL_TEXT",
     {"spacing_before": 0, "spacing_after": 6.6,
      "line_spacing": 1.7, "line_spacing_rule": 1},
     _s(SERIF, font_family="SimSun", font_size=12, color="111827")),
    ("TOC 1", {"jc": "left", "spacing_before": 3, "spacing_after": 3,
               "line_spacing": 1.4, "line_spacing_rule": 1},
     _s(SANS, font_family="SimHei", bold=True, font_size=11, color="111827")),
    ("TOC 2", {"jc": "left", "left_indent": 22, "spacing_before": 1, "spacing_after": 1,
               "line_spacing": 1.4, "line_spacing_rule": 1},
     _s(SERIF, font_family="SimSun", font_size=10.5, color="374151")),
    ("TOC 3", {"jc": "left", "left_indent": 44, "spacing_before": 1, "spacing_after": 1,
               "line_spacing": 1.4, "line_spacing_rule": 1},
     _s(SERIF, font_family="SimSun", font_size=10.5, color="4B5563")),
]
for name, ps, ts in STYLES:
    call("doc_update_named_style", named_style_type=name,
         paragraph_style=ps, text_style=ts)

# ============================================================
# D/E/F/G 封面 -> 正文 -> 目录标题 -> 目录
# ============================================================
call("doc_insert_html_content", idx=0, html_text=COVER)
call("doc_insert_html_content", idx=tail(), html_text=BODY)
call("doc_insert_html_content", idx=tail(), html_text=TOC_TITLE)
call("doc_insert_toc", idx=tail(), max_level=3)

# ============================================================
# H 结构定位
# ============================================================
ns = nodes_of()
io.open(HERE + "_struct_dump.json", "w", encoding="utf-8").write(
    json.dumps(ns, ensure_ascii=False, indent=1))
print(">>> 节点数 =", len(ns))

ti = find_node(ns, lambda n: (n.get("text_preview") or "").startswith("目"))
bi = find_node(ns, lambda n: (n.get("text_preview") or "").startswith("第 1 章"))
assert ti > 0 and bi > 0, "定位失败 ti=%d bi=%d" % (ti, bi)
cover_end = ns[bi]["start_index"]
toc_start = ns[ti]["start_index"]
toc_end = ns[-1]["end_index"]
print(">>> ti=%d bi=%d  cover_end=%d  toc=[%d,%d)  末节点=%s"
      % (ti, bi, cover_end, toc_start, toc_end,
         json.dumps(ns[-1], ensure_ascii=False)[:150]))

# ============================================================
# I 把 [目录标题 .. 目录末] 搬到正文之前
# ============================================================
call("doc_move_content",
     source_range={"begin": toc_start, "end": toc_end},
     target_index=cover_end)

# ============================================================
# J 分页 / 分节（重新查询坐标）
# ============================================================
ns = nodes_of()
io.open(HERE + "_struct_dump2.json", "w", encoding="utf-8").write(
    json.dumps(ns, ensure_ascii=False, indent=1))
ti = find_node(ns, lambda n: (n.get("text_preview") or "").startswith("目"))
bi = find_node(ns, lambda n: (n.get("text_preview") or "").startswith("第 1 章"))
assert ti > 0 and bi > ti, "搬完后定位失败 ti=%d bi=%d" % (ti, bi)
cover_end2 = ns[ti]["start_index"]
body_start = ns[bi]["start_index"]
print(">>> [搬完] 封面结束=%d 目录结束=%d" % (cover_end2, body_start))
print(">>> 目录标题节点:", json.dumps(ns[ti], ensure_ascii=False)[:160])
print(">>> 目录首节点  :", json.dumps(ns[ti + 1], ensure_ascii=False)[:160])
print(">>> 目录末节点  :", json.dumps(ns[bi - 1], ensure_ascii=False)[:160])

call("doc_insert_page_break", idx=body_start)
call("doc_insert_section_break", idx=cover_end2, start_type="new_page")

# ============================================================
# K 页眉 / 页码（只作用于第 2 节 = 目录 + 正文）
# ============================================================
secs = call("doc_list_sections")
s1 = None
for s in (secs.get("sections") or []):
    if s.get("section_index") == 1:
        s1 = s.get("section_id")
print(">>> section1 =", s1)
kw = {"section_id": s1} if s1 else {"section_index": 1}
call("doc_insert_header", text="K210 视觉标定与测距手册", horizontal_align="center",
     text_format={"font_family": "SimSun", "font_east_asia": "SimSun",
                  "font_ascii": "Times New Roman", "font_size": 9,
                  "color": "6B7280"}, **kw)
call("doc_set_page_number", position="center", format="decimal",
     continue_from_prev=False, start=1, scope="from_here", **kw)

# ============================================================
# L 保存
# ============================================================
call("save_file", file_path=OUT)
print(">>> DONE ->", OUT)
