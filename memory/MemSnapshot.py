# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: memory
file: memory/MemSnapshot.py
responsibility: Session 快照管理
exports: MemSnapshot
authority: memory/index.md
</YGA_FILE_ANCHOR>
"""
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


class MemSnapshot:
    """轻量快照：保存当前记忆区事实和生成物索引，供后续变更追溯。"""

    SNAPSHOT_DIR = "snapshots"

    @staticmethod
    def _session_dir(session_id: str) -> Path:
        return Path(__file__).parent.parent / "memory" / "sessions" / session_id

    @staticmethod
    def _output_dir(session_id: str) -> Path:
        return Path(__file__).parent.parent / "output" / session_id

    @staticmethod
    def _manifest_file(session_id: str) -> Path:
        return MemSnapshot._session_dir(session_id) / MemSnapshot.SNAPSHOT_DIR / "manifest.yaml"

    @staticmethod
    def _snapshot_id() -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"snap_{stamp}"

    @staticmethod
    def _load_manifest(session_id: str) -> Dict:
        manifest_file = MemSnapshot._manifest_file(session_id)
        if not manifest_file.exists():
            return {"snapshots": []}
        with open(manifest_file, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f) or {"snapshots": []}

    @staticmethod
    def _write_manifest(session_id: str, manifest: Dict):
        manifest_file = MemSnapshot._manifest_file(session_id)
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_file, "w", encoding="utf-8-sig") as f:
            yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def _sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _iter_snapshot_files(session_id: str) -> List[Tuple[str, Path]]:
        session_dir = MemSnapshot._session_dir(session_id)
        output_dir = MemSnapshot._output_dir(session_id)
        files: List[Tuple[str, Path]] = []

        for path in sorted(session_dir.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(session_dir)
            if rel_path.parts and rel_path.parts[0] == MemSnapshot.SNAPSHOT_DIR:
                continue
            files.append((str(rel_path).replace("\\", "/"), path))

        if output_dir.exists():
            for path in sorted(output_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel_path = path.relative_to(output_dir)
                snapshot_rel = Path("output") / rel_path
                files.append((str(snapshot_rel).replace("\\", "/"), path))

        return files

    @staticmethod
    def latest(session_id: str) -> Optional[Dict]:
        """读取最新快照摘要。"""
        snapshots = MemSnapshot._load_manifest(session_id).get("snapshots", [])
        return snapshots[-1] if snapshots else None

    @staticmethod
    def list(session_id: str) -> List[Dict]:
        """列出快照摘要。"""
        return MemSnapshot._load_manifest(session_id).get("snapshots", [])

    @staticmethod
    def create(session_id: str, reason: str = "manual") -> str:
        """创建一个类似 git commit 的只读快照。"""
        session_dir = MemSnapshot._session_dir(session_id)
        if not session_dir.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        snapshot_id = MemSnapshot._snapshot_id()
        snapshot_dir = session_dir / MemSnapshot.SNAPSHOT_DIR / snapshot_id
        files_dir = snapshot_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        manifest = MemSnapshot._load_manifest(session_id)
        parent = manifest.get("snapshots", [])[-1] if manifest.get("snapshots") else None
        files_meta = []

        for rel_path, source in MemSnapshot._iter_snapshot_files(session_id):
            dest = files_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            files_meta.append({
                "path": rel_path,
                "sha256": MemSnapshot._sha256(source),
                "bytes": source.stat().st_size,
            })

        meta = {}
        meta_file = session_dir / "meta.yaml"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8-sig") as f:
                meta = yaml.safe_load(f) or {}

        session_meta = meta.get("session", {})
        snapshot_meta = {
            "id": snapshot_id,
            "parent": parent.get("id") if parent else None,
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "reason": reason,
            "phase": session_meta.get("phase"),
            "phase_status": session_meta.get("phase_status"),
            "file_count": len(files_meta),
            "files": files_meta,
        }

        with open(snapshot_dir / "snapshot.yaml", "w", encoding="utf-8-sig") as f:
            yaml.dump(snapshot_meta, f, allow_unicode=True, default_flow_style=False)

        manifest.setdefault("snapshots", []).append({
            "id": snapshot_id,
            "parent": snapshot_meta["parent"],
            "created_at": snapshot_meta["created_at"],
            "reason": reason,
            "phase": snapshot_meta["phase"],
            "phase_status": snapshot_meta["phase_status"],
            "file_count": snapshot_meta["file_count"],
        })
        MemSnapshot._write_manifest(session_id, manifest)
        return snapshot_id

    @staticmethod
    def has_completion_snapshot(session_id: str) -> bool:
        """确认当前 session 是否已有交付完成快照。"""
        latest = MemSnapshot.latest(session_id)
        return bool(latest and latest.get("phase") == "phase_6" and latest.get("phase_status") == "completed")


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 初版：支持 session 快照与 manifest
# contract: memory/index.md
# next: MemRouter
# </YGA_END_ANCHOR>
