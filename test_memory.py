# -*- coding: utf-8 -*-
"""
Memory 模块测试脚本
测试 Memory 模块的各个子模块

测试场景：
1. 创建 Session
2. 写入需求草稿（不推进阶段）
3. 确认需求（推进到 phase_2）
4. 写入接口草稿
5. 确认接口（推进到 phase_3）
6. 测试阶段门禁
7. 测试模块上下文
"""
import sys
import os
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import MemRouter, MemSession, MemPhase
from pipeline import PipelineDrain


def test_create_session():
    """测试创建 Session"""
    print("测试: 创建 Session")
    session_id = MemRouter.create_session("user_001", "测试项目")
    print(f"  Session ID: {session_id}")

    meta = MemRouter.get_session(session_id)
    print(f"  项目名: {meta['session']['project_name']}")
    print(f"  初始阶段: {meta['session']['phase']}")
    print(f"  上下文: {meta['context']}")
    print("  PASS")
    return session_id


def test_requirement_flow(session_id):
    """测试需求流程：草稿 -> 确认"""
    print("\n测试: 需求流程")

    # 1. 写入需求草稿（不推进阶段）
    print("  [1] 写入需求草稿...")
    requirement_content = """## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户
"""
    MemRouter.write(session_id, 'requirement', requirement_content, source='AI')

    context = MemRouter.read(session_id, 'context')
    print(f"      requirement_draft: {context.get('requirement_draft')}")
    print(f"      requirement_ready: {context.get('requirement_ready')}")
    assert context.get('requirement_draft') == True
    assert context.get('requirement_ready') == False

    status = MemRouter.get_phase_status(session_id)
    print(f"      当前阶段: {status['current_phase']} (应该是 phase_1)")
    assert status['current_phase'] == 'phase_1'

    # 2. 确认需求（推进到 phase_2）
    print("  [2] 确认需求...")
    MemRouter.write(session_id, 'requirement_confirm', '', source='User')

    context = MemRouter.read(session_id, 'context')
    print(f"      requirement_draft: {context.get('requirement_draft')}")
    print(f"      requirement_ready: {context.get('requirement_ready')}")
    assert context.get('requirement_ready') == True

    status = MemRouter.get_phase_status(session_id)
    print(f"      当前阶段: {status['current_phase']} (应该是 phase_2)")
    assert status['current_phase'] == 'phase_2'

    print("  PASS")


def test_interfaces_flow(session_id):
    """测试接口流程：草稿 -> 确认"""
    print("\n测试: 接口流程")

    # 1. 写入接口草稿
    print("  [1] 写入接口草稿...")
    interfaces_content = """## 接口列表

### 1. 用户注册 POST /api/user/register
- 输入: username, password, email
- 输出: user_id, token

### 2. 用户登录 POST /api/user/login
- 输入: username, password
- 输出: user_id, token
"""
    MemRouter.write(session_id, 'interfaces', interfaces_content, source='AI')
    MemRouter.write(session_id, 'interfaces_confirm', '', source='User')

    context = MemRouter.read(session_id, 'context')
    print(f"      interfaces_draft: {context.get('interfaces_draft')}")
    print(f"      interfaces_ready: {context.get('interfaces_ready')}")
    assert context.get('interfaces_draft') == True
    assert context.get('interfaces_ready') == True  # write_interfaces 自动确认

    status = MemRouter.get_phase_status(session_id)
    print(f"      当前阶段: {status['current_phase']} (应该是 phase_3)")
    assert status['current_phase'] == 'phase_3'

    print("  PASS")


def test_phase_gate(session_id):
    """测试阶段门禁"""
    print("\n测试: 阶段门禁")

    # 当前在 phase_3
    can_enter_p1, msg = MemRouter.check_phase_gate(session_id, 'phase_1')
    can_enter_p2, msg = MemRouter.check_phase_gate(session_id, 'phase_2')
    can_enter_p3, msg = MemRouter.check_phase_gate(session_id, 'phase_3')
    can_enter_p4, msg = MemRouter.check_phase_gate(session_id, 'phase_4')
    can_enter_p5, msg = MemRouter.check_phase_gate(session_id, 'phase_5')

    print(f"  进入 phase_1: {can_enter_p1} (已过阶段，禁止后退)")
    print(f"  进入 phase_2: {can_enter_p2} (已过阶段，禁止后退)")
    print(f"  进入 phase_3: {can_enter_p3} (当前阶段，允许)")
    print(f"  进入 phase_4: {can_enter_p4} (下一阶段，interfaces_ready=True，允许)")
    print(f"  进入 phase_5: {can_enter_p5} (跳跃，禁止)")

    assert can_enter_p1 == False  # 不能后退
    assert can_enter_p2 == False  # 不能后退
    assert can_enter_p3 == True   # 当前阶段
    assert can_enter_p4 == True   # 下一阶段
    assert can_enter_p5 == False  # 跳跃

    print("  PASS")


def test_module_context(session_id):
    """测试模块独立上下文"""
    print("\n测试: 模块独立上下文")

    # PMC 模块写入自己的上下文
    pmc_data = {
        "decision": "simple",
        "interface_count": 2,
        "chain": "simple"
    }
    MemRouter.update_module_context(session_id, 'pmc', pmc_data)

    # 读取 PMC 上下文
    pmc_context = MemRouter.read_module_context(session_id, 'pmc')
    print(f"  PMC 上下文: {pmc_context['data']}")
    assert pmc_context['data']['decision'] == 'simple'

    # 流水线模块写入自己的上下文
    pipe_data = {
        "workers": ["UserWorker", "AuthWorker"],
        "generated_files": ["user.py", "auth.py"]
    }
    MemRouter.update_module_context(session_id, 'pipeline', pipe_data)

    # 读取流水线上下文
    pipe_context = MemRouter.read_module_context(session_id, 'pipeline')
    print(f"  流水线上下文: {pipe_context['data']}")
    assert pipe_context['data']['workers'] == ["UserWorker", "AuthWorker"]

    print("  PASS")


def test_chat_and_read(session_id):
    """测试对话记录和读取"""
    print("\n测试: 对话记录")

    MemRouter.write(session_id, 'chat_raw', "## 用户输入\n用户说：我要一个用户管理系统", source='User')
    MemRouter.write(session_id, 'chat_raw', "## AI 理解\n我理解您的需求：用户注册、登录、查询", source='AI')

    chat = MemRouter.read(session_id, 'chat')
    print(f"  对话记录长度: {len(chat)} 字符")
    assert '用户管理系统' in chat
    assert 'AI 理解' in chat

    print("  PASS")


def test_change_gate_blocks_until_complete():
    """测试当前工作未完成时，新需求只能进入等待区"""
    print("\n测试: 新需求门禁 - 未完成进入等待区")

    session_id = MemRouter.create_session("user_change_block", "变更阻塞测试")
    MemRouter.write(session_id, 'requirement', "## 功能列表\n1. 初始功能", source='AI')
    MemRouter.write(session_id, 'requirement_confirm', '', source='User')
    current_requirement = MemRouter.read(session_id, 'requirement')

    can_accept, msg = MemRouter.can_accept_new_requirement(session_id)
    print(f"  是否可进入工作区: {can_accept} ({msg})")
    assert can_accept == False

    try:
        MemRouter.write(session_id, 'requirement', "## 功能列表\n1. 新需求", source='AI')
        raise AssertionError("未完成工作不应允许覆盖当前工作区需求")
    except PermissionError as exc:
        print(f"  工作区阻塞原因: {exc}")

    pending_id = MemRouter.write(session_id, 'pending_requirement', "## 功能列表\n1. 新需求", source='User')
    pending = MemRouter.list_pending_requirements(session_id)
    print(f"  等待区需求: {pending}")
    assert pending_id == 'pending_001'
    assert len(pending) == 1
    assert pending[0]['status'] == 'pending'
    assert MemRouter.read(session_id, 'requirement') == current_requirement
    context = MemRouter.read(session_id, 'context')
    assert context.get('pipeline_mode') == PipelineDrain.READY
    assert context.get('stable_checkpoint')
    can_start_pipeline, drain_msg = PipelineDrain.can_start_pipeline(session_id)
    print(f"  Drain 后是否可启动新 Pipeline: {can_start_pipeline} ({drain_msg})")
    assert can_start_pipeline == False

    print("  PASS")


def test_change_gate_after_completion():
    """测试完成快照后可以开始新需求，并使下游产物失效"""
    print("\n测试: 新需求门禁 - 完成后允许变更")

    session_id = MemRouter.create_session("user_change_ok", "变更允许测试")
    output_dir = Path(__file__).parent / "output" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "main.py"
    output_file.write_text("# generated\n", encoding="utf-8")

    MemRouter.write(session_id, 'requirement', "## 功能列表\n1. 初始功能", source='AI')
    MemRouter.write(session_id, 'requirement_confirm', '', source='User')
    MemRouter.write(session_id, 'interfaces', "## 接口列表\n### 1. GET /api/items", source='AI')
    MemRouter.write(session_id, 'interfaces_confirm', '', source='User')
    MemRouter.update_module_context(session_id, 'pmc', {"decision": "simple"})

    MemRouter.complete_phase(session_id, 'phase_3')
    MemRouter.complete_phase(session_id, 'phase_4')
    MemRouter.complete_phase(session_id, 'phase_5')
    MemRouter.complete_phase(session_id, 'phase_6')

    latest = MemRouter.latest_snapshot(session_id)
    print(f"  完成快照: {latest}")
    assert latest is not None
    assert latest['phase'] == 'phase_6'
    assert latest['phase_status'] == 'completed'

    can_accept, msg = MemRouter.can_accept_new_requirement(session_id)
    print(f"  是否可接新需求: {can_accept} ({msg})")
    assert can_accept == True

    pending_id = MemRouter.write(session_id, 'pending_requirement', "## 功能列表\n1. 新需求", source='User')
    applied_id = MemRouter.start_next_pending_requirement(session_id)
    assert applied_id == pending_id

    status = MemRouter.get_phase_status(session_id)
    context = status['context']
    print(f"  变更后阶段: {status['current_phase']}")
    print(f"  变更后上下文: {context}")
    assert status['current_phase'] == 'phase_1'
    assert context.get('active_change') == True
    assert context.get('requirement_draft') == True
    assert context.get('requirement_ready') == False
    assert context.get('interfaces_ready') == False
    assert context.get('pending_requirements') == 0

    interfaces_file = Path(__file__).parent / "memory" / "sessions" / session_id / "logs" / "interfaces.md"
    requirement_file = Path(__file__).parent / "memory" / "sessions" / session_id / "logs" / "requirement.md"
    pmc_file = Path(__file__).parent / "memory" / "sessions" / session_id / "context" / "pmc" / "pmc_context.yaml"
    assert not interfaces_file.exists()
    assert pmc_file.exists()
    assert requirement_file.read_text(encoding="utf-8-sig").startswith("# 需求文档（草稿）")

    pmc_context = MemRouter.read_module_context(session_id, 'pmc')
    print(f"  PMC 失效上下文: {pmc_context['data']}")
    assert pmc_context['data']['stale'] == True

    pending = MemRouter.list_pending_requirements(session_id)
    print(f"  等待区状态: {pending}")
    assert pending[0]['status'] == 'applied'

    if output_dir.exists():
        shutil.rmtree(output_dir)

    print("  PASS")


def main():
    print("=" * 50)
    print("Memory 模块测试（完整流程）")
    print("=" * 50)

    try:
        session_id = test_create_session()
        test_requirement_flow(session_id)
        test_interfaces_flow(session_id)
        test_phase_gate(session_id)
        test_module_context(session_id)
        test_chat_and_read(session_id)
        test_change_gate_blocks_until_complete()
        test_change_gate_after_completion()

        print("\n" + "=" * 50)
        print("所有测试通过")
        print("=" * 50)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
