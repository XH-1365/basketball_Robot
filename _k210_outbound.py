# -*- coding: utf-8 -*-
"""
外发硬化：把本机生成的 docx 收拾成「任何 Word/WPS 都能直接打开」的纯正 OOXML。
可重复执行（每步做过就跳过）。构建链路里放在最后一步。

做的事：
  1. 去掉非标准域开关 `\\tdkey <id>`（腾讯 office 私有扩展，TOC/PAGEREF 里）
     - TOC  \\u \\o "1-3" \\z \\h \\tdkey X   ->  TOC \\u \\o "1-3" \\z \\h
     - PAGEREF bm \\h \\tdkey X              ->  PAGEREF bm \\h
     （\\u \\o \\z \\h 都是 Word 官方开关，原样保留）
  2. word/fontTable.xml 去掉重复的 <w:font>（CT_Fonts 要求 name 唯一）
  3. docProps/core.xml 补标题/主题/作者（生成器只写 created/modified）
  4. [Content_Types].xml 提到第一条目（OPC 不强制，但这是 Word 自己的写法）
  5. word/styles.xml 修两处 Word 必拒、LibreOffice 无视的硬伤：
     5a. 悬空的 basedOn/next —— 生成器给 heading 1~4 / Title / Subtitle 写的
         basedOn/next 指向从未生成的 styleId，Word 直接报「无法读取的内容」。
         改为指向 Normal（w:default="1" 的段落样式）；这些样式自身格式齐全，
         继承 Normal 语义正确。
     5b. 空 <w:jc/> —— CT_Jc 的 w:val 是必填属性，生成器对 left 对齐写出
         了没有属性的空元素。改为 <w:jc w:val="left"/>。
     5c. TOC2/TOC3 缩进规范化 —— 编辑器新版把 left_indent 单位换算放大 20 倍
         （440->8800 / 880->17600 缇），目录二三级条目在页右缘一字一行竖排。
         钉死为设计值 440/880 缇（取自 commit 9dc1381 正常版本实测）。
  6. 表格布局定宽（Word/LO/WPS 渲染一致）：
     6a. tblLayout autofit -> fixed（autofit 时 Word 按内容重算列宽，
         和 LibreOffice 差异很大，封面表在 Word 里直接塌掉）
     6b. 封面表加 <w:jc w:val="center"/>（HTML 的 60pt 左缩进被转换器丢了）
     6c. 封面格内边距修正：标签格 right 60->240（HTML 本意 12pt，留出
         标签与值的间隙）、bottom 240->60（与值格统一，行高不再忽高忽低）

其余条目字节保持不变；条目顺序除被提前的 [Content_Types].xml 外原样保留。
验证：_verify_outbound.py（结构 20+ 项）+ Word COM 实开（OpenAndRepair=false）
+ Word 另存 PDF 逐页目检（真正的 Word 渲染效果）。
"""
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

SRC = os.environ.get("K210_DOCX", r"E:/K210/docs/K210视觉标定与测距手册.docx")
BAK = r"E:/K210/docs/_pre_outbound.bak.docx"
TMP = SRC + ".tmp"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS

TITLE = "K210 视觉标定与测距手册"
SUBJECT = "单目相机人体检测 · 相机内参标定 · 距离解算链路"
AUTHOR = "K210 视觉标定与测距项目组"


def parse(s):
    return ET.fromstring(s)


def main():
    if not os.path.exists(SRC):
        print("!! 找不到源文件:", SRC)
        return 1
    shutil.copy2(SRC, BAK)
    print("备份 ->", BAK, os.path.getsize(BAK), "B")

    zin = zipfile.ZipFile(SRC, "r")
    infos = zin.infolist()
    data = {i.filename: zin.read(i.filename) for i in infos}
    zin.close()
    print("原条目数 =", len(infos))

    changed = []

    # ---- 1) document.xml : 去 \\tdkey ----
    doc = data["word/document.xml"].decode("utf-8")
    before_td = doc.count("\\tdkey")
    if before_td == 0:
        print("  1) \\tdkey 已清零，跳过")
    else:
        doc2, n1 = re.subn(r"[ ]*\\tdkey\s+[0-9A-Za-z]+", "", doc)
        assert doc2.count("\\tdkey") == 0
        # 域开关不应被破坏：域节点数不变
        assert doc2.count("<w:instrText") == doc.count("<w:instrText")
        assert doc2.count("<w:fldChar") == doc.count("<w:fldChar")
        parse(doc2)  # 立刻自检：必须仍能解析
        data["word/document.xml"] = doc2.encode("utf-8")
        changed.append("document.xml: 去掉 %d 处 \\tdkey" % n1)
        print("  1) \\tdkey %d -> %d" % (before_td, doc2.count("\\tdkey")))
        m = re.search(r"<w:instrText[^>]*>(TOC [^<]*)</w:instrText>", doc2)
        print("     抽验 TOC 指令:", repr(m.group(1)))

    # ---- 2) fontTable.xml : 去重 ----
    ft = data["word/fontTable.xml"].decode("utf-8")
    # 注意：不能用 ft.index("<w:font")，它会被根标签 <w:fonts 抢先命中
    m_open = re.search(r"<w:fonts[^>]*>", ft)
    m_close = re.search(r"</w:fonts>\s*$", ft)
    assert m_open and m_close, "fontTable 根元素定位失败"
    head, body, tail = ft[: m_open.end()], ft[m_open.end() : m_close.start()], ft[m_close.start() :]
    blocks = re.findall(r'<w:font w:name="[^"]+">.*?</w:font>', body)
    assert blocks, "fontTable 里没找到 <w:font>"
    seen, kept, dropped = set(), [], []
    for b in blocks:
        nm = re.search(r'w:name="([^"]+)"', b).group(1)
        if nm in seen:
            dropped.append(nm)
            continue
        seen.add(nm)
        kept.append(b)
    if dropped:
        new_ft = head + "".join(kept) + tail
        parse(new_ft)  # 立刻自检
        assert new_ft.rstrip().endswith("</w:fonts>")
        data["word/fontTable.xml"] = new_ft.encode("utf-8")
        changed.append("fontTable.xml: 删除重复字体 %s" % dropped)
        print("  2) fontTable 去重:", dropped, "剩余", sorted(seen))
    else:
        print("  2) fontTable 无重复")

    # ---- 3) core.xml : 补元数据 ----
    core = data["docProps/core.xml"].decode("utf-8")
    if "<dc:title>" in core:
        print("  3) core.xml 已有标题，跳过")
    else:
        add = (
            "<dc:title>%s</dc:title>" % TITLE
            + "<dc:subject>%s</dc:subject>" % SUBJECT
            + "<dc:creator>%s</dc:creator>" % AUTHOR
            + "<cp:lastModifiedBy>%s</cp:lastModifiedBy>" % AUTHOR
        )
        core2 = core.replace("<dcterms:created", add + "<dcterms:created", 1)
        assert core2 != core, "core.xml 未插入成功"
        data["docProps/core.xml"] = core2.encode("utf-8")
        changed.append("core.xml: 补 title/subject/creator/lastModifiedBy")
        print("  3) core.xml 已补元数据")

    # ---- 5) styles.xml : 修悬空 basedOn/next + 空 <w:jc/> ----
    st = data["word/styles.xml"].decode("utf-8")
    sroot = parse(st)
    defined = set()
    normal_id = None
    for s in sroot.iter(W + "style"):
        defined.add(s.get(W + "styleId"))
        if s.get(W + "default") == "1" and s.get(W + "type") == "paragraph":
            normal_id = s.get(W + "styleId")
    assert normal_id, "styles.xml 里找不到 default 段落样式 (Normal)"

    def fix_ref(m):
        tag, val = m.group(1), m.group(2)
        if val in defined:
            return m.group(0)
        print("     悬空引用: <%s w:val=\"%s\"/> -> Normal(%s)" % (tag, val, normal_id))
        return '<w:%s w:val="%s"/>' % (tag, normal_id)

    st2, n_ref = re.subn(r'<w:(basedOn|next) w:val="([^"]+)"/>', fix_ref, st)
    st2, n_jc = re.subn(r"<w:jc\s*/>", '<w:jc w:val="left"/>', st2)

    # 5c. TOC2/TOC3 缩进规范化 —— 编辑器 SDK 新版把 left_indent 的单位换算
    #     放大了 20 倍（意图 22pt=440 缇写成 8800 缇 ≈ 整个文本区宽），
    #     导致目录二三级条目在页右缘一字一行"竖排"。钉死为设计值，幂等。
    #     设计值来自首个正常版本（commit 9dc1381）实测：TOC2=440 / TOC3=880 缇。
    n_ind = 0
    for sid, good, bad in (("TOC2", "440", "8800"), ("TOC3", "880", "17600")):
        pat = r'(<w:style [^>]*w:styleId="%s"[^>]*>(?:(?!</w:style>).)*?)<w:ind w:left="%s"/>' % (sid, bad)
        st2, k = re.subn(pat, r'\g<1><w:ind w:left="%s"/>' % good, st2, flags=re.S)
        n_ind += k
        if k:
            print("     TOC 缩进修正: %s %s->%s 缇" % (sid, bad, good))
    assert '<w:ind w:left="8800"/>' not in st2 and '<w:ind w:left="17600"/>' not in st2

    parse(st2)  # 立刻自检
    # 复核：不再有悬空、不再有空 jc
    sroot2 = parse(st2)
    dangling = [
        (s.get(W + "styleId"), r.get(W + "val"))
        for s in sroot2.iter(W + "style")
        for r in s.iter() if r.tag in (W + "basedOn", W + "next")
        if r.get(W + "val") not in defined
    ]
    assert not dangling, "仍有悬空引用: %s" % dangling
    assert "<w:jc/>" not in st2
    if n_ref or n_jc or n_ind:
        data["word/styles.xml"] = st2.encode("utf-8")
        changed.append("styles.xml: 修悬空 basedOn/next %d 处、空 <w:jc/> %d 处、TOC 缩进 %d 处"
                       % (n_ref // 2 if n_ref else 0, n_jc, n_ind))
        print("  5) styles.xml: 悬空引用 %d -> 0, 空 jc %d -> 0, TOC 缩进修正 %d" % (n_ref, n_jc, n_ind))
    else:
        print("  5) styles.xml 无需修")

    # ---- 6) 表格布局定宽 ----
    doc2 = data["word/document.xml"].decode("utf-8")
    doc2, n_fixed = re.subn(r'<w:tblLayout w:type="autofit"/>', '<w:tblLayout w:type="fixed"/>', doc2)
    print("  6a) tblLayout autofit->fixed: %d 张表" % n_fixed)

    # 封面表：加宽值列让最长值单行放得下。封面是文档第一张表，
    # 替换范围限定在第一个 </w:tbl> 之前，避免误伤正文表
    e = doc2.find("</w:tbl>") + len("</w:tbl>")
    cover, rest = doc2[:e], doc2[e:]
    if '<w:tblW w:w="6146" w:type="dxa"/>' in cover:
        cover = cover.replace('<w:tblW w:w="6146" w:type="dxa"/>', '<w:tblW w:w="6806" w:type="dxa"/>')
        cover = cover.replace('<w:gridCol w:w="4486"/>', '<w:gridCol w:w="5147"/>')
        cover = cover.replace('<w:tcW w:w="4486" w:type="dxa"/>', '<w:tcW w:w="5147" w:type="dxa"/>')
        print("  6a2) 封面表加宽: 总宽 6146->6806, 值列 4486->5147 缇")
    else:
        assert '<w:tblW w:w="6806" w:type="dxa"/>' in cover, "封面表宽度锚点丢失"
        print("  6a2) 封面表已是加宽尺寸，跳过")
    doc2 = cover + rest

    # 封面表居中；CT_TblPr 顺序: tblW 之后是 jc（幂等：已加则跳过）
    anchor = '<w:tblW w:w="6806" w:type="dxa"/>'
    assert doc2.count(anchor) == 1, "封面表锚点不唯一: %d" % doc2.count(anchor)
    if anchor + '<w:jc w:val="center"/>' in doc2:
        print("  6b) 封面表已有 jc=center，跳过")
    else:
        doc2 = doc2.replace(anchor, anchor + '<w:jc w:val="center"/>', 1)
        print("  6b) 封面表已加 jc=center")

    # 封面格内边距：bottom 240->60（与值格统一，行高不再忽高忽低）、
    # right 60->240（留出标签与值的间隙）。只作用于第一张表（封面），
    # 属性级替换：无论起点是旧构建的 (60,60,240,60) 还是新构建的 (60,0,60,240)，
    # 都能归一到 (60,*,60,240)，幂等。
    e2 = doc2.find("</w:tbl>") + len("</w:tbl>")
    cover, rest = doc2[:e2], doc2[e2:]
    n_b = cover.count('<w:bottom w:w="240" w:type="dxa"/>')
    cover = cover.replace('<w:bottom w:w="240" w:type="dxa"/>', '<w:bottom w:w="60" w:type="dxa"/>')
    n_r = cover.count('<w:right w:w="60" w:type="dxa"/>')
    cover = cover.replace('<w:right w:w="60" w:type="dxa"/>', '<w:right w:w="240" w:type="dxa"/>')
    doc2 = cover + rest
    if n_b or n_r:
        print("  6c) 封面格 tcMar: bottom 240->60 x%d, right 60->240 x%d" % (n_b, n_r))
    else:
        print("  6c) 封面格 tcMar 已是目标值，跳过")

    parse(doc2)  # 自检
    data["word/document.xml"] = doc2.encode("utf-8")
    changed.append("document.xml: 表格 fixed 布局 %d 张、封面表居中、封面格距修正" % n_fixed)

    # ---- 4) 重排条目：[Content_Types].xml 提前 ----
    order = ["[Content_Types].xml"] + [i.filename for i in infos if i.filename != "[Content_Types].xml"]
    print("  4) 新条目顺序:", order[:3], "...")

    # ---- 写回 ----
    by_name = {i.filename: i for i in infos}
    zout = zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED)
    for name in order:
        src = by_name[name]
        ni = zipfile.ZipInfo(name, date_time=src.date_time)
        ni.compress_type = src.compress_type
        ni.external_attr = src.external_attr
        ni.internal_attr = src.internal_attr
        ni.create_system = src.create_system
        ni.comment = src.comment
        zout.writestr(ni, data[name])
    zout.close()
    os.replace(TMP, SRC)
    print("\n写出:", SRC, os.path.getsize(SRC), "B")
    print("改动:", changed if changed else "（无）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
