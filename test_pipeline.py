# -*- coding: utf-8 -*-
"""
流水线模块测试
测试流水线执行流程
"""
import sys
import shutil
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from memory import MemRouter
from pipeline import PipelineRunner, PipelinePhase, PipelineDrain, AiL1, AiL2, AiL3, LocalTester
from pipeline.PipelineRouter import PipelineRouter


def test_load_prompt():
    """测试加载提示词"""
    print("=" * 50)
    print("测试 1: 加载提示词")
    print("=" * 50)

    runner = PipelineRunner("test_session")

    try:
        prompt = runner.load_prompt("l1_understand")
        print(f"✓ L1 提示词加载成功，长度: {len(prompt)} 字符")
    except FileNotFoundError as e:
        print(f"✗ 提示词文件不存在: {e}")
        return False

    try:
        prompt = runner.load_prompt("l2_interface")
        print(f"✓ L2 提示词加载成功，长度: {len(prompt)} 字符")
    except FileNotFoundError as e:
        print(f"✗ 提示词文件不存在: {e}")
        return False

    try:
        prompt = runner.load_prompt("l3_generate")
        print(f"✓ L3 提示词加载成功，长度: {len(prompt)} 字符")
    except FileNotFoundError as e:
        print(f"✗ 提示词文件不存在: {e}")
        return False

    print("\n✓ 提示词加载测试通过\n")
    return True


def test_ai_l1():
    """测试 L1 AI 模块"""
    print("=" * 50)
    print("测试 2: L1 需求理解")
    print("=" * 50)

    ai_l1 = AiL1()
    user_input = "我想做一个用户管理系统，包含用户注册、登录、查询功能"

    try:
        result = ai_l1.understand(
            "请理解用户需求，输出项目名称、技术栈、功能列表。",
            user_input
        )
        print(f"✓ L1 执行成功")
        print(f"输出预览: {result[:300]}...")
        print()
        return True
    except Exception as e:
        print(f"✗ L1 执行失败: {e}")
        return False


def test_ai_l2():
    """测试 L2 AI 模块"""
    print("=" * 50)
    print("测试 3: L2 接口文档生成")
    print("=" * 50)

    ai_l2 = AiL2()
    requirement = """
## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI
- 项目类型：web_api

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户
"""

    try:
        result = ai_l2.generate_interface(
            "请根据需求设计接口文档。",
            requirement
        )
        print(f"✓ L2 执行成功")
        print(f"输出预览: {result[:300]}...")
        print()
        return True
    except Exception as e:
        print(f"✗ L2 执行失败: {e}")
        return False


def test_ai_l3():
    """测试 L3 AI 模块"""
    print("=" * 50)
    print("测试 4: L3 代码生成")
    print("=" * 50)

    ai_l3 = AiL3()
    interfaces = """
# 接口文档

## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI
- 模块数：1

## 接口列表

### 1. 用户注册
- **方法**: POST
- **路径**: /api/user/register
- **输入参数**:
  - username: string, 必填, 用户名
  - password: string, 必填, 密码
- **输出参数**:
  - code: int, 状态码
  - data: object, 返回数据
"""

    try:
        result = ai_l3.generate_code(
            "请根据接口文档生成代码，包含 main.py, models.py, routes.py。",
            interfaces
        )
        print(f"✓ L3 执行成功")
        print(f"输出预览: {result[:300]}...")
        print()
        return True
    except Exception as e:
        print(f"✗ L3 执行失败: {e}")
        return False


def test_parse_code():
    """测试代码解析"""
    print("=" * 50)
    print("测试 5: 代码解析")
    print("=" * 50)

    ai_l3 = AiL3()
    content = """
这是代码生成结果：

```python filename:main.py
import logging

def main():
    logger = logging.getLogger(__name__)
    logger.info("Hello")

if __name__ == "__main__":
    main()
```

```python filename:models.py
import logging

logger = logging.getLogger(__name__)

class User:
    pass
```
"""

    files = ai_l3.parse_code_files(content)
    print(f"解析出 {len(files)} 个文件:")
    for filename, code in files:
        print(f"  - {filename}: {len(code)} 字符")

    if len(files) == 2:
        print("\n✓ 代码解析测试通过\n")
        return True
    else:
        print("\n✗ 代码解析测试失败\n")
        return False


def test_local_tester():
    """测试本地测试"""
    print("=" * 50)
    print("测试 6: 本地测试")
    print("=" * 50)

    tester = LocalTester()

    # 创建一个临时测试文件
    test_code = '''
# -*- coding: utf-8 -*-
"""测试文件"""

def hello():
    """测试函数"""
    return "Hello, World!"

if __name__ == "__main__":
    print(hello())
'''

    test_dir = Path(__file__).parent / "output" / "test_session"
    test_dir.mkdir(parents=True, exist_ok=True)

    test_file = test_dir / "test_hello.py"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)

    results = tester.run_tests(
        test_dir,
        contract={"check_anchors": False, "check_logging": False},
    )
    print(f"测试结果:")
    for key, result in results.items():
        if isinstance(result, dict):
            status = "✓" if result.get("passed") else "✗"
            print(f"  {status} {result['name']}: {result.get('details', '')[:50]}")

    print()
    return results.get("all_passed", False)


def test_pipeline_runner():
    """测试流水线执行器"""
    print("=" * 50)
    print("测试 7: 流水线执行器初始化")
    print("=" * 50)

    runner = PipelineRunner("test_session")
    status = runner.get_status()

    print(f"Session ID: {status['session_id']}")
    print(f"当前阶段: {status['current_phase']}")
    print(f"有需求文档: {status['has_requirement']}")
    print(f"有接口文档: {status['has_interfaces']}")
    print(f"有代码: {status['has_code']}")

    print("\n✓ 流水线执行器初始化测试通过\n")
    return True


def test_pipeline_drain_control():
    """测试 Drain 控制：停止扩张，完成已开始 run 后创建 checkpoint"""
    print("=" * 50)
    print("测试 8: Pipeline Drain 控制")
    print("=" * 50)

    session_id = MemRouter.create_session("user_drain", "Drain 控制测试")
    session_dir = Path(__file__).parent / "memory" / "sessions" / session_id

    try:
        run_id = PipelineDrain.begin_run(session_id, run_type="unit_test", source="test_pipeline")
        state = PipelineDrain.get_state(session_id)
        assert state["mode"] == PipelineDrain.ACTIVE
        assert state["active_run_id"] == run_id

        state = PipelineDrain.request_drain(session_id, reason="new_requirement_waiting")
        assert state["mode"] == PipelineDrain.DRAINING
        assert state["reject_new_pipeline"] is True

        blocked = PipelineRouter.run_with_interfaces(session_id, "## 接口列表\n### 1. GET /api/items")
        assert blocked["success"] is False
        assert "Pipeline 未启动" in blocked["message"]

        state = PipelineDrain.complete_run(
            session_id,
            run_id,
            success=True,
            phase=PipelinePhase.COMPLETE.value,
            message="running pipeline finished",
            files=[],
        )
        assert state["mode"] == PipelineDrain.READY
        assert state["active_run_id"] == ""
        assert state["last_checkpoint_snapshot"]
        assert MemRouter.latest_snapshot(session_id)["id"] == state["last_checkpoint_snapshot"]
        assert state["cancelled_pending"]

        print("✓ Drain 控制测试通过\n")
        return True
    except Exception as e:
        print(f"✗ Drain 控制测试失败: {e}")
        return False
    finally:
        if session_dir.exists():
            shutil.rmtree(session_dir)


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("流水线模块测试")
    print("=" * 60 + "\n")

    results = []

    results.append(("加载提示词", test_load_prompt()))
    results.append(("L1 需求理解", test_ai_l1()))
    results.append(("L2 接口文档", test_ai_l2()))
    results.append(("L3 代码生成", test_ai_l3()))
    results.append(("代码解析", test_parse_code()))
    results.append(("本地测试", test_local_tester()))
    results.append(("流水线执行器", test_pipeline_runner()))
    results.append(("Pipeline Drain 控制", test_pipeline_drain_control()))

    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status} - {name}")

    all_passed = all(r[1] for r in results)
    print("\n" + ("=" * 60))
    if all_passed:
        print("所有测试通过!")
    else:
        print("部分测试失败，请检查错误信息")
    print("=" * 60)


if __name__ == "__main__":
    main()
