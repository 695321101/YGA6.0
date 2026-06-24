# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pipeline
file: pipeline/PipelineDrain.py
responsibility: Drain 控制 - 停止扩张并维护 Pipeline/Memory/Output 对齐点
exports: PipelineDrain
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from datetime import datetime
from uuid import uuid4
from typing import Dict, Tuple


class PipelineDrain:
    """Pipeline Drain 控制层：允许已开始的 run 完成，拒绝未开始的新 run。"""

    ACTIVE = "active"
    DRAINING = "draining"
    CHECKPOINTING = "checkpointing"
    READY = "ready_for_new_requirements"

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"run_{stamp}_{uuid4().hex[:8]}"

    @staticmethod
    def _default_state() -> Dict:
        return {
            "mode": PipelineDrain.ACTIVE,
            "reject_new_pipeline": False,
            "active_run_id": "",
            "active_run": None,
            "last_run": None,
            "last_checkpoint_snapshot": "",
            "checkpointed_at": "",
            "drain_requested_at": "",
            "drain_reason": "",
            "cancelled_pending": [],
            "history": [],
        }

    @staticmethod
    def _load_state(session_id: str) -> Dict:
        from memory.MemSession import MemSession

        context = MemSession.get_module_context(session_id, "pipeline") or {}
        data = context.get("data") or {}
        state = PipelineDrain._default_state()
        state.update(data)
        state.setdefault("cancelled_pending", [])
        state.setdefault("history", [])
        return state

    @staticmethod
    def _write_state(session_id: str, state: Dict) -> Dict:
        from memory.MemSession import MemSession

        MemSession.replace_module_context(session_id, "pipeline", state)
        MemSession.update_context(
            session_id,
            pipeline_mode=state.get("mode", PipelineDrain.ACTIVE),
            pipeline_reject_new=state.get("reject_new_pipeline", False),
            pipeline_active_run=state.get("active_run_id", ""),
            stable_checkpoint=state.get("last_checkpoint_snapshot", ""),
        )
        return state

    @staticmethod
    def _append_history(state: Dict, event: str, **payload):
        history = state.setdefault("history", [])
        history.append({
            "event": event,
            "at": PipelineDrain._now(),
            **payload,
        })
        if len(history) > 50:
            del history[:-50]

    @staticmethod
    def get_state(session_id: str) -> Dict:
        """读取 Drain 状态。"""
        return PipelineDrain._load_state(session_id)

    @staticmethod
    def can_start_pipeline(session_id: str) -> Tuple[bool, str]:
        """检查是否允许启动新的 Pipeline run。"""
        from memory.MemSession import MemSession

        meta = MemSession.get(session_id)
        context = meta.get("context", {})
        state = PipelineDrain._load_state(session_id)

        if state.get("reject_new_pipeline") or state.get("mode") in {
            PipelineDrain.DRAINING,
            PipelineDrain.CHECKPOINTING,
        }:
            return False, f"Pipeline 正在 Drain，拒绝启动新 run（mode={state.get('mode')}）"

        if state.get("active_run_id"):
            return False, f"已有 Pipeline run 正在执行: {state['active_run_id']}"

        has_pending_change = context.get("pending_requirements", 0) > 0
        waiting_for_change = has_pending_change and not context.get("active_change", False) and (
            context.get("current_work_completed", False)
            or state.get("mode") == PipelineDrain.READY
        )
        if waiting_for_change:
            return False, "等待区有新需求且当前链路已停止扩张，请先处理新需求编排"

        return True, "可以启动 Pipeline run"

    @staticmethod
    def begin_run(session_id: str, run_type: str = "pipeline", source: str = "PipelineRouter") -> str:
        """登记一个已开始的 Pipeline run；Drain 中会拒绝并记录取消项。"""
        from memory.MemSnapshot import MemSnapshot

        can_start, msg = PipelineDrain.can_start_pipeline(session_id)
        if not can_start:
            PipelineDrain.cancel_pending_work(session_id, run_type=run_type, reason=msg, source=source)
            raise PermissionError(msg)

        state = PipelineDrain._load_state(session_id)
        latest = MemSnapshot.latest(session_id)
        run_id = PipelineDrain._new_run_id()
        state.update({
            "mode": PipelineDrain.ACTIVE,
            "reject_new_pipeline": False,
            "active_run_id": run_id,
            "active_run": {
                "id": run_id,
                "type": run_type,
                "source": source,
                "status": "running",
                "started_at": PipelineDrain._now(),
                "base_snapshot": latest.get("id") if latest else "",
                "checkpoint_policy": "finish_running_run_then_checkpoint",
            },
        })
        PipelineDrain._append_history(state, "begin_run", run_id=run_id, run_type=run_type)
        PipelineDrain._write_state(session_id, state)
        return run_id

    @staticmethod
    def request_drain(session_id: str, reason: str = "new_requirement_pending") -> Dict:
        """
        进入 Drain：停止扩张，已开始的 Pipeline run 继续到提交点。

        如果当前没有活跃 run，则立即生成稳定 checkpoint。
        """
        state = PipelineDrain._load_state(session_id)
        state["reject_new_pipeline"] = True
        state["drain_requested_at"] = state.get("drain_requested_at") or PipelineDrain._now()
        state["drain_reason"] = reason
        state["mode"] = PipelineDrain.DRAINING if state.get("active_run_id") else PipelineDrain.CHECKPOINTING
        PipelineDrain._append_history(state, "drain_requested", reason=reason)
        PipelineDrain._write_state(session_id, state)

        if not state.get("active_run_id"):
            return PipelineDrain.create_checkpoint(session_id, reason="drain_idle_checkpoint")
        return state

    @staticmethod
    def cancel_pending_work(
        session_id: str,
        run_type: str = "pipeline",
        reason: str = "drain_requested",
        source: str = "PipelineDrain",
    ) -> Dict:
        """记录未开始工作被取消；不终止已登记的 active run。"""
        state = PipelineDrain._load_state(session_id)
        cancel_id = f"cancel_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
        item = {
            "id": cancel_id,
            "type": run_type,
            "source": source,
            "status": "cancelled",
            "reason": reason,
            "cancelled_at": PipelineDrain._now(),
        }
        state.setdefault("cancelled_pending", []).append(item)
        PipelineDrain._append_history(state, "cancel_pending_work", cancel_id=cancel_id, reason=reason)
        return PipelineDrain._write_state(session_id, state)

    @staticmethod
    def complete_run(
        session_id: str,
        run_id: str,
        success: bool,
        phase: str = "",
        message: str = "",
        files=None,
        test_results=None,
    ) -> Dict:
        """结束 active run；如果 Drain 正在等待该 run，随后创建 checkpoint。"""
        state = PipelineDrain._load_state(session_id)
        if state.get("active_run_id") != run_id:
            raise ValueError(f"Pipeline run 不匹配：当前 {state.get('active_run_id')}，尝试完成 {run_id}")

        active_run = state.get("active_run") or {"id": run_id}
        active_run.update({
            "status": "completed" if success else "failed",
            "success": bool(success),
            "phase": phase,
            "message": message,
            "files": files or [],
            "test_results": test_results or {},
            "completed_at": PipelineDrain._now(),
        })
        state["last_run"] = active_run
        state["active_run_id"] = ""
        state["active_run"] = None
        PipelineDrain._append_history(state, "complete_run", run_id=run_id, success=bool(success))

        if state.get("mode") == PipelineDrain.DRAINING:
            state["mode"] = PipelineDrain.CHECKPOINTING
            state["reject_new_pipeline"] = True
            PipelineDrain._write_state(session_id, state)
            return PipelineDrain.create_checkpoint(session_id, reason="drain_after_pipeline_complete")

        return PipelineDrain._write_state(session_id, state)

    @staticmethod
    def create_checkpoint(session_id: str, reason: str = "manual_checkpoint") -> Dict:
        """创建稳定 checkpoint，快照同时包含 memory 和 output。"""
        from memory.MemSnapshot import MemSnapshot

        state = PipelineDrain._load_state(session_id)
        state["mode"] = PipelineDrain.CHECKPOINTING
        state["reject_new_pipeline"] = True
        PipelineDrain._write_state(session_id, state)

        snapshot_id = MemSnapshot.create(session_id, reason=reason)
        state = PipelineDrain._load_state(session_id)
        state["mode"] = PipelineDrain.READY
        state["reject_new_pipeline"] = False
        state["last_checkpoint_snapshot"] = snapshot_id
        state["checkpointed_at"] = PipelineDrain._now()
        PipelineDrain._append_history(state, "checkpoint", snapshot_id=snapshot_id, reason=reason)
        return PipelineDrain._write_state(session_id, state)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 初版：支持 Drain、取消未开始任务、稳定 checkpoint
# contract: 12_接手文档.md
# next: PipelineRouter 接入
# </YGA_END_ANCHOR>
