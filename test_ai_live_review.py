# -*- coding: utf-8 -*-
"""
真实 AI 审核冒烟测试。

默认不会被其他测试脚本调用；需要验证提示词和审核边界时手动运行：
python test_ai_live_review.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from review import AiArtifactReviewer


def sample_tiny_blueprint():
    """一个极小的 AI 蓝图样例：单模块、单接口、无跨模块依赖。"""
    return {
        "version": "1.0",
        "project_map": {
            "project_name": "待办事项 API",
            "module_count": 1,
            "modules": ["todo.core"],
        },
        "module_cards": [
            {
                "id": "todo.core",
                "name": "待办事项核心",
                "responsibility": "负责创建待办事项",
                "public_interfaces": ["todo.core.create"],
                "depends_on": [],
                "status": "planned",
            }
        ],
        "interface_registry": {
            "public_interfaces": [
                {
                    "id": "todo.core.create",
                    "owner_module": "todo.core",
                    "method": "POST",
                    "path": "/api/todos",
                }
            ],
            "shared_models": [
                {
                    "id": "todo.todo_item",
                    "owner_module": "todo.core",
                    "fields": ["id", "title", "completed", "created_at"],
                }
            ],
        },
        "dependency_graph": {
            "nodes": [{"id": "todo.core"}],
            "edges": [],
        },
        "batch_plan": {
            "active_batch": "batch_1",
            "batches": [
                {"id": "batch_1", "status": "planned", "modules": ["todo.core"]},
            ],
        },
        "assembly": {
            "entrypoint": "main.py",
            "interface_ledger": "interfaces/index.yaml",
            "module_exports": [
                {
                    "module": "todo.core",
                    "package": "modules/todo/core",
                    "export": "get_router",
                    "mount_path": "/api/todos",
                    "interfaces": ["todo.core.create"],
                }
            ],
        },
    }


def main():
    requirement = """
## 项目信息
- 项目名称：待办事项 API
- 技术栈：Python + FastAPI

## 功能列表
1. 创建待办事项
"""

    result = AiArtifactReviewer.review_pmc_blueprint(requirement, sample_tiny_blueprint())
    print("=" * 60)
    print("真实 AI 审核结果")
    print("=" * 60)
    print(f"verdict: {result.verdict}")
    print(f"passed: {result.passed}")
    print(f"reason: {result.reason}")
    print(f"must_fix: {result.must_fix}")
    print(f"prompt_notes: {result.prompt_notes}")
    print("\nraw:")
    print(result.raw)

    if not result.verdict:
        raise AssertionError("AI 审核没有返回 verdict")
    if not result.passed:
        raise AssertionError(f"AI 审核打回: {result.reason}")


if __name__ == "__main__":
    main()
