# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemSession.py
responsibility: Session 管理（上下文追踪）
exports: MemSession
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
import os
import yaml
from pathlib import Path
from datetime import datetime


class MemSession:
    """Session 管理模块 - 管理多轮对话上下文"""

    # 模块列表（每个模块有独立的上下文目录）
    MODULES = ['pmc', 'pipeline', 'test', 'review']

    @staticmethod
    def _get_sessions_dir() -> Path:
        """获取 sessions 目录"""
        root = Path(__file__).parent.parent / "memory" / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def create(user_id: str, project_name: str) -> str:
        """创建新 Session"""
        session_id = MemSession._generate_session_id()
        session_dir = MemSession._get_sessions_dir() / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (session_dir / "chat").mkdir(exist_ok=True)
        (session_dir / "logs").mkdir(exist_ok=True)
        (session_dir / "pending").mkdir(exist_ok=True)
        (session_dir / "artifacts").mkdir(exist_ok=True)
        (session_dir / "context").mkdir(exist_ok=True)  # 通用上下文
        (session_dir / "snapshots").mkdir(exist_ok=True)

        # 为每个模块创建独立上下文目录
        for module in MemSession.MODULES:
            (session_dir / "context" / module).mkdir(exist_ok=True)

        # 初始化 meta.yaml
        meta = {
            "session": {
                "id": session_id,
                "user_id": user_id,
                "project_id": f"proj_{session_id[:16]}",
                "project_name": project_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "phase": "phase_1",
                "phase_status": "in_progress"
            },
            "context": {
                "requirement_draft": False,
                "requirement_ready": False,
                "interfaces_draft": False,
                "interfaces_ready": False,
                "contract_confirmed": False,
                "current_phase": "phase_1",
                "phase_1_confirmed": False,
                "current_work_completed": False,
                "active_change": False,
                "stale_from_snapshot": "",
                "pending_requirements": 0,
                "pipeline_mode": "active",
                "pipeline_reject_new": False,
                "pipeline_active_run": "",
                "stable_checkpoint": ""
            },
            "tech_stack": {
                "language": "Python",
                "framework": "FastAPI",
                "backend_only": True
            }
        }

        meta_file = session_dir / "meta.yaml"
        with open(meta_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(meta, f, allow_unicode=True, default_flow_style=False)

        # 初始化各模块的上下文文件
        for module in MemSession.MODULES:
            module_context_file = session_dir / "context" / module / f"{module}_context.yaml"
            module_context = {
                "module": module,
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "data": {}  # 模块自己的数据
            }
            with open(module_context_file, 'w', encoding='utf-8-sig') as f:
                yaml.dump(module_context, f, allow_unicode=True, default_flow_style=False)

        return session_id

    @staticmethod
    def _generate_session_id() -> str:
        """生成 Session ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = format(int(datetime.now().timestamp() * 1000) % 100000000, '08x')
        return f"sess_{timestamp}_{random_suffix}"

    @staticmethod
    def get(session_id: str) -> dict:
        """获取 Session 信息"""
        meta_file = MemSession._get_sessions_dir() / session_id / "meta.yaml"
        if not meta_file.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        with open(meta_file, 'r', encoding='utf-8-sig') as f:
            return yaml.safe_load(f)

    @staticmethod
    def update_context(session_id: str, **kwargs):
        """更新通用上下文状态"""
        meta = MemSession.get(session_id)
        meta['session']['updated_at'] = datetime.now().isoformat()
        meta['context'].update(kwargs)

        meta_file = MemSession._get_sessions_dir() / session_id / "meta.yaml"
        with open(meta_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(meta, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def get_context(session_id: str) -> dict:
        """获取通用上下文状态"""
        meta = MemSession.get(session_id)
        return meta.get('context', {})

    @staticmethod
    def update_phase(session_id: str, phase: str, status: str):
        """更新阶段状态"""
        meta = MemSession.get(session_id)
        meta['session']['updated_at'] = datetime.now().isoformat()
        meta['session']['phase'] = phase
        meta['session']['phase_status'] = status
        # 同步更新 context 中的 current_phase
        meta['context']['current_phase'] = phase

        meta_file = MemSession._get_sessions_dir() / session_id / "meta.yaml"
        with open(meta_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(meta, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def list_sessions() -> list:
        """列出所有 Session"""
        sessions_dir = MemSession._get_sessions_dir()
        if not sessions_dir.exists():
            return []

        sessions = []
        for item in sessions_dir.iterdir():
            if item.is_dir():
                meta_file = item / "meta.yaml"
                if meta_file.exists():
                    with open(meta_file, 'r', encoding='utf-8-sig') as f:
                        sessions.append(yaml.safe_load(f))
        return sessions

    # ========== 模块独立上下文 ==========

    @staticmethod
    def get_module_context(session_id: str, module: str) -> dict:
        """获取指定模块的上下文"""
        if module not in MemSession.MODULES:
            raise ValueError(f"Unknown module: {module}")

        module_context_file = MemSession._get_sessions_dir() / session_id / "context" / module / f"{module}_context.yaml"
        if not module_context_file.exists():
            return None

        with open(module_context_file, 'r', encoding='utf-8-sig') as f:
            return yaml.safe_load(f)

    @staticmethod
    def update_module_context(session_id: str, module: str, data: dict):
        """更新指定模块的上下文"""
        if module not in MemSession.MODULES:
            raise ValueError(f"Unknown module: {module}")

        # 获取现有上下文
        module_context_file = MemSession._get_sessions_dir() / session_id / "context" / module / f"{module}_context.yaml"

        if module_context_file.exists():
            with open(module_context_file, 'r', encoding='utf-8-sig') as f:
                context = yaml.safe_load(f)
        else:
            context = {
                "module": module,
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "data": {}
            }

        if not context or not isinstance(context.get("data"), dict):
            raise ValueError(
                f"模块上下文格式无效: {module_context_file}；"
                "请只通过 MemRouter.update_module_context / replace_module_context 写入"
            )

        context["updated_at"] = datetime.now().isoformat()
        context["data"].update(data)

        with open(module_context_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(context, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def replace_module_context(session_id: str, module: str, data: dict):
        """替换指定模块的上下文数据。"""
        if module not in MemSession.MODULES:
            raise ValueError(f"Unknown module: {module}")

        module_context_file = MemSession._get_sessions_dir() / session_id / "context" / module / f"{module}_context.yaml"
        context = {
            "module": module,
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "data": data
        }

        if module_context_file.exists():
            with open(module_context_file, 'r', encoding='utf-8-sig') as f:
                existing = yaml.safe_load(f) or {}
            context["created_at"] = existing.get("created_at", context["created_at"])

        with open(module_context_file, 'w', encoding='utf-8-sig') as f:
            yaml.dump(context, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def list_module_contexts(session_id: str) -> dict:
        """列出所有模块的上下文摘要"""
        result = {}
        for module in MemSession.MODULES:
            context = MemSession.get_module_context(session_id, module)
            if context:
                result[module] = {
                    "updated_at": context.get('updated_at'),
                    "data_keys": list(context.get('data', {}).keys())
                }
        return result


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正：增加模块独立上下文目录
# contract: memory/index.md
# next: MemWriter, MemReader, MemPhase, MemRouter
# </YGA_END_ANCHOR>
