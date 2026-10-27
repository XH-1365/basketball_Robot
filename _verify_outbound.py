# -*- coding: utf-8 -*-
"""外发硬化后的完整性核验：逐 part 对比备份 + 结构断言 + 域完整性。"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SRC = os.environ.get("K210_DOCX", r"E:/K210/docs/K210视觉标定与测距手册.docx")
BAK = r"E:/K210/docs/_pre_outbound.bak.docx"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

ok = True


def check(cond, msg, extra=""):
    global ok
    print(("  [OK] " if cond else "  [!!] ") + msg + (("  " + str(extra)) if extra else ""))
    if not cond:
        ok = False


z = zipfile.ZipFile(SRC)
zb = zipfile.ZipFile(BAK)
names = z.namelist()
nmb = zb.namelist()

print("== 1) 包完整性 ==")
check(z.testzip() is None, "zip testzip 无损坏")
check(len(names) == 20, "条目数 20", len(names))
check(names[0] == "[Content_Types].xml", "第一条目为 [Content_Types].xml", names[0])
print("  [..] 备份里的位置（信息性，备份可能本身已硬化）:",
      nmb.index("[Content_Types].xml"), "/", len(nmb) - 1)
check(sorted(names) == sorted(nmb), "条目集合与备份一致")
# 顺序：除被提前者外原样
rest = [n for n in nmb if n != "[Content_Types].xml"]
check(names[1:] == rest, "其余条目顺序原样保留")

print("\n== 2) 所有 XML 可解析 ==")
xmlnames = [n for n in names if n.endswith(".xml") or n.endswith(".rels")]
for n in xmlnames:
    try:
        ET.fromstring(z.read(n))
    except Exception as e:
        check(False, "%s 解析失败" % n, e)
check(True, "%d 个 XML part 全部解析通过" % len(xmlnames))

print("\n== 3) 逐 part 字节对比 ==")
for n in sorted(names):
    if n == "[Content_Types].xml":
        continue
    a, b = z.read(n), zb.read(n)
    if a == b:
        print("  [==] %s  (未改动)" % n)
    else:
        print("  [~~] %s  %d -> %d B" % (n, len(b), len(a)))

print("\n== 4) 域结构完整性 ==")
doc = z.read("word/document.xml").decode("utf-8")
docb = zb.read("word/document.xml").decode("utf-8")
for pat in ["<w:instrText", "<w:fldChar", "<w:bookmarkStart", "<w:bookmarkEnd",
            "<w:hyperlink", "<w:sectPr", "<w:br w:type=\"page\"", "<w:tbl>", "<w:p "] :
    check(doc.count(pat) == docb.count(pat),
          "%-22s %d == 备份 %d" % (pat, doc.count(pat), docb.count(pat)))
check(doc.count("\\tdkey") == 0, "\\tdkey 已清零")
check(doc.count("<w:fldChar") == docb.count("<w:fldChar"),
      "fldChar 数不变（begin/separate/end 配对没被破坏）")

# 域三件套配对
b = doc.count('w:fldCharType="begin"')
s = doc.count('w:fldCharType="separate"')
e = doc.count('w:fldCharType="end"')
check(b == s == e, "fldChar begin/separate/end 配对 %d/%d/%d" % (b, s, e))

# 书签配对（数量随章节增减，只验配对）
check(doc.count("<w:bookmarkStart") == doc.count("<w:bookmarkEnd"),
      "bookmark start/end 配对",
      "%d/%d" % (doc.count("<w:bookmarkStart"), doc.count("<w:bookmarkEnd")))

print("\n== 5) 域指令抽样 ==")
instrs = re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", doc, re.S)
print("  域指令总数 =", len(instrs))
print("  TOC  :", repr(instrs[0]))
print("  PAGEREF 前 3:", [repr(x) for x in instrs[2:8:2]])
bad = [x for x in instrs if "tdkey" in x]
check(not bad, "无残留 tdkey 指令")

print("\n== 6) TOC 缓存页码（不依赖域刷新也应正确） ==")
nums = re.findall(
    r'PAGEREF [^<]*</w:instrText></w:r>'
    r'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    r'<w:r><w:t>(\d+)</w:t>',
    doc,
)
print("  缓存页码 =", nums)
check(len(nums) > 0, "页码占位数 > 0", len(nums))
check(all(int(x) > 0 for x in nums) if nums else False, "无 0 占位")
check(nums == sorted(nums, key=int), "页码单调不减")

print("\n== 7) 字体表 ==")
ft = z.read("word/fontTable.xml").decode("utf-8")
fn = re.findall(r'<w:font w:name="([^"]+)"', ft)
check(len(fn) == len(set(fn)), "字体名唯一", fn)

print("\n== 7b) styles.xml：Word 严格项 ==")
stx = z.read("word/styles.xml").decode("utf-8")
sroot = ET.fromstring(stx)
defined = {s.get(W + "styleId") for s in sroot.iter(W + "style")}
dangling = [
    (s.get(W + "styleId"), r.tag.split("}")[1], r.get(W + "val"))
    for s in sroot.iter(W + "style")
    for r in s.iter()
    if r.tag in (W + "basedOn", W + "next") and r.get(W + "val") not in defined
]
check(not dangling, "无悬空 basedOn/next", dangling)
check("<w:jc/>" not in stx, "无空 <w:jc/>（CT_Jc 的 w:val 必填）")
check(len(re.findall(r"<w:jc[ >]", stx)) == len(re.findall(r'<w:jc [^>]*w:val="[^"]+"', stx)),
      "所有 w:jc 都带 w:val")

print("\n== 7c) styles.xml：TOC 缩进（编辑器单位换算 bug 钉死） ==")
for sid, good in (("TOC2", "440"), ("TOC3", "880")):
    m = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % sid, stx, re.S)
    ind = re.search(r'<w:ind w:left="(\d+)"/>', m.group(0)) if m else None
    check(ind is not None and ind.group(1) == good,
          "%s 缩进 = %s 缇" % (sid, good), ind.group(1) if ind else "无 <w:ind>")
check('<w:ind w:left="8800"/>' not in stx and '<w:ind w:left="17600"/>' not in stx,
      "无异常放大缩进（8800/17600）")

print("\n== 8) 文档属性 ==")
core = z.read("docProps/core.xml").decode("utf-8")
check("<dc:title>K210 视觉标定与测距手册</dc:title>" in core, "core.xml 有标题")
check("<dc:creator>" in core, "core.xml 有作者")

print("\n== 9) settings.xml ==")
st = z.read("word/settings.xml").decode("utf-8")
check("<w:updateFields w:val=\"true\"/>" in st, "updateFields=true 保留")
check(st.index("<w:updateFields") < st.index("<w:compat"),
      "updateFields 位于 compat 之前（CT_Settings 顺序）")
check(st == zb.read("word/settings.xml").decode("utf-8"), "settings.xml 未被改动")

print("\n== 10) 关系与分节 ==")
rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
targets = re.findall(r'Target="([^"]+)"', rels)
ext = [t for t in targets if t.startswith(("http", "file:"))]
check(not ext, "无外部关系", ext)
missing = [t for t in targets if not t.startswith(("http", "file:"))
           and ("word/" + t.lstrip("/")) not in names and t.lstrip("/") not in names]
check(not missing, "无悬空关系目标", missing)
root = ET.fromstring(doc)
sect = root.iter(W + "sectPr")
check(len(list(root.iter(W + "sectPr"))) == 2, "2 个 sectPr")

print("\n" + ("===== 全部通过 =====" if ok else "===== 有失败项 ====="))
sys.exit(0 if ok else 1)
