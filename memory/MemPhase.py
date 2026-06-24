# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemPhase.py
responsibility: 阶段门禁模块
exports: MemPhase
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
from typing import Tuple


class MemPhase:
    """阶段门禁模块 - 控制阶段流转"""

    # 阶段定义（严格顺序）
    PHASES = ['phase_1', 'phase_2', 'phase_3', 'phase_4', 'phase_5', 'phase_6']

    # 阶段门禁要求（进入该阶段需要的文档就绪标记）
    GATE_REQUIREMENTS = {
        'phase_2': ['requirement_ready'],       # 进入 phase_2 需要需求确认
        'phase_3': ['requirement_ready'],       # PMC 在需求确认后、L2 正式契约前
        'phase_4': ['interfaces_ready'],        # L3 需要 L2 正式契约
    }

    @staticmethod
    def can_accept_new_requirement(session_id: str) -> Tuple[bool, str]:
        """新需求只能在当前工作完成且已形成快照后进入当前工作区。"""
        from memory.MemSession import MemSession
        from memory.MemSnapshot import MemSnapshot

        meta = MemSession.get(session_id)
        session = meta.get('session', {})
        context = meta.get('context', {})

        if not context.get('requirement_ready', False):
            return True, "当前需求尚未确认，可以继续整理"

        completed = (
            session.get('phase') == 'phase_6'
            and session.get('phase_status') == 'completed'
            and context.get('current_work_completed', False)
        )
        if not completed:
            return False, "当前工作尚未交付完成，新需求只能进入等待区，不能进入工作区"

        if not MemSnapshot.has_completion_snapshot(session_id):
            return False, "当前工作尚未形成完成快照，新需求不能进入工作区"

        return True, "当前工作已完成且已快照，可以将新需求提升到工作区"

    @staticmethod
    def _get_phase_index(phase: str) -> int:
        """获取阶段索引"""
        if phase not in MemPhase.PHASES:
            raise ValueError(f"Unknown phase: {phase}")
        return MemPhase.PHASES.index(phase)

    @staticmethod
    def can_enter_phase(session_id: str, target_phase: str) -> Tuple[bool, str]:
        """
        检查是否可以进入指定阶段

        阶段门禁规则：
        1. 可以进入当前阶段（查看当前状态）
        2. 可以进入下一个阶段（需要满足文档要求）
        3. 不能跳跃（跳过中间阶段）
        4. 不能后退（已完成阶段不可返回）
        """
        from memory.MemSession import MemSession

        meta = MemSession.get(session_id)
        current_phase = meta['session'].get('phase', 'phase_1')
        context = meta.get('context', {})

        current_idx = MemPhase._get_phase_index(current_phase)
        target_idx = MemPhase._get_phase_index(target_phase)

        # 规则1：可以进入当前阶段（查看状态）
        if target_idx == current_idx:
            return True, "当前阶段"

        # 规则2：可以进入下一个阶段
        if target_idx == current_idx + 1:
            requirements = MemPhase.GATE_REQUIREMENTS.get(target_phase, [])
            for req in requirements:
                if not context.get(req, False):
                    req_name = req.replace('_ready', '文档')
                    return False, f"{req_name}未准备好，无法进入 {target_phase}"
            return True, "下一阶段"

        # 规则3：不能跳跃
        if target_idx > current_idx + 1:
            return False, f"阶段不允许跳跃：当前 {current_phase}，目标 {target_phase}"

        # 规则4：不能后退
        if target_idx < current_idx:
            return False, f"阶段不允许后退：当前 {current_phase}，目标 {target_phase}"

        return False, "未知错误"

    @staticmethod
    def complete_phase(session_id: str, phase: str):
        """标记阶段完成，推进到下一阶段"""
        from memory.MemSession import MemSession

        meta = MemSession.get(session_id)
        current_phase = meta['session'].get('phase', 'phase_1')

        # 验证当前阶段
        if phase != current_phase:
            raise ValueError(f"阶段不匹配：当前 {current_phase}，尝试完成 {phase}")

        phase_index = MemPhase._get_phase_index(phase)
        if phase_index == len(MemPhase.PHASES) - 1:
            MemSession.update_phase(session_id, phase, 'completed')
            MemSession.update_context(session_id, current_work_completed=True, active_change=False)
            from memory.MemSnapshot import MemSnapshot
            MemSnapshot.create(session_id, reason="delivery_complete")
            return

        # 推进到下一阶段
        next_phase = MemPhase.PHASES[phase_index + 1]

        MemSession.update_phase(session_id, next_phase, 'in_progress')

        # 更新上下文
        if phase == 'phase_1':
            MemSession.update_context(session_id, phase_1_confirmed=True)

    @staticmethod
    def get_phase_status(session_id: str) -> dict:
        """获取阶段状态"""
        from memory.MemSession import MemSession

        meta = MemSession.get(session_id)
        session = meta.get('session', {})
        context = meta.get('context', {})

        return {
            'current_phase': session.get('phase', 'phase_1'),
            'phase_status': session.get('phase_status', 'in_progress'),
            'context': context
        }

    @staticmethod
    def get_next_phase(phase: str) -> str:
        """获取下一个阶段"""
        phase_index = MemPhase._get_phase_index(phase)
        if phase_index < len(MemPhase.PHASES) - 1:
            return MemPhase.PHASES[phase_index + 1]
        return phase


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正阶段门禁逻辑（禁止跳跃/后退）
# contract: memory/index.md
# next: MemRouter
# </YGA_END_ANCHOR>
