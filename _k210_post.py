# -*- coding: utf-8 -*-
"""收尾后处理：往 settings.xml 里补 <w:updateFields w:val="true"/>。

editor_sdk 没有直接开这个开关的工具，但它是 settings.xml 里的一个平铺元素，
位置在 CT_Settings 序列的 compat 之前。补上之后 Word/WPS 打开文档时会自动
更新目录域，PAGEREF 的占位 0 就会被替换成真实页码。

纯字节级改写：只动 settings.xml，其余条目原样复制。
"""
import io
import re
import shutil
import zipfile

import os as _os
SRC = _os.environ.get("K210_DOCX", "E:/K210/docs/K210视觉标定与测距手册.docx")
BAK = "E:/K210/docs/_pre_updatefields.bak.docx"

z = zipfile.ZipFile(SRC)
s = z.read("word/settings.xml").decode("utf-8")
assert "<w:updateFields" not in s, "已经开过了"

if "<w:compat>" in s:
    s2 = s.replace("<w:compat>", '<w:updateFields w:val="true"/><w:compat>', 1)
else:
    s2 = s.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>', 1)
assert '<w:updateFields w:val="true"/>' in s2, "补写失败"

shutil.copyfile(SRC, BAK)
infos = z.infolist()
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
    for it in infos:
        data = z.read(it.filename)
        if it.filename == "word/settings.xml":
            data = s2.encode("utf-8")
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        out.writestr(zi, data)
z.close()
with open(SRC, "wb") as f:
    f.write(buf.getvalue())

# 复核
z2 = zipfile.ZipFile(SRC)
chk = z2.read("word/settings.xml").decode("utf-8")
print("updateFields 写入:", re.findall(r"<w:updateFields[^>]*/>", chk))
print("条目一致:", z2.namelist() == [i.filename for i in infos])
print("其它文件字节一致:",
      all(z2.read(n) == zipfile.ZipFile(BAK).read(n)
          for n in z2.namelist() if n != "word/settings.xml"))
print("文件大小:", __import__("os").path.getsize(SRC))
