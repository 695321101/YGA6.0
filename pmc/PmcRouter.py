# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pmc
file: pmc/PmcRouter.py
responsibility: PMC 统一入口（规划 + 审核 + 记忆区交互）
exports: PmcRouter
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
import yaml
from datetime import datetime
from typing import Tuple, Optional
from pathlib import Path

from pmc.PmcPlanner import PmcPlanner, PmcDecision, PipelineType, Task
from pmc.PmcReviewer import PmcReviewer, PmcReviewResult
from pmc.PmcBlueprint import PmcBlueprint
from pmc.PmcLayeredSplitter import PmcLayeredSplitter, PmcLayeredSplitResult


class PmcRouter:
    """
    PMC 统一入口 - 所有 PMC 操作通过此入口

    功能：
    1. PMC 规划：读取需求，生成决策
    2. PMC 审核：审核决策结果
    3. 写入记忆区：保存决策到 context/pmc/
    4. 阶段门禁：检查 requirement_ready 状态
    """

    @staticmethod
    def _ensure_pmc_admission(session_id: str):
        """PMC 规划准入：需求已确认，且当前处于 phase_2（L2 之前）。"""
        from memory import MemRouter

        context = MemRouter.read(session_id, "context") or {}
        if not context.get("requirement_ready"):
            raise PermissionError("需求尚未确认，无法执行 PMC")
        phase = MemRouter.get_phase_status(session_id).get("current_phase", "phase_1")
        if phase != "phase_2":
            raise PermissionError(f"PMC 规划应在 phase_2 执行，当前为 {phase}")

    @staticmethod
    def plan(session_id: str, ai_blueprint: Optional[dict] = None) -> PmcDecision:
        """
        执行 PMC 规划

        从记忆区读取需求文档，执行规划，生成决策

        Args:
            session_id: Session ID

        Returns:
            PMC 决策结果
        """
        from memory import MemRouter

        # 1. 检查阶段门禁：需求已确认即可规划（仍在 L2 之前，不要求 interfaces_ready）
        PmcRouter._ensure_pmc_admission(session_id)

        # 2. 读取需求文档
        requirement = MemRouter.read(session_id, 'requirement')
        if not requirement:
            raise ValueError(f"Session {session_id} 没有需求文档")

        # 3. 读取接口文档（可选）
        interfaces = MemRouter.read(session_id, 'interfaces')

        # 4. 执行规划；业务模块拆分只能来自 AI 明确给出的蓝图
        decision = PmcPlanner.plan(session_id, requirement, interfaces, ai_blueprint=ai_blueprint)

        return decision

    @staticmethod
    def review(
        decision: PmcDecision,
        interfaces_content: str = "",
        requirement_content: str = "",
        require_ai_review: bool = False
    ) -> PmcReviewResult:
        """
        审核 PMC 决策

        Args:
            decision: PMC 决策结果
            interfaces_content: 接口文档内容（用于验证）

        Returns:
            审核结果
        """
        return PmcReviewer.review_pmc_decision(
            decision,
            interfaces_content,
            requirement_content=requirement_content,
            require_ai_review=require_ai_review,
        )

    @staticmethod
    def execute(
        session_id: str,
        ai_blueprint: Optional[dict] = None,
        require_ai_review: bool = False
    ) -> Tuple[PmcDecision, PmcReviewResult]:
        """
        执行 PMC 完整流程（规划 + 审核）

        Args:
            session_id: Session ID

        Returns:
            (PMC 决策, 审核结果)
        """
        # 1. 规划
        decision = PmcRouter.plan(session_id, ai_blueprint=ai_blueprint)

        # 2. 审核
        from memory import MemRouter
        interfaces = MemRouter.read(session_id, 'interfaces')
        requirement = MemRouter.read(session_id, 'requirement') or ""
        review_result = PmcRouter.review(
            decision,
            interfaces or "",
            requirement_content=requirement,
            require_ai_review=require_ai_review,
        )

        # 3. 写入记忆区（只有审核通过才写入）
        if review_result.passed:
            PmcRouter._save_decision(decision)
            MemRouter.update_context(session_id, pmc_ready=True)
            # 阶段仍停留在 phase_2，直到 L2 确认 interfaces_ready 后由 SimpleOrchestrator 推进
        else:
            # 打印审核问题
            print("PMC 审核未通过：")
            for issue in review_result.issues:
                print(f"  - {issue}")

        return decision, review_result

    @staticmethod
    def execute_layered_split(
        session_id: str,
        require_ai_review: bool = True
    ) -> Tuple[PmcDecision, PmcReviewResult, PmcLayeredSplitResult]:
        """
        执行 PMC 分层拆分流程。

        该入口先让 AI 按层拆分并逐层通过 AI 审核，再把最终蓝图交给
        PmcPlanner/PmcReviewer 做已有的决策、确定性验收、落盘和阶段推进。
        """
        from memory import MemRouter

        PmcRouter._ensure_pmc_admission(session_id)

        requirement = MemRouter.read(session_id, 'requirement')
        if not requirement:
            raise ValueError(f"Session {session_id} 没有需求文档")

        split_result = PmcLayeredSplitter.split(
            session_id,
            requirement,
            require_ai_review=require_ai_review,
        )
        decision, review_result = PmcRouter.execute(
            session_id,
            ai_blueprint=split_result.blueprint,
            require_ai_review=require_ai_review,
        )
        if review_result.passed:
            PmcRouter._save_layered_split_context(session_id, split_result)
        return decision, review_result, split_result

    @staticmethod
    def _save_decision(decision: PmcDecision):
        """保存决策到记忆区"""
        from memory import MemRouter, update_session

        blueprint_artifacts = {}
        if decision.blueprint:
            blueprint_artifacts = PmcBlueprint.write_artifacts(decision.session_id, decision.blueprint)

        # 构建 PMC 上下文数据
        pmc_data = {
            "session_id": decision.session_id,
            "created_at": datetime.now().isoformat(),
            "data": {
                "decision": {
                    "pipeline_type": decision.pipeline_type.value,
                    "interface_count": decision.interface_count,
                    "module_count": decision.module_count,
                    "reasoning": decision.reasoning
                },
                "tasks": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "module": t.module,
                        "priority": t.priority,
                        "description": t.description,
                        "dependencies": t.dependencies
                    }
                    for t in decision.tasks
                ],
                "blueprint": {
                    "module_count": len(decision.blueprint.get("module_cards", [])) if decision.blueprint else 0,
                    "interface_count": len(decision.blueprint.get("interface_registry", {}).get("public_interfaces", [])) if decision.blueprint else 0,
                    "active_batch": decision.blueprint.get("batch_plan", {}).get("active_batch", "") if decision.blueprint else "",
                    "requires_ai_review": bool(decision.blueprint),
                },
                "artifacts": blueprint_artifacts
            }
        }

        # 写入模块上下文
        MemRouter.update_module_context(decision.session_id, "pmc", pmc_data)

        # 同时写入 YAML 文件（兼容旧接口）
        session_dir = Path(__file__).parent.parent / "memory" / "sessions" / decision.session_id
        pmc_context_file = session_dir / "context" / "pmc" / "pmc_context.yaml"

        # 确保目录存在
        pmc_context_file.parent.mkdir(parents=True, exist_ok=True)

        with open(pmc_context_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(pmc_data, f, allow_unicode=True, default_flow_style=False)

        # 更新会话索引
        modules = list(set([t.module for t in decision.tasks if t.module]))
        update_session(
            session_id=decision.session_id,
            requirement=f"PMC规划: {decision.pipeline_type.value}",
            modules=modules,
            files=[],
            status="pmc_completed",
            chain_type=decision.pipeline_type.value
        )

    @staticmethod
    def _save_layered_split_context(session_id: str, split_result: PmcLayeredSplitResult):
        """把分层拆分摘要补写到 PMC 上下文。"""
        from memory import MemRouter

        summary = {
            "enabled": True,
            "project_domain_count": len(split_result.project_domains.get("domains", [])),
            "domain_module_count": sum(
                len(item.get("modules", []))
                for item in split_result.domain_modules.get("domains", [])
            ),
            "review_count": len(split_result.reviews),
            "artifacts": split_result.artifacts,
        }
        MemRouter.update_module_context(session_id, "pmc", {"layered_split": summary})

    @staticmethod
    def get_decision(session_id: str) -> Optional[PmcDecision]:
        """
        从记忆区读取 PMC 决策

        Args:
            session_id: Session ID

        Returns:
            PMC 决策结果，如果不存在返回 None
        """
        from memory import MemRouter

        # 从模块上下文读取
        pmc_context = MemRouter.read_module_context(session_id, "pmc")

        if not pmc_context or not pmc_context.get("data"):
            return None

        data = pmc_context["data"]

        # 转换为 PmcDecision
        tasks = [
            Task(
                id=t["id"],
                name=t["name"],
                module=t["module"],
                priority=t["priority"],
                description=t.get("description", ""),
                dependencies=t.get("dependencies", [])
            )
            for t in data.get("tasks", [])
        ]

        return PmcDecision(
            session_id=session_id,
            pipeline_type=PipelineType(data["decision"]["pipeline_type"]),
            interface_count=data["decision"]["interface_count"],
            module_count=data["decision"]["module_count"],
            reasoning=data["decision"].get("reasoning", ""),
            tasks=tasks
        )


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发完成
# contract: 12_接手文档.md
# next: 测试 PMC 模块
# </YGA_END_ANCHOR>
