# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pipeline
file: pipeline/PipelineRouter.py
responsibility: 流水线统一入口（Simple 主链转发 SimpleOrchestrator）
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from pathlib import Path
from typing import Dict, Optional

from memory import MemRouter
from pipeline.PipelineDrain import PipelineDrain
from pipeline.PipelineRunner import PipelineRunner, PipelinePhase
from pipeline.SimpleOrchestrator import SimpleOrchestrator


class PipelineRouter:
    """
    流水线统一入口

    产品主路径：SimpleOrchestrator（Memory 已确认需求 → PMC → L2 → L3 → Gate → Review）
    过渡路径：run_legacy_simple（需 user_input，仅兼容旧演示）
    """

    @staticmethod
    def run(
        session_id: str,
        user_input: str = "",
        require_ai_review: bool = True,
        skip_delivery_ai_review: bool = False,
    ) -> Dict:
        """
        执行 Simple 产品主链。

        Args:
            session_id: Session ID
            user_input: 已废弃为主路径输入；仅当 requirement 缺失且 allow_legacy 时作兜底
            require_ai_review: L2 是否走 AiArtifactReviewer
            skip_delivery_ai_review: 测试用，跳过交付 AI 终审
        """
        requirement = MemRouter.read(session_id, "requirement")
        context = MemRouter.read(session_id, "context") or {}

        if context.get("requirement_ready") and requirement:
            result = SimpleOrchestrator.run(
                session_id,
                require_ai_review=require_ai_review,
                skip_delivery_ai_review=skip_delivery_ai_review,
            )
            return {
                "success": result.success,
                "session_id": session_id,
                "run_id": result.run_id,
                "phases": result.phases,
                "files": result.files,
                "message": result.message,
                "error": result.error,
                "delivery": result.delivery,
                "orchestrator": "SimpleOrchestrator",
            }

        if user_input:
            return PipelineRouter.run_legacy_simple(session_id, user_input)

        return {
            "success": False,
            "session_id": session_id,
            "run_id": "",
            "message": "请先确认需求（requirement_ready）并写入 logs/requirement.md，或使用过渡接口 run_legacy_simple",
        }

    @staticmethod
    def run_legacy_simple(session_id: str, user_input: str) -> Dict:
        """过渡路径：L1 流水线（非 P0 产品口径）。"""
        result = {
            "success": False,
            "session_id": session_id,
            "run_id": "",
            "phases": {},
            "message": "",
            "orchestrator": "PipelineRunner.run_simple_pipeline",
        }
        run_id = ""

        def finish_run(success: bool, phase: str, message: str, files=None, test_results=None):
            nonlocal run_id
            if not run_id:
                return
            PipelineDrain.complete_run(
                session_id,
                run_id,
                success=success,
                phase=phase,
                message=message,
                files=files or [],
                test_results=test_results or {},
            )
            run_id = ""

        try:
            can_start, msg = PipelineDrain.can_start_pipeline(session_id)
            if not can_start:
                result["message"] = f"Pipeline 未启动: {msg}"
                return result

            run_id = PipelineDrain.begin_run(
                session_id,
                run_type="pipeline.legacy_simple",
                source="PipelineRouter.run_legacy_simple",
            )
            result["run_id"] = run_id

            pipeline = PipelineRunner(session_id)
            pipeline_result = pipeline.run_simple_pipeline(user_input)

            result["success"] = pipeline_result.success
            result["phases"] = {
                "l1": pipeline.context.requirement[:200] if pipeline.context.requirement else "",
                "l2": pipeline.context.interfaces[:200] if pipeline.context.interfaces else "",
                "files": pipeline_result.files,
                "test_results": pipeline_result.test_results,
            }
            result["message"] = pipeline_result.message
            finish_run(
                pipeline_result.success,
                pipeline_result.phase.value if isinstance(pipeline_result.phase, PipelinePhase) else str(pipeline_result.phase),
                pipeline_result.message,
                files=pipeline_result.files,
                test_results=pipeline_result.test_results,
            )
            return result

        except PermissionError as e:
            result["message"] = f"Pipeline 未启动: {str(e)}"
            return result
        except Exception as e:
            result["message"] = f"流水线执行失败: {str(e)}"
            try:
                finish_run(False, "exception", result["message"])
            except Exception:
                pass
            return result

    @staticmethod
    def run_with_interfaces(session_id: str, interfaces: str) -> Dict:
        """直接 L3 + LocalTester（跳过 L1/L2/PMC），开发调试用。"""
        result = {
            "success": False,
            "session_id": session_id,
            "run_id": "",
            "files": [],
            "message": "",
        }
        run_id = ""

        def finish_run(success: bool, phase: str, message: str, files=None, test_results=None):
            nonlocal run_id
            if not run_id:
                return
            PipelineDrain.complete_run(
                session_id,
                run_id,
                success=success,
                phase=phase,
                message=message,
                files=files or [],
                test_results=test_results or {},
            )
            run_id = ""

        try:
            run_id = PipelineDrain.begin_run(
                session_id,
                run_type="pipeline.run_with_interfaces",
                source="PipelineRouter.run_with_interfaces",
            )
            result["run_id"] = run_id
            pipeline = PipelineRunner(session_id)

            pipeline.context.requirement = "用户需求（从接口文档推断）"
            pipeline.context.interfaces = interfaces

            l3_result = pipeline.run_l3_generate()
            result["success"] = l3_result.success
            result["files"] = l3_result.files
            result["message"] = l3_result.message

            if l3_result.success:
                test_result = pipeline.run_local_test()
                result["test_results"] = test_result.test_results
                result["success"] = test_result.success
                result["message"] = test_result.message

            finish_run(
                result["success"],
                PipelinePhase.LOCAL_TEST.value if l3_result.success else l3_result.phase.value,
                result["message"],
                files=result["files"],
                test_results=result.get("test_results", {}),
            )

            return result

        except PermissionError as e:
            result["message"] = f"Pipeline 未启动: {str(e)}"
            return result
        except Exception as e:
            result["message"] = f"代码生成失败: {str(e)}"
            try:
                finish_run(False, "exception", result["message"])
            except Exception:
                pass
            return result


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: Simple 主链转发 SimpleOrchestrator
# contract: 12_接手文档.md
# next: test_simple_e2e_offline
# </YGA_END_ANCHOR>