# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: review
file: review/Reviewer.py
responsibility: 审核员模块（本地审核 + AI 审核）
exports: Reviewer
authority: .claude/planning/11_记忆区模块设计.md
</YGA_FILE_ANCHOR>
"""
import os
import sys
from pathlib import Path
from typing import Tuple, List, Optional, Dict


class LocalReviewer:
    """
    本地审核员 - 只审核100%能确定的事情

    本地审核范围：
    - 文件是否存在
    - 文件格式是否正确
    - YAML 语法是否正确
    - 必需字段是否存在
    - 类型是否匹配
    - 字符串/数字/布尔值

    本地审核不包括：
    - 业务逻辑判断
    - 设计合理性
    - 潜在问题发现
    """

    # 必须包含 YGA 锚点的文件
    YGA_FILES = [
        'memory/MemSession.py',
        'memory/MemWriter.py',
        'memory/MemReader.py',
        'memory/MemPhase.py',
        'memory/MemRouter.py',
    ]

    @staticmethod
    def review_file(file_path: str) -> Tuple[bool, Optional[str]]:
        """
        审核单个文件

        Returns:
            (是否通过, 错误信息)
        """
        if not os.path.exists(file_path):
            return False, f"文件不存在: {file_path}"

        # 检查文件编码
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except UnicodeDecodeError:
            return False, f"文件编码错误: {file_path}"

        # 如果是 Python 文件
        if file_path.endswith('.py'):
            return LocalReviewer._review_python_file(file_path, content)

        # 如果是 YAML 文件
        if file_path.endswith('.yaml') or file_path.endswith('.yml'):
            return LocalReviewer._review_yaml_file(file_path, content)

        # 如果是 Markdown 文件
        if file_path.endswith('.md'):
            return LocalReviewer._review_markdown_file(file_path, content)

        return True, None

    @staticmethod
    def _review_python_file(file_path: str, content: str) -> Tuple[bool, Optional[str]]:
        """审核 Python 文件"""
        # 检查 YGA 文件锚点
        file_name = os.path.basename(file_path)
        if file_name in [os.path.basename(f) for f in LocalReviewer.YGA_FILES]:
            if '<YGA_FILE_ANCHOR' not in content:
                return False, f"缺少 YGA_FILE_ANCHOR: {file_path}"
            if '<YGA_END_ANCHOR' not in content:
                return False, f"缺少 YGA_END_ANCHOR: {file_path}"

        # 检查语法错误
        try:
            compile(content, file_path, 'exec')
        except SyntaxError as e:
            return False, f"语法错误: {file_path} ({e})"

        return True, None

    @staticmethod
    def _review_yaml_file(file_path: str, content: str) -> Tuple[bool, Optional[str]]:
        """审核 YAML 文件"""
        import yaml

        try:
            data = yaml.safe_load(content)
            if data is None:
                return False, f"YAML 解析为空: {file_path}"
        except yaml.YAMLError as e:
            return False, f"YAML 语法错误: {file_path} ({e})"

        return True, None

    @staticmethod
    def _review_markdown_file(file_path: str, content: str) -> Tuple[bool, Optional[str]]:
        """审核 Markdown 文件"""
        # Markdown 不需要严格审核，只检查是否为空
        if not content or len(content.strip()) < 10:
            return False, f"文件内容过少: {file_path}"

        return True, None

    @staticmethod
    def review_module(module_name: str, files: List[str]) -> Tuple[bool, List[str]]:
        """
        审核整个模块

        Returns:
            (是否通过, 错误列表)
        """
        errors = []

        for file_path in files:
            passed, error = LocalReviewer.review_file(file_path)
            if not passed:
                errors.append(error)

        return len(errors) == 0, errors


class AIReviewer:
    """
    AI 审核员 - 审核复杂逻辑和设计

    AI 审核范围：
    - 记忆区内容（需求文档、接口文档、上下文）
    - 工作AI生成的代码（generated/ 目录）
    - 业务逻辑是否合理
    - 代码是否满足需求
    """

    SYSTEM_PROMPT = """你是 YGA 的交付前 AI 审核员。
当前阶段：Review。
当前区域：审核区。
当前模块：交付前审核模块；它审核当前代码产物，不重新规划项目模块，不替代码开发区补写实现。
输入来源：记忆区需求文档、接口文档、上下文状态、本地门禁结果和工作 AI 生成的代码。
产物用途：决定代码是否可以交付，或打回 Pipeline 修改。

你不替代本地确定性门禁；文件存在、编码、语法、YAML/JSON 可解析等由本地检查负责。
你负责复杂质量判断：需求符合度、接口符合度、业务逻辑、明显 bug、安全风险、日志是否足够支撑普通用户反馈问题。

## 审核依据

### 1. 记忆区 - 需求文档
- 项目需求和功能列表
- 技术栈要求

### 2. 记忆区 - 接口文档
- API 接口定义
- 请求/响应格式

### 3. 工作AI生成的代码
- generated/ 目录下的代码文件

## 审核要求

1. **需求匹配**: 代码是否实现了需求文档中的功能
2. **接口一致**: API 接口是否按接口文档实现
3. **技术栈**: 是否使用了需求文档中指定的技术栈
4. **代码质量**: 是否有明显bug、安全问题

## 输出格式

审核结果只输出以下三种之一：
- `通过` - 所有检查项都通过
- `打回: [原因]` - 有问题，说明原因，要求修改"""

    @staticmethod
    def _get_generated_code(session_id: str, code_dir: Path = None) -> str:
        """获取工作 AI 生成的代码（优先 output/{session}/modules/）。"""
        root = Path(__file__).parent.parent
        if code_dir is None:
            output_base = root / "output" / session_id / "modules"
            if output_base.exists():
                py_files = sorted(output_base.rglob("*.py"))
            else:
                py_files = []
        else:
            py_files = sorted(Path(code_dir).glob("*.py"))

        if not py_files:
            session_dir = root / "memory" / "sessions" / session_id
            generated_dir = session_dir / "generated"
            if generated_dir.exists():
                py_files = sorted(generated_dir.glob("*.py"))

        if not py_files:
            return "（无生成的代码）"

        code_files = []
        for py_file in py_files:
            try:
                with open(py_file, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                rel = py_file.name
                code_files.append(f"### {rel}\n```python\n{content}\n```")
            except Exception:
                code_files.append(f"### {py_file.name}\n（读取失败）")

        return "\n\n".join(code_files)

    @staticmethod
    def review_with_ai(
        session_id: str,
        context_str: str,
        phase_status: dict,
        code_dir: Path = None,
        gate_results: Dict = None,
    ) -> str:
        """
        使用 AI 进行审核

        Args:
            session_id: Session ID
            context_str: 上下文字符串
            phase_status: 阶段状态

        Returns:
            审核结果: "通过" 或 "打回: [原因]"
        """
        from memory import MemRouter

        # 准备审核数据
        meta = MemRouter.get_session(session_id)
        requirement = MemRouter.read(session_id, 'requirement') or "（无需求文档）"
        interfaces = MemRouter.read(session_id, 'interfaces') or "（无接口文档）"
        generated_code = AIReviewer._get_generated_code(session_id, code_dir=code_dir)
        gate_section = ""
        if gate_results:
            gate_section = f"\n## LocalGate 结果\n{gate_results}\n"

        review_prompt = f"""## Session 信息
- Session ID: {session_id}
- 项目名: {meta['session']['project_name']}
- 当前阶段: {phase_status['current_phase']}
- 阶段状态: {phase_status['phase_status']}

## 上下文状态
{context_str}

## 需求文档
{requirement}

## 接口文档
{interfaces}

## 工作AI生成的代码
{generated_code}
{gate_section}

请根据需求文档和接口文档，审核工作AI生成的代码是否符合要求。"""

        try:
            ai_response = AIReviewer._call_ai(review_prompt)
            return ai_response
        except Exception as e:
            return f"AI 审核失败: {e}"

    @staticmethod
    def _call_ai(prompt: str) -> str:
        """调用 AI"""
        import json
        import requests

        config_path = Path(__file__).parent.parent / 'config' / 'ai_config.json'
        with open(config_path, 'r', encoding='utf-8-sig') as f:
            config = json.load(f)

        payload = {
            "model": config.get('model', 'agnes-2.0-flash'),
            "messages": [
                {"role": "system", "content": AIReviewer.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }

        proxies = None
        if config.get('proxy_url'):
            proxies = {"http": config['proxy_url'], "https": config['proxy_url']}

        response = requests.post(
            config['api_base'] + "/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json"
            },
            json=payload,
            proxies=proxies,
            timeout=60
        )

        if response.status_code != 200:
            raise Exception(f"AI API 错误: {response.status_code}")

        result = response.content.decode('utf-8-sig')
        result = json.loads(result)
        return result['choices'][0]['message']['content']


class Reviewer:
    """
    审核员入口 - 本地审核 + AI 审核

    审核流程：
    1. 本地审核 - 100% 确定的事情
    2. AI 审核 - 复杂逻辑和设计
    3. 输出结果
    """

    @staticmethod
    def review_session_delivery(
        session_id: str,
        code_dir: Path,
        gate_results: Dict = None,
    ) -> str:
        """Simple 交付前 AI 终审（读 requirement、interfaces、output 代码、LocalGate）。"""
        from memory import MemRouter

        context = MemRouter.read(session_id, "context") or {}
        phase_status = MemRouter.get_phase_status(session_id)
        context_str = ""
        if isinstance(context, dict):
            for key, value in context.items():
                context_str += f"- {key}: {value}\n"
        else:
            context_str = str(context)

        return AIReviewer.review_with_ai(
            session_id,
            context_str,
            phase_status,
            code_dir=Path(code_dir),
            gate_results=gate_results,
        )

    @staticmethod
    def review(session_id: str, files: List[str] = None) -> str:
        """
        执行审核

        Args:
            session_id: Session ID
            files: 要审核的文件列表（默认审核 memory 模块）

        Returns:
            审核结果
        """
        if files is None:
            files = LocalReviewer.YGA_FILES

        # 1. 本地审核
        print("=" * 40)
        print("本地审核...")
        print("=" * 40)

        local_passed, local_errors = LocalReviewer.review_module('memory', files)

        if not local_passed:
            print("\n本地审核失败:")
            for error in local_errors:
                print(f"  - {error}")
            return f"打回: 本地审核失败\n" + "\n".join(local_errors)

        print("本地审核通过 ✓")

        # 2. AI 审核
        print("\n" + "=" * 40)
        print("AI 审核...")
        print("=" * 40)

        # 获取模块上下文
        from memory import MemRouter
        context = MemRouter.read(session_id, 'context')
        phase_status = MemRouter.get_phase_status(session_id)

        # 将 context 转为可读字符串
        context_str = ""
        if isinstance(context, dict):
            for key, value in context.items():
                context_str += f"- {key}: {value}\n"
        else:
            context_str = str(context)

        ai_result = AIReviewer.review_with_ai(session_id, context_str, phase_status)

        # 3. 输出结果
        print("\n" + "=" * 40)
        print("审核结果")
        print("=" * 40)

        if ai_result.strip() == "通过":
            print("通过")
            return "通过"
        else:
            print(ai_result)
            return ai_result


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发完成
# contract: 11_记忆区模块设计.md
# next: 其他模块通过 Reviewer.review() 调用审核
# </YGA_END_ANCHOR>
