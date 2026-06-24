# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemWriter.py
responsibility: 写入模块（需求/接口/进度/对话）
exports: MemWriter
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
from pathlib import Path
from datetime import datetime
import yaml


class MemWriter:
    """写入模块 - 写入需求/接口/进度/对话文档"""

    @staticmethod
    def _get_session_dir(session_id: str) -> Path:
        """获取 session 目录"""
        return Path(__file__).parent.parent / "memory" / "sessions" / session_id

    @staticmethod
    def _get_logs_dir(session_id: str) -> Path:
        """获取 logs 目录"""
        logs_dir = MemWriter._get_session_dir(session_id) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @staticmethod
    def _get_chat_dir(session_id: str) -> Path:
        """获取 chat 目录"""
        chat_dir = MemWriter._get_session_dir(session_id) / "chat"
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    @staticmethod
    def _get_pending_dir(session_id: str) -> Path:
        """获取待处理需求目录"""
        pending_dir = MemWriter._get_session_dir(session_id) / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        return pending_dir

    @staticmethod
    def _pending_manifest_file(session_id: str) -> Path:
        return MemWriter._get_pending_dir(session_id) / "manifest.yaml"

    @staticmethod
    def _load_pending_manifest(session_id: str) -> dict:
        manifest_file = MemWriter._pending_manifest_file(session_id)
        if not manifest_file.exists():
            return {"requirements": []}
        with open(manifest_file, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f) or {"requirements": []}

    @staticmethod
    def _write_pending_manifest(session_id: str, manifest: dict):
        with open(MemWriter._pending_manifest_file(session_id), "w", encoding="utf-8-sig") as f:
            yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def _pending_count(manifest: dict) -> int:
        return len([item for item in manifest.get("requirements", []) if item.get("status") == "pending"])

    @staticmethod
    def _invalidate_downstream_for_change(session_id: str, snapshot_id: str):
        """新需求开始后，旧接口和下游产物不再作为当前事实。"""
        from memory.MemSession import MemSession

        logs_dir = MemWriter._get_logs_dir(session_id)
        stale_files = [
            logs_dir / "interfaces.md",
            MemWriter._get_session_dir(session_id) / "context" / "pmc" / "pmc_context.yaml",
        ]
        for file_path in stale_files:
            if file_path.exists():
                file_path.unlink()

        stale_data = {
            "stale": True,
            "stale_from_snapshot": snapshot_id,
            "reason": "new_requirement_started",
            "updated_at": datetime.now().isoformat(),
        }
        for module in ("pmc", "pipeline", "test", "review"):
            MemSession.replace_module_context(session_id, module, stale_data)

    @staticmethod
    def _ensure_markdown_header(content: str, title: str, session_id: str) -> str:
        """确保 Markdown 文件有标准头部"""
        if content.startswith('# '):
            return content

        header = f"# {title}\n> Session: {session_id}\n> Created: {datetime.now().isoformat()}\n\n---\n\n"
        return header + content

    @staticmethod
    def _strip_generated_header(content: str) -> str:
        """移除等待区生成的文件头，便于提升时重新包装当前工作区标题。"""
        normalized = content.replace("\r\n", "\n")
        if normalized.startswith("# ") and "\n---\n\n" in normalized:
            return normalized.split("\n---\n\n", 1)[1]
        return content

    @staticmethod
    def enqueue_pending_requirement(session_id: str, content: str):
        """
        写入等待区需求。

        等待区只记录用户新输入，不覆盖当前轮次的 requirement.md，也不触发 PMC/Pipeline 编排。
        """
        from memory.MemSession import MemSession

        MemSession.get(session_id)
        manifest = MemWriter._load_pending_manifest(session_id)
        pending_dir = MemWriter._get_pending_dir(session_id)
        next_num = len(manifest.get("requirements", [])) + 1
        pending_id = f"pending_{str(next_num).zfill(3)}"
        filename = f"{pending_id}.md"
        file_path = pending_dir / filename

        content = MemWriter._ensure_markdown_header(content, "待处理需求", session_id)
        with open(file_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

        manifest.setdefault("requirements", []).append({
            "id": pending_id,
            "file": filename,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        })
        MemWriter._write_pending_manifest(session_id, manifest)
        MemSession.update_context(session_id, pending_requirements=MemWriter._pending_count(manifest))
        try:
            from pipeline.PipelineDrain import PipelineDrain
            PipelineDrain.request_drain(session_id, reason=f"pending_requirement:{pending_id}")
        except Exception as exc:
            MemSession.update_context(session_id, pipeline_drain_error=str(exc))
        return pending_id

    @staticmethod
    def _prepare_change_workspace(session_id: str) -> str:
        """当前工作完成后，准备新一轮工作区并失效下游产物。"""
        from memory.MemSession import MemSession
        from memory.MemSnapshot import MemSnapshot

        snapshot = MemSnapshot.latest(session_id)
        snapshot_id = snapshot["id"] if snapshot else MemSnapshot.create(session_id, reason="pre_change")
        MemWriter._invalidate_downstream_for_change(session_id, snapshot_id)
        MemSession.update_phase(session_id, 'phase_1', 'in_progress')
        MemSession.update_context(
            session_id,
            requirement_draft=False,
            requirement_ready=False,
            interfaces_draft=False,
            interfaces_ready=False,
            contract_confirmed=False,
            phase_1_confirmed=False,
            current_work_completed=False,
            active_change=True,
            stale_from_snapshot=snapshot_id,
            pmc_ready=False,
            pipeline_mode="active",
            pipeline_reject_new=False,
            pipeline_active_run="",
            stable_checkpoint=snapshot_id,
        )
        return snapshot_id

    @staticmethod
    def start_next_pending_requirement(session_id: str):
        """将等待区最早的一条需求提升为当前工作区需求草稿。"""
        from memory.MemPhase import MemPhase
        from memory.MemSession import MemSession

        can_accept, msg = MemPhase.can_accept_new_requirement(session_id)
        if not can_accept:
            raise PermissionError(msg)

        manifest = MemWriter._load_pending_manifest(session_id)
        pending_items = [item for item in manifest.get("requirements", []) if item.get("status") == "pending"]
        if not pending_items:
            raise ValueError("没有待处理需求")

        item = pending_items[0]
        pending_file = MemWriter._get_pending_dir(session_id) / item["file"]
        if not pending_file.exists():
            raise FileNotFoundError(f"Pending requirement not found: {item['file']}")

        with open(pending_file, "r", encoding="utf-8-sig") as f:
            content = f.read()

        snapshot_id = MemWriter._prepare_change_workspace(session_id)
        MemWriter._write_current_requirement(session_id, MemWriter._strip_generated_header(content))

        item["status"] = "applied"
        item["applied_at"] = datetime.now().isoformat()
        item["stale_from_snapshot"] = snapshot_id
        MemWriter._write_pending_manifest(session_id, manifest)
        MemSession.update_context(
            session_id,
            requirement_draft=True,
            pending_requirements=MemWriter._pending_count(manifest),
        )
        return item["id"]

    @staticmethod
    def _write_current_requirement(session_id: str, content: str):
        """写入当前工作区需求草稿。"""
        content = MemWriter._ensure_markdown_header(content, "需求文档（草稿）", session_id)
        file_path = MemWriter._get_logs_dir(session_id) / "requirement.md"
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)

    @staticmethod
    def write_requirement_draft(session_id: str, content: str):
        """
        写入需求文档草稿（AI 生成，还未用户确认）

        注意：这只是草稿，不会推进阶段
        """
        from memory.MemPhase import MemPhase
        from memory.MemSession import MemSession

        can_accept, msg = MemPhase.can_accept_new_requirement(session_id)
        if not can_accept:
            raise PermissionError(msg)

        meta = MemSession.get(session_id)
        context = meta.get('context', {})
        starting_new_requirement = (
            context.get('requirement_ready', False)
            and context.get('current_work_completed', False)
        )

        if starting_new_requirement:
            MemWriter._prepare_change_workspace(session_id)

        MemWriter._write_current_requirement(session_id, content)

        # 只标记草稿状态
        MemSession.update_context(session_id, requirement_draft=True)

    @staticmethod
    def confirm_requirement(session_id: str):
        """
        确认需求文档（用户确认后调用）

        这会推进阶段：phase_1 -> phase_2
        """
        from memory.MemSession import MemSession
        from memory.MemPhase import MemPhase

        # 更新上下文状态
        MemSession.update_context(session_id, requirement_ready=True)

        # 推进阶段
        if MemPhase.get_phase_status(session_id)['current_phase'] == 'phase_1':
            MemPhase.complete_phase(session_id, 'phase_1')

    @staticmethod
    def write_interfaces_draft(session_id: str, content: str):
        """
        写入接口文档草稿（AI 生成，还未用户确认）
        """
        content = MemWriter._ensure_markdown_header(content, "接口文档（草稿）", session_id)
        file_path = MemWriter._get_logs_dir(session_id) / "interfaces.md"
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)

        from memory.MemSession import MemSession
        MemSession.update_context(session_id, interfaces_draft=True)

    @staticmethod
    def confirm_interfaces(session_id: str):
        """
        确认接口文档（用户确认后调用）

        这会推进阶段：phase_2 -> phase_3
        """
        from memory.MemSession import MemSession
        from memory.MemPhase import MemPhase

        MemSession.update_context(session_id, interfaces_ready=True)

        if MemPhase.get_phase_status(session_id)['current_phase'] == 'phase_2':
            MemPhase.complete_phase(session_id, 'phase_2')

    @staticmethod
    def write_interfaces(session_id: str, content: str):
        """
        写入接口文档草稿（AI 生成）

        注意：这只是草稿，不会自动确认和推进阶段
        如需用户确认，单独调用 confirm_interfaces
        """
        MemWriter.write_interfaces_draft(session_id, content)

    @staticmethod
    def write_progress(session_id: str, content: str):
        """写入进度文档"""
        content = MemWriter._ensure_markdown_header(content, "开发进度", session_id)
        file_path = MemWriter._get_logs_dir(session_id) / "progress.md"
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)

    @staticmethod
    def append_chat(session_id: str, round_num: int, content: str):
        """追加对话记录"""
        title = f"对话记录 - 第 {round_num} 轮"
        content = MemWriter._ensure_markdown_header(content, title, session_id)
        filename = f"round_{str(round_num).zfill(3)}.md"
        file_path = MemWriter._get_chat_dir(session_id) / filename
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)

    @staticmethod
    def append_chat_raw(session_id: str, content: str):
        """追加对话记录（自动编号）"""
        chat_dir = MemWriter._get_chat_dir(session_id)

        existing = list(chat_dir.glob("round_*.md"))
        next_num = len(existing) + 1

        title = f"对话记录 - 第 {next_num} 轮"
        content = MemWriter._ensure_markdown_header(content, title, session_id)
        filename = f"round_{str(next_num).zfill(3)}.md"
        file_path = chat_dir / filename
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)

        return next_num


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正：区分草稿和确认状态，自动推进阶段
# contract: memory/index.md
# next: MemReader, MemRouter
# </YGA_END_ANCHOR>
