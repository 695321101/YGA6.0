# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pipeline
file: pipeline/SimpleOrchestrator.py
responsibility: Simple 主链编排（Memory → PMC → L2 → L3 → LocalGate → Review → 交付）
exports: SimpleOrchestrator, SimpleOrchestratorResult
authority: .claude/planning/README.md
</YGA_FILE_ANCHOR>
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

from pipeline.PipelineDrain import PipelineDrain
from pipeline.PipelineRunner import PipelineRunner
from pipeline.LocalGate import LocalGate
from pmc.PmcPlanner import PipelineType


@dataclass
class SimpleOrchestratorResult:
    """Simple 主链执行结果。"""
    success: bool
    session_id: str
    message: str = ""
    error: str = ""
    run_id: str = ""
    files: List[str] = field(default_factory=list)
    phases: Dict = field(default_factory=dict)
    delivery: Dict = field(default_factory=dict)


class SimpleOrchestrator:
    """
    Simple 产品主链编排器。

    不重复 L1 重写需求；以 logs/requirement.md（requirement_ready）为唯一需求真相。
    """

    PROJECT_ROOT = Path(__file__).parent.parent
    PROMPT_DIR = PROJECT_ROOT / "prompts"
    OUTPUT_DIR = PROJECT_ROOT / "output"
    DEFAULT_MODULE = "app"
    MAX_L3_GATE_RETRIES = 3

    @classmethod
    def run(
        cls,
        session_id: str,
        require_ai_review: bool = True,
        skip_delivery_ai_review: bool = False,
    ) -> SimpleOrchestratorResult:
        """执行 Simple 闭环。"""
        from memory import MemRouter
        from pmc import PmcRouter

        run_id = ""
        phases: Dict = {}

        def fail(phase: str, message: str, error: str = "") -> SimpleOrchestratorResult:
            if run_id:
                PipelineDrain.complete_run(
                    session_id,
                    run_id,
                    success=False,
                    phase=phase,
                    message=message,
                )
            return SimpleOrchestratorResult(
                success=False,
                session_id=session_id,
                message=message,
                error=error or message,
                run_id=run_id,
                phases=phases,
            )

        # --- 准入 ---
        context = MemRouter.read(session_id, "context") or {}
        if not context.get("requirement_ready"):
            return fail("admission", "需求尚未确认（requirement_ready=false）")

        requirement = MemRouter.read(session_id, "requirement")
        if not requirement or not requirement.strip():
            return fail("admission", "缺少 logs/requirement.md")

        can_start, drain_msg = PipelineDrain.can_start_pipeline(session_id)
        if not can_start:
            return fail("admission", f"Pipeline 未启动: {drain_msg}")

        try:
            run_id = PipelineDrain.begin_run(
                session_id,
                run_type="simple.orchestrator",
                source="SimpleOrchestrator.run",
            )
        except PermissionError as exc:
            return SimpleOrchestratorResult(
                success=False,
                session_id=session_id,
                message=str(exc),
                error=str(exc),
            )

        try:
            # --- PMC（phase_2，经 PmcRouter）---
            decision, pmc_review = PmcRouter.execute(session_id, require_ai_review=False)
            phases["pmc"] = {
                "pipeline_type": decision.pipeline_type.value,
                "passed": pmc_review.passed,
            }
            if not pmc_review.passed:
                return fail(
                    "pmc",
                    "PMC 审核未通过",
                    "; ".join(pmc_review.issues or []),
                )
            if decision.pipeline_type != PipelineType.SIMPLE:
                return fail(
                    "pmc",
                    f"SimpleOrchestrator 仅支持 simple 链路，当前为 {decision.pipeline_type.value}",
                )

            module_slug = cls._resolve_module_slug(decision)
            code_dir = cls._module_output_dir(session_id, module_slug)

            # --- L2（不跑 L1）---
            runner = PipelineRunner(session_id)
            runner.context.requirement = requirement
            l2_result = cls._run_l2_with_review(
                runner,
                requirement,
                require_ai_review=require_ai_review,
            )
            phases["l2"] = {"success": l2_result["success"], "message": l2_result.get("message", "")}
            if not l2_result["success"]:
                return fail("l2", l2_result.get("message", "L2 失败"), l2_result.get("error", ""))

            interfaces = l2_result["interfaces"]
            MemRouter.write(session_id, "interfaces", interfaces, source="L2")
            MemRouter.write(session_id, "interfaces_confirm", "", source="System")
            runner.context.interfaces = interfaces

            # --- L3 + LocalGate（打回重生成，最多 MAX_L3_GATE_RETRIES 次）---
            can_l3, l3_gate_msg = MemRouter.check_phase_gate(session_id, "phase_4")
            if not can_l3:
                return fail("l3_admission", l3_gate_msg)

            gate = LocalGate()
            contract = LocalGate.parse_contract_from_interfaces(interfaces)
            l3_result = None
            gate_results = None
            gate_feedback = ""

            for attempt in range(cls.MAX_L3_GATE_RETRIES):
                l3_result = cls._run_l3(
                    runner,
                    interfaces,
                    code_dir,
                    gate_feedback=gate_feedback,
                )
                if not l3_result["success"]:
                    return fail("l3", l3_result.get("message", "L3 失败"), l3_result.get("error", ""))

                gate_results = gate.run(code_dir, contract=contract)
                cls._save_test_context(session_id, gate_results, code_dir)
                if gate_results.get("all_passed"):
                    phases["l3"] = {
                        "success": True,
                        "files": l3_result.get("files", []),
                        "attempts": attempt + 1,
                    }
                    phases["local_gate"] = {"all_passed": True, "attempts": attempt + 1}
                    break

                gate_feedback = cls._summarize_gate_failures(gate_results)
                phases["local_gate_retry"] = phases.get("local_gate_retry", []) + [
                    {"attempt": attempt + 1, "feedback": gate_feedback[:500]},
                ]
                cls._clear_py_files(code_dir)
            else:
                phases["l3"] = {"success": True, "files": l3_result.get("files", []) if l3_result else []}
                phases["local_gate"] = {"all_passed": False}
                return fail(
                    "local_gate",
                    f"LocalGate 未通过（已重试 {cls.MAX_L3_GATE_RETRIES} 次）",
                    str(gate_results),
                )

            MemRouter.complete_phase(session_id, "phase_3")
            MemRouter.complete_phase(session_id, "phase_4")

            # --- Review ---
            review_outcome = cls._run_delivery_review(
                session_id,
                code_dir,
                gate_results,
                skip_ai=skip_delivery_ai_review,
            )
            phases["review"] = review_outcome
            if not review_outcome.get("passed"):
                return fail("review", review_outcome.get("message", "Review 未通过"))

            MemRouter.complete_phase(session_id, "phase_5")
            MemRouter.complete_phase(session_id, "phase_6")

            delivery = cls._write_delivery(session_id, module_slug, code_dir, l3_result.get("files", []))
            phases["delivery"] = delivery

            PipelineDrain.complete_run(
                session_id,
                run_id,
                success=True,
                phase="phase_6",
                message="Simple 闭环完成",
                files=l3_result.get("files", []),
                test_results=gate_results,
            )

            return SimpleOrchestratorResult(
                success=True,
                session_id=session_id,
                message="Simple 闭环完成",
                run_id=run_id,
                files=l3_result.get("files", []),
                phases=phases,
                delivery=delivery,
            )

        except Exception as exc:
            return fail("exception", f"Simple 编排异常: {exc}", str(exc))

    @classmethod
    def _resolve_module_slug(cls, decision) -> str:
        for task in decision.tasks:
            mod = (task.module or "").strip()
            if mod and mod not in ("test", "database"):
                return mod.replace("/", "_").replace("\\", "_")
        return cls.DEFAULT_MODULE

    @classmethod
    def _module_output_dir(cls, session_id: str, module_slug: str) -> Path:
        path = cls.OUTPUT_DIR / session_id / "modules" / module_slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _load_prompt(cls, name: str) -> str:
        prompt_path = cls.PROMPT_DIR / f"{name}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt 不存在: {prompt_path}")
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'# -\*- coding: utf-8 -\*-\n', "", content)
        content = re.sub(r'"""[\s\S]*?"""', "", content)
        return content.strip()

    @classmethod
    def _run_l2_with_review(cls, runner: PipelineRunner, requirement: str, require_ai_review: bool) -> Dict:
        prompt = cls._load_prompt("l2_interface")
        interfaces = runner.ai_l2.generate_interface(prompt, requirement)

        if require_ai_review:
            from review import AiArtifactReviewer

            review = AiArtifactReviewer.review_l2_interface(requirement, interfaces)
            if not review.passed:
                return {
                    "success": False,
                    "message": f"L2 AI 审核打回: {review.reason}",
                    "error": review.reason,
                }

        if not cls._local_l2_shape_ok(interfaces):
            return {
                "success": False,
                "message": "L2 本地结构检查未通过",
                "error": "接口文档缺少接口/输入/输出等关键章节",
            }

        return {"success": True, "interfaces": interfaces, "message": "L2 完成"}

    @staticmethod
    def _local_l2_shape_ok(interfaces: str) -> bool:
        text = interfaces or ""
        has_interface = "接口" in text
        has_in = "输入" in text or "请求" in text
        has_out = "输出" in text or "响应" in text
        return has_interface and has_in and has_out

    @classmethod
    def _run_l3(
        cls,
        runner: PipelineRunner,
        interfaces: str,
        code_dir: Path,
        gate_feedback: str = "",
    ) -> Dict:
        prompt = cls._load_prompt("l3_generate")
        if gate_feedback:
            full = f"""{prompt}

## LocalGate 打回（请按 L3 提示词与规划 README 生成标准修正）
{gate_feedback}

## 接口契约
{interfaces}

请重新输出完整代码块（```python filename:...）。"""
            raw = runner.ai_l3.ai.call(full, temperature=0.3)
        else:
            raw = runner.ai_l3.generate_code(prompt, interfaces)
        runner.context.generated_code = raw
        files = cls._save_code_files(raw, code_dir)
        if not files:
            return {"success": False, "message": "L3 未生成任何文件", "error": "no files"}
        return {"success": True, "files": files, "message": f"生成 {len(files)} 个文件"}

    @staticmethod
    def _summarize_gate_failures(gate_results: Dict) -> str:
        lines = []
        for key, val in gate_results.items():
            if key == "all_passed" or not isinstance(val, dict):
                continue
            if not val.get("passed"):
                lines.append(f"- {val.get('name', key)}: {val.get('details', '')}")
        return "\n".join(lines) or "LocalGate 未通过。"

    @staticmethod
    def _clear_py_files(code_dir: Path):
        for py_file in Path(code_dir).glob("*.py"):
            try:
                py_file.unlink()
            except OSError:
                pass

    @classmethod
    def _save_code_files(cls, code_content: str, output_dir: Path) -> List[str]:
        saved = []
        pattern = r"```(?:\w+)?\s*(?:filename:(\S+))?\n([\s\S]*?)```"
        files = []
        for match in re.finditer(pattern, code_content):
            filename = match.group(1) if match.group(1) else "main.py"
            code = match.group(2).strip()
            if not match.group(1):
                file_match = re.search(r'["\'](\w+\.py)["\']', code)
                if file_match:
                    filename = file_match.group(1)
            files.append((filename, code))

        if not files and code_content.strip():
            if "def " in code_content or "class " in code_content or "import " in code_content:
                files.append(("main.py", code_content.strip()))

        for filename, content in files:
            file_path = output_dir / Path(filename).name
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            saved.append(str(file_path))
        return saved

    @classmethod
    def _save_test_context(cls, session_id: str, gate_results: Dict, code_dir: Path):
        from memory import MemRouter

        payload = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "source": "LocalGate",
            "code_dir": str(code_dir.relative_to(cls.PROJECT_ROOT)).replace("\\", "/"),
            "results": gate_results,
            "all_passed": gate_results.get("all_passed", False),
        }
        MemRouter.update_module_context(session_id, "test", payload)

    @classmethod
    def _run_delivery_review(
        cls,
        session_id: str,
        code_dir: Path,
        gate_results: Dict,
        skip_ai: bool = False,
    ) -> Dict:
        from memory import MemRouter
        from review.Reviewer import LocalReviewer

        py_files = [str(p) for p in sorted(code_dir.glob("*.py"))]
        local_ok, local_errors = LocalReviewer.review_module("generated", py_files)
        if not local_ok:
            cls._save_review_context(session_id, passed=False, message="本地审核失败", detail=local_errors)
            return {"passed": False, "message": "本地审核失败", "errors": local_errors}

        if skip_ai:
            cls._save_review_context(session_id, passed=True, message="跳过 AI 终审（测试模式）")
            return {"passed": True, "message": "跳过 AI 终审（测试模式）", "verdict": "通过"}

        from review.Reviewer import Reviewer

        ai_result = Reviewer.review_session_delivery(
            session_id,
            code_dir=code_dir,
            gate_results=gate_results,
        )
        passed = ai_result.strip().startswith("通过")
        cls._save_review_context(
            session_id,
            passed=passed,
            message=ai_result,
        )
        return {"passed": passed, "message": ai_result, "verdict": ai_result}

    @classmethod
    def _save_review_context(cls, session_id: str, passed: bool, message: str, detail=None):
        from memory import MemRouter

        payload = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "passed": passed,
            "message": message,
            "detail": detail or [],
        }
        MemRouter.update_module_context(session_id, "review", payload)

    @classmethod
    def _write_delivery(cls, session_id: str, module_slug: str, code_dir: Path, files: List[str]) -> Dict:
        from memory import MemRouter

        entry = "main.py"
        for f in files:
            if f.endswith("main.py"):
                entry = Path(f).name
                break

        rel_dir = code_dir.relative_to(cls.OUTPUT_DIR / session_id)
        delivery = {
            "session_id": session_id,
            "completed_at": datetime.now().isoformat(),
            "module": module_slug,
            "entrypoint": f"{rel_dir.as_posix()}/{entry}",
            "start_hint": f"cd output/{session_id}/{rel_dir.as_posix()} && python {entry}",
            "files": [Path(f).name for f in files],
        }
        MemRouter.write(
            session_id,
            "progress",
            f"# 交付\n\n- 启动: `{delivery['start_hint']}`\n",
            source="System",
        )
        return delivery


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 初版 Simple 主链编排
# contract: README.md §13
# next: PipelineRouter 转发
# </YGA_END_ANCHOR>