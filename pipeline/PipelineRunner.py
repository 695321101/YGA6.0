# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pipeline
file: pipeline/PipelineRunner.py
responsibility: 流水线执行器 - 读取接口文档，生成代码
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
import os
import re
import yaml
from enum import Enum
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.AiL1 import AiL1
from pipeline.AiL2 import AiL2
from pipeline.AiL3 import AiL3
from pipeline.LocalTester import LocalTester
from review import Reviewer


class PipelinePhase(Enum):
    """流水线阶段"""
    L1_UNDERSTAND = "l1_understand"      # 需求理解
    L2_INTERFACE = "l2_interface"       # 接口文档
    L3_GENERATE = "l3_generate"          # 代码生成
    LOCAL_TEST = "local_test"            # 本地测试
    COMPLETE = "complete"                # 完成


@dataclass
class PipelineContext:
    """流水线上下文"""
    session_id: str
    requirement: str = ""
    interfaces: str = ""
    generated_code: str = ""
    test_result: Dict = field(default_factory=dict)
    current_phase: PipelinePhase = PipelinePhase.L1_UNDERSTAND
    error_message: str = ""


@dataclass
class PipelineResult:
    """流水线执行结果"""
    success: bool
    phase: PipelinePhase
    output: str = ""
    files: List[str] = field(default_factory=list)
    test_results: Dict = field(default_factory=dict)
    error: str = ""
    message: str = ""


@dataclass
class ReviewResult:
    """审核结果"""
    passed: bool
    phase: PipelinePhase
    reviewer_type: str = ""  # "local" 或 "ai"
    message: str = ""
    reason: str = ""  # 如果打回，记录原因


class PipelineRunner:
    """
    流水线执行器

    职责：
    1. 读取接口文档
    2. 执行各阶段 AI 生成
    3. 调用本地测试
    4. 输出代码文件
    """

    # Prompt 路径
    PROMPT_DIR = Path(__file__).parent.parent / "prompts"

    # 代码输出目录
    OUTPUT_DIR = Path(__file__).parent.parent / "output"

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.context = PipelineContext(session_id=session_id)
        self.ai_l1 = AiL1()
        self.ai_l2 = AiL2()
        self.ai_l3 = AiL3()
        self.local_tester = LocalTester()

    def load_prompt(self, prompt_name: str) -> str:
        """加载提示词文件"""
        prompt_path = self.PROMPT_DIR / f"{prompt_name}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")

        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 去掉 YGA 锚点部分
        content = re.sub(r'# -\*- coding: utf-8 -\*-\n', '', content)
        content = re.sub(r'"""[\s\S]*?"""', '', content)
        return content.strip()

    def get_output_dir(self) -> Path:
        """获取输出目录"""
        output_dir = self.OUTPUT_DIR / self.session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def run_l1_understand(self, user_input: str) -> PipelineResult:
        """
        执行 L1 需求理解

        Args:
            user_input: 用户原始需求

        Returns:
            PipelineResult
        """
        try:
            prompt = self.load_prompt("l1_understand")
            result = self.ai_l1.understand(prompt, user_input)

            self.context.requirement = result
            self.context.current_phase = PipelinePhase.L1_UNDERSTAND

            return PipelineResult(
                success=True,
                phase=PipelinePhase.L1_UNDERSTAND,
                output=result,
                message="需求理解完成"
            )
        except Exception as e:
            return PipelineResult(
                success=False,
                phase=PipelinePhase.L1_UNDERSTAND,
                error=str(e),
                message=f"需求理解失败: {e}"
            )

    def run_l2_interface(self) -> PipelineResult:
        """
        执行 L2 接口文档生成

        Returns:
            PipelineResult
        """
        try:
            prompt = self.load_prompt("l2_interface")
            result = self.ai_l2.generate_interface(prompt, self.context.requirement)

            self.context.interfaces = result
            self.context.current_phase = PipelinePhase.L2_INTERFACE

            return PipelineResult(
                success=True,
                phase=PipelinePhase.L2_INTERFACE,
                output=result,
                message="接口文档生成完成"
            )
        except Exception as e:
            return PipelineResult(
                success=False,
                phase=PipelinePhase.L2_INTERFACE,
                error=str(e),
                message=f"接口文档生成失败: {e}"
            )

    def run_l3_generate(self) -> PipelineResult:
        """
        执行 L3 代码生成

        Returns:
            PipelineResult
        """
        try:
            prompt = self.load_prompt("l3_generate")
            result = self.ai_l3.generate_code(prompt, self.context.interfaces)

            self.context.generated_code = result
            self.context.current_phase = PipelinePhase.L3_GENERATE

            # 保存代码文件
            output_dir = self.get_output_dir()
            files = self._save_code_files(result, output_dir)

            return PipelineResult(
                success=True,
                phase=PipelinePhase.L3_GENERATE,
                output=result,
                files=files,
                message=f"代码生成完成，生成了 {len(files)} 个文件"
            )
        except Exception as e:
            return PipelineResult(
                success=False,
                phase=PipelinePhase.L3_GENERATE,
                error=str(e),
                message=f"代码生成失败: {e}"
            )

    def run_local_test(self) -> PipelineResult:
        """
        执行本地测试

        Returns:
            PipelineResult
        """
        try:
            output_dir = self.get_output_dir()
            interfaces = self.context.interfaces or ""
            test_results = self.local_tester.run_tests(
                output_dir,
                interfaces=interfaces,
            )

            self.context.test_result = test_results
            self.context.current_phase = PipelinePhase.LOCAL_TEST

            all_passed = test_results.get("all_passed")
            success = all_passed is True or all(
                t.get('passed', False)
                for t in test_results.values()
                if isinstance(t, dict)
            )

            return PipelineResult(
                success=success,
                phase=PipelinePhase.LOCAL_TEST,
                test_results=test_results,
                message="本地测试完成" if success else "本地测试失败"
            )
        except Exception as e:
            return PipelineResult(
                success=False,
                phase=PipelinePhase.LOCAL_TEST,
                error=str(e),
                message=f"本地测试失败: {e}"
            )

    def _save_code_files(self, code_content: str, output_dir: Path) -> List[str]:
        """
        保存代码文件

        Args:
            code_content: AI 生成的代码内容
            output_dir: 输出目录

        Returns:
            保存的文件列表
        """
        saved_files = []

        # 解析代码块
        files = self._parse_code_blocks(code_content)

        for filename, content in files:
            file_path = output_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            saved_files.append(str(file_path))

        return saved_files

    def _parse_code_blocks(self, content: str) -> List[Tuple[str, str]]:
        """
        解析代码块

        Args:
            content: 包含代码块的内容

        Returns:
            [(filename, content), ...]
        """
        files = []

        # 匹配 ```python 或 ``` 包裹的代码块
        pattern = r'```(?:\w+)?\s*(?:filename:(\S+))?\n([\s\S]*?)```'

        for match in re.finditer(pattern, content):
            filename = match.group(1) if match.group(1) else "generated.py"
            code = match.group(2).strip()

            # 从内容中提取文件名（如果 filename 标签没有）
            if not match.group(1):
                # 尝试从代码中提取 __file__
                file_match = re.search(r'["\'](\w+\.py)["\']', code)
                if file_match:
                    filename = file_match.group(1)

            files.append((filename, code))

        # 如果没有代码块，尝试整个内容作为单个文件
        if not files and content.strip():
            # 检查是否是 Python 代码
            if 'def ' in content or 'class ' in content or 'import ' in content:
                files.append(("generated.py", content.strip()))

        return files

    def get_status(self) -> Dict:
        """获取流水线状态"""
        return {
            "session_id": self.session_id,
            "current_phase": self.context.current_phase.value,
            "has_requirement": bool(self.context.requirement),
            "has_interfaces": bool(self.context.interfaces),
            "has_code": bool(self.context.generated_code),
            "test_passed": self.context.test_result.get("all_passed", False) if self.context.test_result else False
        }

    # ========== 审核员方法 ==========

    def _review_l1_result(self) -> ReviewResult:
        """
        审核 L1 需求理解结果

        本地审核：检查需求文档是否包含关键信息
        AI 审核：检查需求是否清晰、完整、可执行
        """
        requirement = self.context.requirement

        # 本地审核：检查基本结构（支持多种格式）
        has_project = '项目' in requirement
        has_function = '功能' in requirement
        has_tech = '技术' in requirement

        if not (has_project and has_function and has_tech):
            missing = []
            if not has_project:
                missing.append('项目')
            if not has_function:
                missing.append('功能')
            if not has_tech:
                missing.append('技术栈')

            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L1_UNDERSTAND,
                reviewer_type="local",
                message="本地审核失败",
                reason=f"需求文档缺少关键字段: {', '.join(missing)}"
            )

        # AI 审核：调用 AI 审核员
        phase_status = {
            "current_phase": "L1_UNDERSTAND",
            "phase_status": "需求理解完成，等待审核"
        }

        context_str = f"需求文档长度: {len(requirement)} 字符\n"
        ai_result = self._call_ai_reviewer(
            context_str,
            phase_status,
            requirement,  # 传入当前阶段输出
            self.context.requirement
        )

        # 解析 AI 审核结果
        if ai_result.strip() == "通过":
            return ReviewResult(
                passed=True,
                phase=PipelinePhase.L1_UNDERSTAND,
                reviewer_type="ai",
                message="AI 审核通过"
            )
        else:
            # 打回：提取原因
            reason = ai_result
            if "打回:" in ai_result:
                reason = ai_result.split("打回:")[1].strip()
            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L1_UNDERSTAND,
                reviewer_type="ai",
                message="AI 审核打回",
                reason=reason
            )

    def _review_l2_result(self) -> ReviewResult:
        """
        审核 L2 接口文档结果

        本地审核：检查接口文档格式
        AI 审核：检查接口是否满足需求
        """
        interfaces = self.context.interfaces

        # 本地审核：检查基本结构（支持多种格式）
        has_interface = '接口' in interfaces
        has_input = '输入' in interfaces or '请求' in interfaces
        has_output = '输出' in interfaces or '响应' in interfaces

        if not (has_interface and has_input and has_output):
            missing = []
            if not has_interface:
                missing.append('接口')
            if not has_input:
                missing.append('输入/请求')
            if not has_output:
                missing.append('输出/响应')

            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L2_INTERFACE,
                reviewer_type="local",
                message="本地审核失败",
                reason=f"接口文档缺少关键章节: {', '.join(missing)}"
            )

        # AI 审核：调用 AI 审核员
        phase_status = {
            "current_phase": "L2_INTERFACE",
            "phase_status": "接口文档生成完成，等待审核"
        }

        context_str = f"接口文档长度: {len(interfaces)} 字符\n"
        ai_result = self._call_ai_reviewer(
            context_str,
            phase_status,
            interfaces,  # 传入当前阶段输出
            self.context.requirement
        )

        # 解析 AI 审核结果
        if ai_result.strip() == "通过":
            return ReviewResult(
                passed=True,
                phase=PipelinePhase.L2_INTERFACE,
                reviewer_type="ai",
                message="AI 审核通过"
            )
        else:
            reason = ai_result
            if "打回:" in ai_result:
                reason = ai_result.split("打回:")[1].strip()
            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L2_INTERFACE,
                reviewer_type="ai",
                message="AI 审核打回",
                reason=reason
            )

    def _review_l3_result(self) -> ReviewResult:
        """
        审核 L3 代码生成结果

        本地审核：检查代码语法
        AI 审核：检查代码是否满足接口文档
        """
        from memory import MemRouter

        # 本地审核：检查生成的代码文件
        output_dir = self.get_output_dir()
        py_files = list(output_dir.glob("*.py"))

        if not py_files:
            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L3_GENERATE,
                reviewer_type="local",
                message="本地审核失败",
                reason="没有生成任何代码文件"
            )

        # 检查语法
        for py_file in py_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    compile(f.read(), str(py_file), 'exec')
            except SyntaxError as e:
                return ReviewResult(
                    passed=False,
                    phase=PipelinePhase.L3_GENERATE,
                    reviewer_type="local",
                    message="本地审核失败",
                    reason=f"代码语法错误: {py_file.name} ({e})"
                )

        # AI 审核：读取记忆区数据，调用 AI 审核员
        requirement = MemRouter.read(self.session_id, 'requirement') or ""
        interfaces = MemRouter.read(self.session_id, 'interfaces') or ""

        phase_status = {
            "current_phase": "L3_GENERATE",
            "phase_status": "代码生成完成，等待审核"
        }

        # 读取生成的代码
        generated_code = ""
        for py_file in py_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    generated_code += f"\n### {py_file.name}\n```python\n{f.read()}\n```\n"
            except Exception:
                pass

        context_str = f"生成文件数: {len(py_files)}\n生成代码长度: {len(generated_code)} 字符\n"

        ai_result = self._call_ai_reviewer_for_code(
            context_str,
            phase_status,
            requirement,
            interfaces,
            generated_code,
            self.context.requirement
        )

        # 解析 AI 审核结果
        if ai_result.strip() == "通过":
            return ReviewResult(
                passed=True,
                phase=PipelinePhase.L3_GENERATE,
                reviewer_type="ai",
                message="AI 审核通过"
            )
        else:
            reason = ai_result
            if "打回:" in ai_result:
                reason = ai_result.split("打回:")[1].strip()
            return ReviewResult(
                passed=False,
                phase=PipelinePhase.L3_GENERATE,
                reviewer_type="ai",
                message="AI 审核打回",
                reason=reason
            )

    def _call_ai_reviewer(
        self,
        context_str: str,
        phase_status: dict,
        current_output: str = "",
        requirement: str = ""
    ) -> str:
        """调用 AI 审核员（通用）"""
        from memory import MemRouter

        # 优先从 context 读取，没有再从记忆区读取
        requirement = requirement or self.context.requirement or MemRouter.read(self.session_id, 'requirement') or "（无需求文档）"
        interfaces = self.context.interfaces or MemRouter.read(self.session_id, 'interfaces') or "（无接口文档）"

        # 构建当前阶段输出
        current_phase_output = current_output or self.context.requirement or self.context.interfaces or ""

        prompt = f"""## Session 信息
- Session ID: {self.session_id}
- 当前阶段: {phase_status['current_phase']}
- 阶段状态: {phase_status['phase_status']}

## 上下文状态
{context_str}

## 当前阶段产出
{current_phase_output}

## 需求文档
{requirement}

## 接口文档
{interfaces}

请审核当前阶段的输出是否符合要求。输出格式：
- `通过` - 所有检查项都通过
- `打回: [原因]` - 有问题，说明原因"""

        try:
            from pipeline.AiBase import AiBase
            ai_base = AiBase()
            system_prompt = """你是 YGA 的阶段审核员。
你需要先识别当前阶段背景，再审核当前阶段产物。

阶段背景：
- L1_UNDERSTAND：审核需求整理是否忠于用户输入，不遗漏、不脑补、不设计接口或模块。
- L2_INTERFACE：审核接口契约是否覆盖已确认需求，不越权新增功能，不替代 PMC 模块拆分。
- 其他阶段：只按当前阶段输入和产物用途审核，不套用代码审核标准。

模块背景：
- 先识别当前产物属于哪个模块或子模块；如果只是阶段产物，就按阶段模块职责审核。
- 不要求一个模块承担上层功能域的全部职责，也不允许它越界实现兄弟模块职责。

输出只允许：
- 通过
- 打回: [原因]"""
            result = ai_base.call(prompt, system=system_prompt, temperature=0.3)
            return result
        except Exception as e:
            return f"AI 审核失败: {e}"

    def _call_ai_reviewer_for_code(
        self,
        context_str: str,
        phase_status: dict,
        requirement: str,
        interfaces: str,
        generated_code: str,
        current_output: str = ""
    ) -> str:
        """调用 AI 审核员（针对代码）"""
        prompt = f"""## Session 信息
- Session ID: {self.session_id}
- 当前阶段: {phase_status['current_phase']}
- 阶段状态: {phase_status['phase_status']}

## 上下文状态
{context_str}

## 当前阶段产出
{current_output}

## 需求文档
{requirement}

## 接口文档
{interfaces}

## 生成的代码
{generated_code}

请根据需求文档和接口文档，审核生成的代码是否符合要求。

## 审核要求

1. **需求匹配**: 代码是否实现了需求文档中的功能
2. **接口一致**: API 接口是否按接口文档实现
3. **代码质量**: 是否有明显bug、安全问题

输出格式：
- `通过` - 所有检查项都通过
- `打回: [原因]` - 有问题，说明原因"""

        try:
            from pipeline.AiBase import AiBase
            ai_base = AiBase()
            system_prompt = """你是 YGA 的 L3 代码审核员。
当前区域是代码开发区，输入是已审核的接口契约和当前批次范围。
当前模块是本批次进入代码开发区的具体模块或子模块。
你只审核生成代码是否实现该模块契约、是否只实现当前范围、是否具备基础日志和错误处理。
不要重新拆模块，不要新增接口总账之外的公共接口。

输出只允许：
- 通过
- 打回: [原因]"""
            result = ai_base.call(prompt, system=system_prompt, temperature=0.3)
            return result
        except Exception as e:
            return f"AI 审核失败: {e}"

    # 重试配置
    MAX_RETRIES = 3

    def run_simple_pipeline(self, user_input: str) -> PipelineResult:
        """
        执行 Simple 链路完整流程（含审核 + 重试）

        流程：L1 → L1审核 → L2 → L2审核 → L3 → L3审核 → 本地测试
        重试机制：审核打回 → 附上原因重新生成 → 再次审核（最多3次）

        Args:
            user_input: 用户原始需求

        Returns:
            PipelineResult
        """
        results = []
        reviews = []  # 记录审核结果
        retry_count = {"l1": 0, "l2": 0, "l3": 0}

        # ========== L1 需求理解 + 审核 ==========
        while retry_count["l1"] < self.MAX_RETRIES:
            result_l1 = self.run_l1_understand(user_input)
            results.append(result_l1)
            if not result_l1.success:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L1_UNDERSTAND,
                    error=f"L1 失败: {result_l1.error}",
                    message="流水线在 L1 阶段失败"
                )

            # L1 审核
            review_l1 = self._review_l1_result()
            reviews.append(review_l1)
            if review_l1.passed:
                break

            retry_count["l1"] += 1
            if retry_count["l1"] >= self.MAX_RETRIES:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L1_UNDERSTAND,
                    error=f"L1 审核打回（已达最大重试次数 {self.MAX_RETRIES}）: {review_l1.reason}",
                    message=f"L1 审核未通过: {review_l1.reason}"
                )

            # 打回：带着原因重新生成
            print(f"[L1] 审核打回，重新生成（第 {retry_count['l1']} 次）: {review_l1.reason}")
            user_input = self._reconstruct_with_feedback(user_input, review_l1.reason, "L1 需求理解")

        # ========== L2 接口文档 + 审核 ==========
        while retry_count["l2"] < self.MAX_RETRIES:
            result_l2 = self.run_l2_interface()
            results.append(result_l2)
            if not result_l2.success:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L2_INTERFACE,
                    error=f"L2 失败: {result_l2.error}",
                    message="流水线在 L2 阶段失败"
                )

            # L2 审核
            review_l2 = self._review_l2_result()
            reviews.append(review_l2)
            if review_l2.passed:
                break

            retry_count["l2"] += 1
            if retry_count["l2"] >= self.MAX_RETRIES:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L2_INTERFACE,
                    error=f"L2 审核打回（已达最大重试次数 {self.MAX_RETRIES}）: {review_l2.reason}",
                    message=f"L2 审核未通过: {review_l2.reason}"
                )

            # 打回：带着原因重新生成
            print(f"[L2] 审核打回，重新生成（第 {retry_count['l2']} 次）: {review_l2.reason}")
            self.context.interfaces = self._reconstruct_with_feedback(
                self.context.interfaces,
                review_l2.reason,
                "L2 接口文档",
                context=self.context.requirement  # 传入需求文档作为上下文
            )

        # ========== L3 代码生成 + 审核 ==========
        while retry_count["l3"] < self.MAX_RETRIES:
            result_l3 = self.run_l3_generate()
            results.append(result_l3)
            if not result_l3.success:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L3_GENERATE,
                    error=f"L3 失败: {result_l3.error}",
                    message="流水线在 L3 阶段失败"
                )

            # L3 审核
            review_l3 = self._review_l3_result()
            reviews.append(review_l3)
            if review_l3.passed:
                break

            retry_count["l3"] += 1
            if retry_count["l3"] >= self.MAX_RETRIES:
                return PipelineResult(
                    success=False,
                    phase=PipelinePhase.L3_GENERATE,
                    error=f"L3 审核打回（已达最大重试次数 {self.MAX_RETRIES}）: {review_l3.reason}",
                    message=f"L3 审核未通过: {review_l3.reason}"
                )

            # 打回：带着原因重新生成
            print(f"[L3] 审核打回，重新生成（第 {retry_count['l3']} 次）: {review_l3.reason}")
            self.context.interfaces = self._reconstruct_with_feedback(
                self.context.interfaces,
                review_l3.reason,
                "L3 代码生成"
            )
            # 清除旧文件，重新生成
            self._clear_output_files()

        # ========== 本地测试 ==========
        result_test = self.run_local_test()
        results.append(result_test)

        # 更新索引
        from memory import update_session, add_test
        files = result_l3.files if result_l3.files else []

        if result_test.success:
            self.context.current_phase = PipelinePhase.COMPLETE

            # 成功：更新会话索引 + 添加测试记录
            update_session(
                session_id=self.session_id,
                requirement=self.context.requirement[:50] if self.context.requirement else "simple",
                modules=[],
                files=files,
                status="completed"
            )
            add_test(
                test_case=f"流水线执行-{self.session_id}",
                result="✅ 成功",
                files=f"{len(files)} 个文件"
            )

            return PipelineResult(
                success=True,
                phase=PipelinePhase.COMPLETE,
                files=files,
                test_results=result_test.test_results,
                message="流水线执行完成，所有测试通过"
            )
        else:
            # 失败：更新会话索引
            update_session(
                session_id=self.session_id,
                requirement=self.context.requirement[:50] if self.context.requirement else "simple",
                modules=[],
                files=files,
                status="failed"
            )

            return PipelineResult(
                success=False,
                phase=PipelinePhase.LOCAL_TEST,
                files=files,
                test_results=result_test.test_results,
                error=result_test.error,
                message="流水线执行完成，但测试未通过"
            )

    def _reconstruct_with_feedback(self, original: str, reason: str, stage: str, context: str = "") -> str:
        """
        带着打回原因重新构造输入

        Args:
            original: 原始输入
            reason: 审核打回原因
            stage: 当前阶段名称
            context: 附加上下文信息

        Returns:
            带反馈的新输入
        """
        context_section = f"\n\n**参考上下文**:\n{context}\n" if context else ""
        return f"""## {stage} 审核打回反馈
请根据以下审核意见重新生成：

**打回原因**: {reason}
{context_section}
**原始内容**:
{original}

**要求**:
1. 针对打回原因进行修改
2. 保持原有正确的内容不变
3. 重新输出完整的 {stage} 内容
"""

    def _clear_output_files(self):
        """清除输出目录中的旧文件"""
        output_dir = self.get_output_dir()
        if output_dir.exists():
            for py_file in output_dir.glob("*.py"):
                try:
                    py_file.unlink()
                except Exception:
                    pass


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发完成
# contract: 12_接手文档.md
# next: 端到端测试
# changelog: 添加审核打回重试机制，每个AI步骤最多重试3次
# </YGA_END_ANCHOR>
