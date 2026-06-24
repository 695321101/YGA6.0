# -*- coding: utf-8 -*-
"""
真实 AI 的 PMC 分层拆分冒烟测试。

默认不会被其他测试脚本调用；需要验证分层拆分提示词和审核边界时手动运行：
python test_pmc_layered_live.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pmc import PmcLayeredSplitter, PmcBlueprint


def main():
    session_id = "sess_layered_live"
    output_dir = Path(__file__).parent / "output" / session_id
    if output_dir.exists():
        shutil.rmtree(output_dir)

    requirement = """
## 项目信息
- 项目名称：待办事项 API
- 技术栈：Python + FastAPI

## 功能列表
1. 创建待办事项
2. 查询待办事项
"""

    try:
        result = PmcLayeredSplitter.split(session_id, requirement, require_ai_review=True)
        issues, suggestions = PmcBlueprint.validate(result.blueprint)

        print("=" * 60)
        print("真实 AI PMC 分层拆分结果")
        print("=" * 60)
        print(f"项目域数量: {len(result.project_domains.get('domains', []))}")
        print(f"域内拆分数量: {len(result.domain_modules.get('domains', []))}")
        print(f"模块数量: {len(result.blueprint.get('module_cards', []))}")
        print(f"接口数量: {len(result.blueprint.get('interface_registry', {}).get('public_interfaces', []))}")
        print(f"审核次数: {len(result.reviews)}")
        print(f"确定性问题: {issues}")
        print(f"建议: {suggestions}")
        print("产物:")
        for name, path in result.artifacts.items():
            print(f"  - {name}: {path}")

        if issues:
            raise AssertionError(f"蓝图确定性验收失败: {issues}")
        if not result.reviews or not all(item.get("passed") for item in result.reviews):
            raise AssertionError("存在未通过的 AI 审核")
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)


if __name__ == "__main__":
    main()
