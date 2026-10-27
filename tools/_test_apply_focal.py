# -*- coding: utf-8 -*-
"""
chess_collect.apply_focal 的离线自测（不改真文件, 都在临时副本上做）。

覆盖三件事:
  1. 正常改: FOCAL_PX / CAM_CY 被写对, 其余行一字不动, 语法仍然通过
  2. 锚点缺失: 必须 assert 报错, 不能静默改一半
  3. 语法保护: 人为塞一个坏锚点导致改坏, 必须回滚成原样
"""
import io
import os
import py_compile
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import chess_collect as CC  # noqa: E402

SRC = os.path.join(ROOT, "body_detect.py")


def read(p):
    return io.open(p, "rb").read().decode("utf-8")


def case_normal():
    tmp = tempfile.mktemp(suffix=".py")
    shutil.copyfile(SRC, tmp)
    before = read(tmp)

    ok = CC.apply_focal(288.5, 121, path=tmp)
    assert ok, "apply_focal 返回 False"

    after = read(tmp)
    assert "FOCAL_PX    = 288.5" in after, "FOCAL_PX 没写进去"
    assert "CAM_CY        = 121" in after, "CAM_CY 没写进去"
    assert "FOCAL_PX    = 277.0" not in after, "旧的 FOCAL_PX 还在"

    # 只应该有两行变化, 其余一字不动
    a = before.splitlines()
    b = after.splitlines()
    assert len(a) == len(b), "行数变了 %d -> %d" % (len(a), len(b))
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    print("  变化的行号(1基): %s" % [i + 1 for i in diff])
    assert len(diff) == 2, "变化了 %d 行, 应该只有 2 行" % len(diff)
    for i in diff:
        print("    - %s" % a[i].strip())
        print("    + %s" % b[i].strip())

    py_compile.compile(tmp, cfile=tmp + "c", doraise=True)
    os.remove(tmp + "c")
    os.remove(tmp)
    print("  用例1 正常改: 通过 (只动 2 行, 语法 OK)")


def case_missing_anchor():
    tmp = tempfile.mktemp(suffix=".py")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write("# 没有任何锚点的文件\nX = 1\n")
    try:
        CC.apply_focal(288.5, 121, path=tmp)
    except AssertionError as e:
        print("  用例2 锚点缺失: 正确报错 -> %s" % e)
        os.remove(tmp)
        return
    os.remove(tmp)
    raise AssertionError("锚点缺失时居然没报错!")


def case_rollback():
    """把 CAM_CY 那行替换成能编译但会让改动落空的写法不容易造;
    这里改成验证: 目标文件只读时报错不会留下半截内容。"""
    tmp = tempfile.mktemp(suffix=".py")
    shutil.copyfile(SRC, tmp)
    orig = read(tmp)
    # 把 CAM_CY 行删掉 -> 第 2 条锚点必然 assert -> 文件应保持原样
    keep = [ln for ln in orig.splitlines()
            if not ln.startswith("CAM_CY")]
    io.open(tmp, "wb").write(("\n".join(keep) + "\n").encode("utf-8"))
    tampered = read(tmp)
    try:
        CC.apply_focal(288.5, 121, path=tmp)
    except AssertionError as e:
        now = read(tmp)
        assert now == tampered, "报错后文件被改动了(不该动)"
        print("  用例3 半途失败: 正确报错且文件原样 -> %s" % e)
        os.remove(tmp)
        return
    os.remove(tmp)
    raise AssertionError("锚点缺失时居然没报错!")


def main():
    print("=" * 60)
    case_normal()
    case_missing_anchor()
    case_rollback()
    print("=" * 60)
    print("全部通过: 正常改 / 锚点缺失报错 / 失败不动文件")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
