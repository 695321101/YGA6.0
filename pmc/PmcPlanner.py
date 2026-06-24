# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pmc
file: pmc/PmcPlanner.py
responsibility: PMC 决策模块（读取需求，输出链路类型 + 任务队列）
exports: PmcPlanner, PipelineType
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
import re
from enum import Enum
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from pmc.PmcBlueprint import PmcBlueprint


class PipelineType(Enum):
    """流水线链路类型"""
    SIMPLE = "simple"      # 简单链路：≤5 接口，=1 模块
    MEDIUM = "medium"      # 中等链路：5-20 接口，2-5 模块
    COMPLEX = "complex"    # 复杂链路：>20 接口，>5 模块


@dataclass
class Task:
    """任务单元"""
    id: int
    name: str
    module: str
    priority: int
    description: str = ""
    dependencies: List[int] = field(default_factory=list)


@dataclass
class PmcDecision:
    """PMC 决策结果"""
    session_id: str
    pipeline_type: PipelineType
    interface_count: int
    module_count: int
    tasks: List[Task]
    reasoning: str = ""
    blueprint: Dict = field(default_factory=dict)


class PmcPlanner:
    """
    PMC 决策模块 - 分析需求，生成链路决策

    职责：
    1. 读取需求文档
    2. 分析接口数量和模块数量
    3. 判断链路类型
    4. 生成任务队列
    5. 输出 PMC 决策
    """

    # 链路类型判断阈值
    THRESHOLDS = {
        PipelineType.SIMPLE: {"max_interface": 5, "max_module": 1},
        PipelineType.MEDIUM: {"min_interface": 5, "max_interface": 20, "min_module": 2, "max_module": 5},
        PipelineType.COMPLEX: {"min_interface": 20, "min_module": 5}
    }

    @staticmethod
    def parse_requirement(requirement_content: str) -> Dict:
        """
        解析需求文档

        Args:
            requirement_content: 需求文档内容

        Returns:
            解析后的需求字典
        """
        result = {
            "project_name": "",
            "tech_stack": "",
            "features": [],
            "interface_hints": []
        }

        if not requirement_content:
            return result

        lines = requirement_content.split('\n')

        for line in lines:
            line = line.strip()

            # 项目名称
            if '项目名称' in line or '项目名' in line:
                match = re.search(r'[:：]\s*(.+)', line)
                if match:
                    result["project_name"] = match.group(1).strip()

            # 技术栈
            elif '技术栈' in line:
                match = re.search(r'[:：]\s*(.+)', line)
                if match:
                    result["tech_stack"] = match.group(1).strip()

            # 功能列表
            elif re.match(r'^\d+[\.\)、]\s*', line):
                feature = re.sub(r'^\d+[\.\)、]\s*', '', line)
                result["features"].append(feature)

            # 接口提示（包含 API 关键词）
            elif '/api/' in line.lower() or '接口' in line:
                result["interface_hints"].append(line)

        return result

    @staticmethod
    def count_interfaces(interfaces_content: str) -> Tuple[int, List[str]]:
        """
        统计接口数量

        Args:
            interfaces_content: 接口文档内容

        Returns:
            (接口数量, 接口列表)
        """
        if not interfaces_content:
            return 0, []

        interfaces = []
        lines = interfaces_content.split('\n')

        for line in lines:
            # 匹配接口定义：### N. METHOD /path 或 - METHOD /path
            # 例如: ### 1. POST /api/user/register
            # 例如: - GET /api/users/:id
            patterns = [
                r'(?:###\s*\d+\.?\s*)?([A-Z]+)\s+(/[^\s\-]+)',  # METHOD /path
                r'(?:###\s*\d+\.?\s*)?([A-Z]+)\s+([^\s]+/[^\s]+)',  # METHOD xxx/path
            ]

            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    method = match.group(1).upper()
                    path = match.group(2).strip('`.,;:')
                    if method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']:
                        interfaces.append(f"{method} {path}")
                        break

        return len(interfaces), interfaces

    @staticmethod
    def count_modules(requirement: Dict, interfaces_content: str) -> Tuple[int, List[str]]:
        """
        统计确定性的技术层模块数量。

        注意：业务模块拆分由 AI 蓝图决定，本地代码不根据关键词或接口路径猜业务边界。

        Args:
            requirement: 解析后的需求
            interfaces_content: 接口文档内容

        Returns:
            (模块数量, 模块列表)
        """
        modules = set()

        # 从技术栈推断模块
        tech_stack = requirement.get("tech_stack", "").lower()

        # 基础后端模块
        if "python" in tech_stack or "fastapi" in tech_stack or "flask" in tech_stack or "django" in tech_stack:
            modules.add("backend")

        # 前端模块
        if "vue" in tech_stack or "react" in tech_stack or "angular" in tech_stack:
            modules.add("frontend")

        # 数据库模块
        if "mysql" in tech_stack or "postgres" in tech_stack or "mongodb" in tech_stack:
            modules.add("database")

        # 默认至少有一个模块
        if not modules:
            modules.add("backend")

        return len(modules), sorted(list(modules))

    @classmethod
    def determine_pipeline_type(cls, interface_count: int, module_count: int) -> PipelineType:
        """
        判断链路类型

        Args:
            interface_count: 接口数量
            module_count: 模块数量

        Returns:
            链路类型
        """
        # 复杂链路：>20 接口 或 >5 模块
        if interface_count > 20 or module_count > 5:
            return PipelineType.COMPLEX

        # 中等链路：5-20 接口 且 2-5 模块
        if interface_count >= 5 and interface_count <= 20 and module_count >= 2:
            return PipelineType.MEDIUM

        # 简单链路：≤5 接口 且 =1 模块
        if interface_count <= 5 and module_count <= 1:
            return PipelineType.SIMPLE

        # 边界情况，根据接口数判断
        if interface_count > 5:
            return PipelineType.MEDIUM
        else:
            return PipelineType.SIMPLE

    @classmethod
    def generate_tasks(cls, requirement: Dict, pipeline_type: PipelineType) -> List[Task]:
        """
        生成任务队列

        Args:
            requirement: 解析后的需求
            pipeline_type: 链路类型

        Returns:
            任务列表
        """
        tasks = []
        task_id = 1

        # 根据链路类型确定任务
        if pipeline_type == PipelineType.SIMPLE:
            # 简单链路：后端 + 测试
            tasks.append(Task(
                id=task_id,
                name="后端 API 开发",
                module="backend",
                priority=1,
                description="实现所有接口的后端逻辑"
            ))
            task_id += 1

            tasks.append(Task(
                id=task_id,
                name="本地测试",
                module="test",
                priority=2,
                description="编写单元测试和集成测试"
            ))
            task_id += 1

        elif pipeline_type == PipelineType.MEDIUM:
            # 中等链路：后端 + 数据库 + 测试
            tasks.append(Task(
                id=task_id,
                name="后端 API 开发",
                module="backend",
                priority=task_id,
                description="实现核心业务逻辑"
            ))
            task_id += 1

            tasks.append(Task(
                id=task_id,
                name="数据库设计",
                module="database",
                priority=task_id,
                description="设计数据库表和关系"
            ))
            task_id += 1

            tasks.append(Task(
                id=task_id,
                name="集成测试",
                module="test",
                priority=task_id,
                description="端到端集成测试"
            ))

        else:  # COMPLEX
            # 复杂链路：多个模块 + 详细规划
            project_name = requirement.get("project_name", "项目")

            # 核心业务模块
            for feature in requirement.get("features", [])[:5]:
                tasks.append(Task(
                    id=task_id,
                    name=f"功能开发：{feature}",
                    module="backend",
                    priority=task_id,
                    description=f"实现 {feature} 功能"
                ))
                task_id += 1

            # 基础设施任务
            tasks.append(Task(
                id=task_id,
                name="数据库设计",
                module="database",
                priority=task_id,
                description="设计数据库表结构和索引"
            ))
            task_id += 1

            tasks.append(Task(
                id=task_id,
                name="API 路由开发",
                module="backend",
                priority=task_id,
                description="实现 API 路由和中间件"
            ))
            task_id += 1

            tasks.append(Task(
                id=task_id,
                name="测试套件",
                module="test",
                priority=task_id,
                description="完整的测试覆盖"
            ))

        return tasks

    @classmethod
    def plan(
        cls,
        session_id: str,
        requirement_content: str,
        interfaces_content: str = "",
        ai_blueprint: Optional[Dict] = None
    ) -> PmcDecision:
        """
        PMC 规划主流程

        Args:
            session_id: Session ID
            requirement_content: 需求文档内容
            interfaces_content: 接口文档内容（可选）

        Returns:
            PMC 决策结果
        """
        # 1. 解析需求
        requirement = cls.parse_requirement(requirement_content)

        # 2. 统计接口数量
        if interfaces_content:
            interface_count, interfaces = cls.count_interfaces(interfaces_content)
        else:
            # 从需求中推断接口数
            interface_count = len(requirement.get("features", []))
            interfaces = []

        # 3. 接收 AI 明确给出的统一蓝图；本地不根据需求拆业务模块
        blueprint = PmcBlueprint.from_ai_blueprint(session_id, requirement, ai_blueprint or {})

        # 4. 统计模块数量：技术层模块来自本地确定性统计，业务模块只来自 AI 蓝图
        legacy_module_count, modules = cls.count_modules(requirement, interfaces_content)
        blueprint_module_ids = {
            module.get("id")
            for module in blueprint.get("module_cards", [])
            if module.get("id")
        }
        module_count = max(legacy_module_count, len(blueprint_module_ids))
        module_card_count = len(blueprint.get("module_cards", []))

        # 5. 判断链路类型
        pipeline_type = cls.determine_pipeline_type(interface_count, module_count)

        # 6. 生成任务队列
        tasks = cls.generate_tasks(requirement, pipeline_type)

        # 7. 生成推理说明
        reasoning = (
            f"根据需求分析：共 {interface_count} 个接口，{module_count} 个模块计数，"
            f"判断为 {pipeline_type.value} 链路。生成 {len(tasks)} 个任务。"
        )
        if blueprint:
            reasoning += f"已接收 AI 蓝图：{module_card_count} 张模块卡片和统一接口总账。"
        else:
            reasoning += "未收到 AI 蓝图，本地不生成业务模块拆分。"

        return PmcDecision(
            session_id=session_id,
            pipeline_type=pipeline_type,
            interface_count=interface_count,
            module_count=module_count,
            tasks=tasks,
            reasoning=reasoning,
            blueprint=blueprint
        )


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发完成
# contract: 12_接手文档.md
# next: PmcReviewer, 流水线模块
# </YGA_END_ANCHOR>
