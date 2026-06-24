# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemRouter.py
responsibility: 统一入口（路由到各子模块）
exports: MemRouter
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
from typing import Optional, Tuple


class MemRouter:
    """记忆区统一入口 - 所有模块通过此入口访问记忆区"""

    # 来源白名单（只接受这些来源的写入）
    SOURCE_WHITELIST = ['User', 'AI', 'System', 'PMC', 'L0', 'L2', 'L3', 'Test']

    # 信息类型映射
    TYPE_MAPPING = {
        'requirement': 'write_requirement_draft',
        'pending_requirement': 'enqueue_pending_requirement',
        'requirement_confirm': 'confirm_requirement',
        'interfaces': 'write_interfaces',
        'interfaces_confirm': 'confirm_interfaces',
        'progress': 'write_progress',
        'chat': 'append_chat',
        'chat_raw': 'append_chat_raw',
    }

    # 支持的模块
    MODULES = ['pmc', 'pipeline', 'test', 'review']

    @staticmethod
    def write(session_id: str, info_type: str, content: str = '', source: str = 'System') -> bool:
        """
        写入记忆区

        Args:
            session_id: Session ID
            info_type: 信息类型
            content: 内容
            source: 来源 (User/AI/System/PMC/L0/L2/L3/Test)

        Returns:
            bool: 是否成功
        """
        if source not in MemRouter.SOURCE_WHITELIST:
            raise ValueError(f"Unknown source: {source}")

        from memory.MemWriter import MemWriter

        method = MemRouter.TYPE_MAPPING.get(info_type)
        if not method:
            raise ValueError(f"Unknown info_type: {info_type}")

        write_method = getattr(MemWriter, method)

        # 特殊处理：不需要 content 的方法
        if info_type in ['requirement_confirm', 'interfaces_confirm']:
            return write_method(session_id)
        else:
            return write_method(session_id, content)

    @staticmethod
    def read(session_id: str, info_type: str, round_num: int = None) -> Optional[str]:
        """
        读取记忆区

        Args:
            session_id: Session ID
            info_type: 信息类型 (requirement/interfaces/progress/chat/context/meta/module_context)
            round_num: 对话轮次（仅 chat 使用）

        Returns:
            str: 内容，未找到返回 None
        """
        from memory.MemReader import MemReader

        if info_type == 'requirement':
            return MemReader.read_requirement(session_id)
        elif info_type == 'interfaces':
            return MemReader.read_interfaces(session_id)
        elif info_type == 'progress':
            return MemReader.read_progress(session_id)
        elif info_type == 'chat':
            return MemReader.read_chat(session_id, round_num)
        elif info_type == 'context':
            return MemReader.read_context(session_id)
        elif info_type == 'meta':
            return MemReader.read_meta(session_id)
        elif info_type == 'module_context':
            return None  # 需要指定 module
        elif info_type == 'pending_requirements':
            return MemReader.list_pending_requirements(session_id)
        elif info_type == 'pending_requirement':
            return MemReader.read_pending_requirement(session_id)
        else:
            raise ValueError(f"Unknown info_type: {info_type}")

    @staticmethod
    def read_module_context(session_id: str, module: str) -> dict:
        """读取指定模块的上下文"""
        if module not in MemRouter.MODULES:
            raise ValueError(f"Unknown module: {module}")
        from memory.MemReader import MemReader
        return MemReader.read_module_context(session_id, module)

    @staticmethod
    def update_module_context(session_id: str, module: str, data: dict):
        """更新指定模块的上下文"""
        if module not in MemRouter.MODULES:
            raise ValueError(f"Unknown module: {module}")
        from memory.MemSession import MemSession
        MemSession.update_module_context(session_id, module, data)

    @staticmethod
    def update_context(session_id: str, **kwargs):
        """更新通用上下文状态"""
        from memory.MemSession import MemSession
        MemSession.update_context(session_id, **kwargs)

    @staticmethod
    def create_session(user_id: str, project_name: str) -> str:
        """创建新 Session"""
        from memory.MemSession import MemSession
        return MemSession.create(user_id, project_name)

    @staticmethod
    def get_session(session_id: str) -> dict:
        """获取 Session 信息"""
        from memory.MemSession import MemSession
        return MemSession.get(session_id)

    @staticmethod
    def list_sessions() -> list:
        """列出所有 Session"""
        from memory.MemSession import MemSession
        return MemSession.list_sessions()

    @staticmethod
    def check_phase_gate(session_id: str, target_phase: str) -> Tuple[bool, str]:
        """检查阶段门禁"""
        from memory.MemPhase import MemPhase
        return MemPhase.can_enter_phase(session_id, target_phase)

    @staticmethod
    def complete_phase(session_id: str, phase: str):
        """标记阶段完成"""
        from memory.MemPhase import MemPhase
        MemPhase.complete_phase(session_id, phase)

    @staticmethod
    def get_phase_status(session_id: str) -> dict:
        """获取阶段状态"""
        from memory.MemPhase import MemPhase
        return MemPhase.get_phase_status(session_id)

    @staticmethod
    def can_accept_new_requirement(session_id: str) -> Tuple[bool, str]:
        """检查当前 session 是否可以把新需求提升到工作区。"""
        from memory.MemPhase import MemPhase
        return MemPhase.can_accept_new_requirement(session_id)

    @staticmethod
    def create_snapshot(session_id: str, reason: str = "manual") -> str:
        """创建当前 session 快照。"""
        from memory.MemSnapshot import MemSnapshot
        return MemSnapshot.create(session_id, reason)

    @staticmethod
    def latest_snapshot(session_id: str) -> Optional[dict]:
        """读取最新快照。"""
        from memory.MemSnapshot import MemSnapshot
        return MemSnapshot.latest(session_id)

    @staticmethod
    def list_snapshots(session_id: str) -> list:
        """列出当前 session 快照。"""
        from memory.MemSnapshot import MemSnapshot
        return MemSnapshot.list(session_id)

    @staticmethod
    def start_next_pending_requirement(session_id: str):
        """把等待区最早的一条需求提升到当前工作区。"""
        from memory.MemWriter import MemWriter
        return MemWriter.start_next_pending_requirement(session_id)

    @staticmethod
    def list_pending_requirements(session_id: str) -> list:
        """列出等待区需求。"""
        from memory.MemReader import MemReader
        return MemReader.list_pending_requirements(session_id)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正：增加模块上下文操作
# contract: memory/index.md
# next: 其他模块通过 MemRouter 访问记忆区
# </YGA_END_ANCHOR>
