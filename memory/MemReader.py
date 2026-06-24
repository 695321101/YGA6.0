# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemReader.py
responsibility: 读取模块（需求/接口/进度/对话/模块上下文）
exports: MemReader
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
from pathlib import Path


class MemReader:
    """读取模块 - 读取需求/接口/进度/对话/模块上下文"""

    @staticmethod
    def _get_session_dir(session_id: str) -> Path:
        """获取 session 目录"""
        return Path(__file__).parent.parent / "memory" / "sessions" / session_id

    @staticmethod
    def _get_logs_dir(session_id: str) -> Path:
        """获取 logs 目录"""
        return MemReader._get_session_dir(session_id) / "logs"

    @staticmethod
    def _get_chat_dir(session_id: str) -> Path:
        """获取 chat 目录"""
        return MemReader._get_session_dir(session_id) / "chat"

    @staticmethod
    def _get_pending_dir(session_id: str) -> Path:
        """获取待处理需求目录"""
        return MemReader._get_session_dir(session_id) / "pending"

    @staticmethod
    def _pending_manifest(session_id: str) -> dict:
        import yaml
        manifest_file = MemReader._get_pending_dir(session_id) / "manifest.yaml"
        if not manifest_file.exists():
            return {"requirements": []}
        with open(manifest_file, 'r', encoding='utf-8-sig') as f:
            return yaml.safe_load(f) or {"requirements": []}

    @staticmethod
    def read_requirement(session_id: str) -> str:
        """读取需求文档"""
        file_path = MemReader._get_logs_dir(session_id) / "requirement.md"
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()

    @staticmethod
    def read_interfaces(session_id: str) -> str:
        """读取接口文档"""
        file_path = MemReader._get_logs_dir(session_id) / "interfaces.md"
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()

    @staticmethod
    def read_progress(session_id: str) -> str:
        """读取进度文档"""
        file_path = MemReader._get_logs_dir(session_id) / "progress.md"
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()

    @staticmethod
    def read_chat(session_id: str, round_num: int = None) -> str:
        """读取对话记录"""
        chat_dir = MemReader._get_chat_dir(session_id)

        if round_num is not None:
            filename = f"round_{str(round_num).zfill(3)}.md"
            file_path = chat_dir / filename
            if not file_path.exists():
                return None
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                return f.read()
        else:
            # 读取所有对话记录
            all_chats = []
            for chat_file in sorted(chat_dir.glob("round_*.md")):
                with open(chat_file, 'r', encoding='utf-8-sig') as f:
                    all_chats.append(f.read())
            return "\n\n---\n\n".join(all_chats)

    @staticmethod
    def list_pending_requirements(session_id: str) -> list:
        """列出等待区需求。"""
        return MemReader._pending_manifest(session_id).get("requirements", [])

    @staticmethod
    def read_pending_requirement(session_id: str, pending_id: str = None) -> str:
        """读取等待区需求；未指定 ID 时读取最早未处理需求。"""
        manifest = MemReader._pending_manifest(session_id)
        items = manifest.get("requirements", [])
        if pending_id is None:
            candidates = [item for item in items if item.get("status") == "pending"]
            if not candidates:
                return None
            item = candidates[0]
        else:
            matched = [item for item in items if item.get("id") == pending_id]
            if not matched:
                return None
            item = matched[0]

        file_path = MemReader._get_pending_dir(session_id) / item["file"]
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()

    @staticmethod
    def read_context(session_id: str) -> dict:
        """读取通用上下文状态"""
        from memory.MemSession import MemSession
        return MemSession.get_context(session_id)

    @staticmethod
    def read_meta(session_id: str) -> dict:
        """读取 Session 元信息"""
        from memory.MemSession import MemSession
        return MemSession.get(session_id)

    @staticmethod
    def read_module_context(session_id: str, module: str) -> dict:
        """读取指定模块的上下文"""
        from memory.MemSession import MemSession
        return MemSession.get_module_context(session_id, module)

    @staticmethod
    def list_chats(session_id: str) -> list:
        """列出所有对话记录"""
        chat_dir = MemReader._get_chat_dir(session_id)
        return sorted([f.name for f in chat_dir.glob("round_*.md")])

    @staticmethod
    def list_module_contexts(session_id: str) -> dict:
        """列出所有模块的上下文摘要"""
        from memory.MemSession import MemSession
        return MemSession.list_module_contexts(session_id)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正：增加模块上下文读取
# contract: memory/index.md
# next: MemPhase, MemRouter
# </YGA_END_ANCHOR>
