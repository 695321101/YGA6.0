# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pmc
file: pmc/PmcReviewer.py
responsibility: PMC 审核模块（审核链路类型 + 任务队列）
exports: PmcReviewer, PmcReviewResult
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from typing import Tuple, List
from dataclasses import dataclass, field
from pmc.PmcPlanner import PmcDecision, PipelineType
from pmc.PmcBlueprint import PmcBlueprint


@dataclass
class PmcReviewResult:
    """PMC 审核结果"""
    passed: bool
    issues: List[str]
    suggestions: List[str] = None
    ai_reviews: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class PmcReviewer:
    """
    PMC 审核模块 - 审核 PMC 决策结果

    审核内容：
    1. 链路类型是否合理（接口数/模块数与链路类型是否匹配）
    2. 任务队列是否完整（任务列表是否覆盖完整流程）
    3. 并行关系是否正确（依赖关系是否合理）

    审核流程：
    PMC 决策 → PMC 审核 → 通过 → 流水线
                ↓
             打回重做（如果有问题）
    """

    @staticmethod
    def review_pmc_decision(
        decision: PmcDecision,
        interfaces_content: str = "",
        requirement_content: str = "",
        require_ai_review: bool = False
    ) -> PmcReviewResult:
        """
        审核 PMC 决策

        Args:
            decision: PMC 决策结果
            interfaces_content: 接口文档内容（用于验证接口数）

        Returns:
            审核结果
        """
        issues = []
        suggestions = []
        ai_reviews = []

        # 1. 审核链路类型
        type_issues, type_suggestions = PmcReviewer._review_pipeline_type(decision)
        issues.extend(type_issues)
        suggestions.extend(type_suggestions)

        # 2. 审核任务队列
        task_issues, task_suggestions = PmcReviewer._review_tasks(decision)
        issues.extend(task_issues)
        suggestions.extend(task_suggestions)

        # 3. 审核接口数与任务匹配
        if interfaces_content:
            count_issues, count_suggestions = PmcReviewer._review_interface_count(
                decision, interfaces_content
            )
            issues.extend(count_issues)
            suggestions.extend(count_suggestions)

        # 4. 审核蓝图一致性
        if getattr(decision, "blueprint", None):
            blueprint_issues, blueprint_suggestions = PmcReviewer._review_blueprint(decision)
            issues.extend(blueprint_issues)
            suggestions.extend(blueprint_suggestions)

            if require_ai_review and not blueprint_issues:
                ai_result = PmcReviewer._review_blueprint_with_ai(decision, requirement_content)
                ai_reviews.append(ai_result)
                if not ai_result.get("passed"):
                    issues.append(ai_result.get("reason") or "AI 蓝图审核未通过")

        passed = len(issues) == 0

        return PmcReviewResult(
            passed=passed,
            issues=issues,
            suggestions=suggestions,
            ai_reviews=ai_reviews
        )

    @staticmethod
    def _review_pipeline_type(decision: PmcDecision) -> Tuple[List[str], List[str]]:
        """审核链路类型是否合理"""
        issues = []
        suggestions = []

        interface_count = decision.interface_count
        module_count = decision.module_count
        pipeline_type = decision.pipeline_type

        # 检查接口数与链路类型是否匹配
        if pipeline_type == PipelineType.SIMPLE:
            if interface_count > 5:
                issues.append(
                    f"链路类型判断错误：{interface_count} 个接口应为 medium 或 complex 链路"
                )
            if module_count > 1:
                issues.append(
                    f"链路类型判断错误：{module_count} 个模块应为 medium 或 complex 链路"
                )

        elif pipeline_type == PipelineType.MEDIUM:
            if interface_count > 20:
                issues.append(
                    f"链路类型判断保守：{interface_count} 个接口建议为 complex 链路"
                )
                suggestions.append("考虑拆分模块或接口以简化复杂度")
            elif interface_count < 5:
                issues.append(
                    f"链路类型判断过重：{interface_count} 个接口建议为 simple 链路"
                )

            if module_count > 5:
                issues.append(
                    f"链路类型判断保守：{module_count} 个模块建议为 complex 链路"
                )
            elif module_count < 2:
                issues.append(
                    f"链路类型判断过重：{module_count} 个模块建议为 simple 链路"
                )

        else:  # COMPLEX
            if interface_count <= 20:
                suggestions.append(
                    f"链路类型可能过于复杂：{interface_count} 个接口考虑 medium 链路"
                )
            if module_count <= 5:
                suggestions.append(
                    f"链路类型可能过于复杂：{module_count} 个模块考虑 medium 链路"
                )

        return issues, suggestions

    @staticmethod
    def _review_blueprint(decision: PmcDecision) -> Tuple[List[str], List[str]]:
        """审核项目蓝图是否保持统一接口总账。"""
        return PmcBlueprint.validate(decision.blueprint or {})

    @staticmethod
    def _review_blueprint_with_ai(decision: PmcDecision, requirement_content: str) -> dict:
        """使用 AI 审查员审核 AI 生成的 PMC 蓝图。"""
        try:
            from review import AiArtifactReviewer
            result = AiArtifactReviewer.review_pmc_blueprint(requirement_content, decision.blueprint or {})
            return {
                "artifact": "pmc_blueprint",
                "passed": result.passed,
                "verdict": result.verdict,
                "reason": result.reason,
                "must_fix": result.must_fix,
                "prompt_notes": result.prompt_notes,
                "raw": result.raw,
            }
        except Exception as exc:
            return {
                "artifact": "pmc_blueprint",
                "passed": False,
                "verdict": "审核失败",
                "reason": f"AI 蓝图审核调用失败: {exc}",
                "raw": "",
            }

    @staticmethod
    def _review_tasks(decision: PmcDecision) -> Tuple[List[str], List[str]]:
        """审核任务队列是否完整"""
        issues = []
        suggestions = []

        tasks = decision.tasks
        pipeline_type = decision.pipeline_type

        if not tasks:
            issues.append("任务队列为空")
            return issues, suggestions

        # 检查是否有重复任务
        task_names = [t.name for t in tasks]
        if len(task_names) != len(set(task_names)):
            issues.append("存在重复任务")

        # 检查优先级连续性
        priorities = sorted([t.priority for t in tasks])
        expected = list(range(1, len(tasks) + 1))
        if priorities != expected:
            issues.append(f"任务优先级不连续：{priorities}")
            suggestions.append("重新编号任务优先级（1, 2, 3...）")

        # 根据链路类型检查任务覆盖
        if pipeline_type == PipelineType.SIMPLE:
            # 简单链路至少需要：后端 + 测试
            modules = set(t.module for t in tasks)
            if "backend" not in modules and "api" not in str(modules).lower():
                issues.append("缺少后端/API 开发任务")

            if "test" not in modules:
                suggestions.append("建议添加测试任务")

        elif pipeline_type == PipelineType.MEDIUM:
            # 中等链路需要：后端 + 至少一个测试
            modules = set(t.module for t in tasks)
            if "backend" not in modules:
                issues.append("缺少后端模块")

            if "test" not in modules:
                suggestions.append("建议添加集成测试任务")

        else:  # COMPLEX
            # 复杂链路需要：多个模块 + 数据库 + 测试
            modules = set(t.module for t in tasks)
            task_count = len(tasks)

            if task_count < 5:
                suggestions.append(
                    f"复杂链路建议更多任务：当前 {task_count} 个，建议 5+ 个"
                )

            if "test" not in modules:
                issues.append("复杂链路必须包含测试任务")

        return issues, suggestions

    @staticmethod
    def _review_interface_count(
        decision: PmcDecision,
        interfaces_content: str
    ) -> Tuple[List[str], List[str]]:
        """审核接口数量与任务匹配"""
        import re

        issues = []
        suggestions = []

        # 解析接口文档中的实际接口数
        actual_interfaces = 0
        for line in interfaces_content.split('\n'):
            patterns = [
                r'(?:###\s*\d+\.?\s*)?([A-Z]+)\s+(/[^\s\-]+)',
                r'(?:###\s*\d+\.?\s*)?([A-Z]+)\s+([^\s]+/[^\s]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    method = match.group(1).upper()
                    if method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']:
                        actual_interfaces += 1
                        break

        # 比较接口数差异
        declared_count = decision.interface_count
        if actual_interfaces != declared_count:
            if actual_interfaces > declared_count:
                issues.append(
                    f"接口数量不符：PMC 统计 {declared_count} 个，"
                    f"实际接口文档有 {actual_interfaces} 个"
                )
            else:
                suggestions.append(
                    f"接口数量可能遗漏：PMC 统计 {declared_count} 个，"
                    f"实际接口文档有 {actual_interfaces} 个"
                )

        return issues, suggestions

    @staticmethod
    def format_review_result(result: PmcReviewResult) -> str:
        """
        格式化审核结果为可读字符串

        Args:
            result: 审核结果

        Returns:
            格式化的审核结果
        """
        lines = []

        if result.passed:
            lines.append("PMC 审核结果：通过 ✓")
        else:
            lines.append("PMC 审核结果：打回 ✗")

        if result.issues:
            lines.append("\n问题：")
            for issue in result.issues:
                lines.append(f"  - {issue}")

        if result.suggestions:
            lines.append("\n建议：")
            for suggestion in result.suggestions:
                lines.append(f"  - {suggestion}")

        if result.ai_reviews:
            lines.append("\nAI 审核：")
            for item in result.ai_reviews:
                status = "通过" if item.get("passed") else "打回"
                lines.append(f"  - {item.get('artifact')}: {status} - {item.get('reason', '')}")

        return "\n".join(lines)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发完成
# contract: 12_接手文档.md
# next: PmcRouter, 流水线模块
# </YGA_END_ANCHOR>
