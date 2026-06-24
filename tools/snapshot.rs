use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

const SNAPSHOT_DIR: &str = ".yga_snapshots";
const MAX_VERSIONS: usize = 20;

#[derive(Debug, Serialize, Deserialize)]
pub struct SnapshotResult {
    pub success: bool,
    pub snapshot_id: String,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SnapshotEntry {
    pub id: String,
    pub file_path: String,
    pub reason: String,
    pub timestamp: String,
    pub size: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SnapshotListResult {
    pub file_path: String,
    pub snapshots: Vec<SnapshotEntry>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RestoreResult {
    pub success: bool,
    pub restored_from: String,
    pub backup_of_current: String,
}

fn snapshot_dir(project_path: &Path, file_path: &str) -> PathBuf {
    let mut hasher = Sha256::new();
    hasher.update(file_path.as_bytes());
    let hash = format!("{:x}", hasher.finalize());
    let short = &hash[..12];
    project_path.join(SNAPSHOT_DIR).join(short)
}

fn timestamp_id() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}", now.as_millis())
}

fn format_timestamp(ts: &str) -> String {
    // simple: return the raw timestamp as-is for now
    ts.to_string()
}

pub async fn tool_snapshot_create(
    project_path: String,
    file_path: String,
    reason: Option<String>,
) -> Result<SnapshotResult, String> {
    let abs_file = Path::new(&file_path);
    if !abs_file.exists() {
        return Err(format!("文件不存在: {}", file_path));
    }

    let snap_dir = snapshot_dir(Path::new(&project_path), &file_path);
    std::fs::create_dir_all(&snap_dir).map_err(|e| format!("创建快照目录失败: {}", e))?;

    let ts = timestamp_id();
    let ext = abs_file
        .extension()
        .map(|e| e.to_string_lossy().to_string())
        .unwrap_or_default();
    let snap_name = if ext.is_empty() {
        format!("{}.snap", ts)
    } else {
        format!("{}.{}.snap", ts, ext)
    };
    let snap_path = snap_dir.join(&snap_name);

    // copy file to snapshot
    std::fs::copy(abs_file, &snap_path).map_err(|e| format!("快照保存失败: {}", e))?;

    // write metadata
    let meta = serde_json::json!({
        "file_path": file_path,
        "reason": reason.as_deref().unwrap_or("auto"),
        "timestamp": &ts,
    });
    let meta_path = snap_dir.join(format!("{}.meta.json", ts));
    std::fs::write(&meta_path, serde_json::to_string_pretty(&meta).unwrap())
        .map_err(|e| format!("元数据写入失败: {}", e))?;

    // enforce max versions: remove oldest if exceeding
    cleanup_old_snapshots(&snap_dir);

    Ok(SnapshotResult {
        success: true,
        snapshot_id: ts,
        message: "快照已保存".to_string(),
    })
}

pub async fn tool_snapshot_list(
    project_path: String,
    file_path: String,
) -> Result<SnapshotListResult, String> {
    let snap_dir = snapshot_dir(Path::new(&project_path), &file_path);
    if !snap_dir.exists() {
        return Ok(SnapshotListResult {
            file_path,
            snapshots: Vec::new(),
        });
    }

    let mut entries = Vec::new();
    for entry in std::fs::read_dir(&snap_dir)
        .map_err(|e| e.to_string())?
        .flatten()
    {
        let name = entry.file_name().to_string_lossy().to_string();
        if name.ends_with(".meta.json") {
            if let Ok(content) = std::fs::read_to_string(entry.path()) {
                if let Ok(meta) = serde_json::from_str::<serde_json::Value>(&content) {
                    let ts = meta["timestamp"].as_str().unwrap_or("").to_string();
                    let reason = meta["reason"].as_str().unwrap_or("").to_string();
                    let fp = meta["file_path"].as_str().unwrap_or("").to_string();

                    // find corresponding snap file size
                    let size = std::fs::read_dir(&snap_dir)
                        .ok()
                        .and_then(|rd| {
                            rd.flatten().find(|e| {
                                let n = e.file_name().to_string_lossy().to_string();
                                n.starts_with(&ts) && n.ends_with(".snap")
                            })
                        })
                        .and_then(|e| e.metadata().ok())
                        .map(|m| m.len())
                        .unwrap_or(0);

                    entries.push(SnapshotEntry {
                        id: ts.clone(),
                        file_path: fp,
                        reason,
                        timestamp: format_timestamp(&ts),
                        size,
                    });
                }
            }
        }
    }

    entries.sort_by(|a, b| b.id.cmp(&a.id)); // newest first

    Ok(SnapshotListResult {
        file_path,
        snapshots: entries,
    })
}

pub async fn tool_snapshot_restore(
    project_path: String,
    file_path: String,
    snapshot_id: String,
) -> Result<RestoreResult, String> {
    let snap_dir = snapshot_dir(Path::new(&project_path), &file_path);
    if !snap_dir.exists() {
        return Err("无快照记录".to_string());
    }

    // find the snapshot file
    let snap_file = std::fs::read_dir(&snap_dir)
        .map_err(|e| e.to_string())?
        .flatten()
        .find(|e| {
            let n = e.file_name().to_string_lossy().to_string();
            n.starts_with(&snapshot_id) && n.ends_with(".snap")
        })
        .ok_or("快照文件未找到")?;

    let abs_file = Path::new(&file_path);

    // backup current file before restoring
    let backup_id = timestamp_id();
    if abs_file.exists() {
        let _ = tool_snapshot_create(
            project_path.clone(),
            file_path.clone(),
            Some("restore-backup".to_string()),
        )
        .await;
    }

    // restore
    std::fs::copy(snap_file.path(), abs_file).map_err(|e| format!("恢复失败: {}", e))?;

    Ok(RestoreResult {
        success: true,
        restored_from: snapshot_id,
        backup_of_current: backup_id,
    })
}

fn cleanup_old_snapshots(snap_dir: &Path) {
    let mut metas: Vec<(String, PathBuf)> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(snap_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.ends_with(".meta.json") {
                let ts = name.trim_end_matches(".meta.json").to_string();
                metas.push((ts, entry.path()));
            }
        }
    }

    if metas.len() <= MAX_VERSIONS {
        return;
    }

    metas.sort_by(|a, b| a.0.cmp(&b.0)); // oldest first
    let to_remove = metas.len() - MAX_VERSIONS;
    for (ts, meta_path) in metas.iter().take(to_remove) {
        let _ = std::fs::remove_file(meta_path);
        // also remove the corresponding .snap file
        if let Ok(entries) = std::fs::read_dir(snap_dir) {
            for entry in entries.flatten() {
                let n = entry.file_name().to_string_lossy().to_string();
                if n.starts_with(ts) && n.ends_with(".snap") {
                    let _ = std::fs::remove_file(entry.path());
                }
            }
        }
    }
}
