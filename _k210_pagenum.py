# -*- coding: utf-8 -*-
"""把 LibreOffice 排版得到的真实页码回填进目录域的缓存值。

doc_insert_toc 生成的 PAGEREF 域缓存值全是占位的 0，Word 靠 updateFields 在
打开时刷新，但在线预览/不刷新的查看器会一直显示 0。这里用 LibreOffice 导出的
PDF 反查每个标题落在第几页，把缓存值直接改成真实页码（域本身保留，仍可更新）。

页码口径：第 1 节（封面）无页码，第 2 节从 1 起算 => 显示页码 = PDF 页码 - 1。
"""
import io
import re
import shutil
import subprocess
import zipfile

PDF = "E:/K210/_pdfout/k210.pdf"
import os as _os
DOCX = _os.environ.get("K210_DOCX", "E:/K210/docs/K210视觉标定与测距手册.docx")
BAK = "E:/K210/docs/_pre_pagenum.bak.docx"
BODY = io.open("E:/K210/_standalone_body.html", encoding="utf-8").read()

# ---- 1. 标题清单（与目录顺序一致） ----
heads = [re.sub(r"<[^>]+>", "", t) for t in
         re.findall(r"<h[123]>(.*?)</h[123]>", BODY, re.S)]
print("标题数 =", len(heads))

# ---- 2. PDF 反查页码 ----
txt = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True).stdout
pages = txt.decode("utf-8", "replace").split("\f")
norm = [re.sub(r"\s+", "", p) for p in pages]
print("PDF 页数 =", len([p for p in norm if p]))

# 正文起始页自动探测：封面 / 目录里也会出现"第 1 章 概述"字样，
# 但正文页是它在 PDF 里【最后一次】出现的页（目录条目在前面）。
key1 = "第1章概述"
cand = [i for i, p in enumerate(norm) if key1 in p]
assert cand, "PDF 里找不到 第 1 章 概述"
BODY_START = cand[-1]      # 0-based：目录页在前, 正文页在后
assert BODY_START >= 2, "正文起始页异常: %d" % BODY_START
print("正文起始页(0-based) =", BODY_START)
nums, cur = [], BODY_START
for h in heads:
    key = re.sub(r"\s+", "", h)
    hit = None
    for i in range(cur, len(norm)):
        if key in norm[i]:
            hit = i
            break
    if hit is None:
        raise SystemExit("找不到标题所在页: %r" % h)
    cur = hit                            # 标题按顺序出现，从上一命中页继续找
    nums.append(hit + 1 - 1)             # 显示页码 = PDF 页码 - 1
print("页码 =", nums)

# ---- 3. 回填 ----
z = zipfile.ZipFile(DOCX)
d = z.read("word/document.xml").decode("utf-8")
shutil.copyfile(DOCX, BAK)

pat = re.compile(r'(PAGEREF [^<]*</w:instrText></w:r>'
                 r'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>)0(</w:t>)')
hits = pat.findall(d)
print("PAGEREF 占位 0 的个数 =", len(hits))
assert len(hits) == len(nums), "占位数与标题数不一致"

it = iter(nums)
d2 = pat.sub(lambda m: m.group(1) + str(next(it)) + m.group(2), d)
assert d2.count("<w:t>0</w:t>") < d.count("<w:t>0</w:t>")

infos = z.infolist()
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
    for f in infos:
        data = z.read(f.filename)
        if f.filename == "word/document.xml":
            data = d2.encode("utf-8")
        zi = zipfile.ZipInfo(f.filename, date_time=f.date_time)
        zi.compress_type = f.compress_type
        zi.external_attr = f.external_attr
        out.writestr(zi, data)
z.close()
open(DOCX, "wb").write(buf.getvalue())

z2 = zipfile.ZipFile(DOCX)
d3 = z2.read("word/document.xml").decode("utf-8")
print("回填后剩余 PAGEREF 0 占位:",
      len(re.findall(r'PAGEREF [^<]*</w:instrText></w:r><w:r><w:fldChar '
                     r'w:fldCharType="separate"/></w:r><w:r><w:t>0</w:t>', d3)))
print("回填样例:", re.findall(r'<w:t>(第 1 章 [^<]*)</w:t><w:tab/></w:r>.*?'
                              r'<w:t>(\d+)</w:t>', d3)[:3])
