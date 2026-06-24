# -*- coding: utf-8 -*-
"""
审核员模块测试
测试本地审核和AI审核功能
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from review import Reviewer, LocalReviewer


def test_local_review():
    """测试本地审核"""
    print("测试: 本地审核")

    # 测试不存在的文件
    passed, errors = LocalReviewer.review_file('not_exist.py')
    assert passed == False, "不存在的文件应该返回 False"
    assert '文件不存在' in errors
    print("  [1] 不存在文件检测 ✓")

    # 测试 Python 语法错误
    error_py_content = """
def broken_function(:
    if True
        print(
"""
    test_file = 'e:/YGA6.0/_test_error.py'
    with open(test_file, 'w', encoding='utf-8-sig') as f:
        f.write(error_py_content)

    passed, errors = LocalReviewer.review_file(test_file)
    assert passed == False, "语法错误的文件应该返回 False"
    assert '语法错误' in errors
    print("  [2] 语法错误检测 ✓")

    # 清理测试文件
    os.remove(test_file)

    # 测试正常 Python 文件
    passed, errors = LocalReviewer.review_file('e:/YGA6.0/memory/MemSession.py')
    assert passed == True, "正常的 YGA 文件应该通过"
    print("  [3] YGA 文件锚点检测 ✓")

    # 测试 Markdown 文件
    passed, errors = LocalReviewer.review_file('e:/YGA6.0/.claude/yga-principles.md')
    assert passed == True, "正常 Markdown 应该通过"
    print("  [4] Markdown 文件检测 ✓")

    print("  PASS")


def test_local_review_module():
    """测试模块审核"""
    print("\n测试: 模块审核")

    files = [
        'e:/YGA6.0/memory/MemSession.py',
        'e:/YGA6.0/memory/MemWriter.py',
        'e:/YGA6.0/memory/MemReader.py',
        'e:/YGA6.0/memory/MemPhase.py',
        'e:/YGA6.0/memory/MemRouter.py',
    ]

    passed, errors = LocalReviewer.review_module('memory', files)
    assert passed == True, "Memory 模块应该通过本地审核"
    print("  Memory 模块本地审核通过 ✓")
    print("  PASS")


def main():
    print("=" * 50)
    print("审核员模块测试")
    print("=" * 50)

    try:
        test_local_review()
        test_local_review_module()

        print("\n" + "=" * 50)
        print("本地审核测试通过")
        print("=" * 50)
        print("\n注意: AI 审核需要 AI API 配置")
        print("完整审核请运行: Reviewer.review(session_id)")

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()