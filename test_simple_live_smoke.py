# -*- coding: utf-8 -*-
"""
Simple 主链真实 AI 冒烟（需 config/ai_config.json）。

手动运行：
  python test_simple_live_smoke.py
  python test_simple_live_smoke.py --minimal   # 极小需求，省 token

成功标准：PipelineRouter.run 返回 success=True，phase_6 完成且有快照。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory import MemRouter
from pipeline import PipelineRouter


MINIMAL_REQUIREMENT = """## 项目信息
- 项目名称：两数相加
- 技术栈：Python

## 功能列表
1. 输入两个数字，返回相加结果
"""

STANDARD_REQUIREMENT = """## 项目信息
- 项目名称：简易计算器
- 技术栈：Python

## 功能列表
1. 加法
2. 减法
"""


def main():
    parser = argparse.ArgumentParser(description="Simple 主链 live 冒烟")
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="使用极小需求（单功能）",
    )
    args = parser.parse_args()

    requirement = MINIMAL_REQUIREMENT if args.minimal else STANDARD_REQUIREMENT

    session_id = MemRouter.create_session("live_smoke", "Simple Live 冒烟")
    MemRouter.write(session_id, "requirement", requirement, source="AI")
    MemRouter.write(session_id, "requirement_confirm", "", source="User")

    print("=" * 60)
    print("Simple 主链 Live 冒烟")
    print("=" * 60)
    print(f"session_id: {session_id}")
    print("调用真实 AI（L2 / L3 / 审核）…")

    result = PipelineRouter.run(session_id, require_ai_review=True)

    print(f"success: {result.get('success')}")
    print(f"message: {result.get('message')}")
    print(f"orchestrator: {result.get('orchestrator')}")
    if result.get("error"):
        print(f"error: {result.get('error')}")
    if result.get("delivery"):
        print(f"delivery: {result.get('delivery')}")

    phase = MemRouter.get_phase_status(session_id)
    print(f"phase: {phase.get('current_phase')} / {phase.get('phase_status')}")

    if not result.get("success"):
        raise SystemExit(f"Live 冒烟失败: {result.get('message')}")

    if phase.get("current_phase") != "phase_6":
        raise SystemExit(f"未到达 phase_6: {phase}")

    snap = MemRouter.latest_snapshot(session_id)
    if not snap:
        raise SystemExit("缺少完成快照")

    print("=" * 60)
    print("Live 冒烟通过")
    print("=" * 60)


if __name__ == "__main__":
    main()