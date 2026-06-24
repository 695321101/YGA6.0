use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadResult {
    pub content: String,
    pub total_lines: usize,
    pub hash: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct WriteResult {
    pub success: bool,
    pub bytes_written: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EditResult {
    pub success: bool,
    pub replacements: usize,
    pub new_hash: String,
}

fn compute_hash(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    format!("{:x}", hasher.finalize())
}

pub async fn tool_read_file(
    file_path: String,
    offset: Option<usize>,
    limit: Option<usize>,
) -> Result<ReadResult, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("文件不存在: {}", file_path));
    }

    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;

    let total_lines = content.lines().count();
    let hash = compute_hash(&content);

    let result_content = match (offset, limit) {
        (Some(off), Some(lim)) => {
            let start = off.saturating_sub(1); // 1-indexed
            content
                .lines()
                .skip(start)
                .take(lim)
                .collect::<Vec<_>>()
                .join("\n")
        }
        (Some(off), None) => {
            let start = off.saturating_sub(1);
            content.lines().skip(start).collect::<Vec<_>>().join("\n")
        }
        _ => content,
    };

    Ok(ReadResult {
        content: result_content,
        total_lines,
        hash,
    })
}

pub async fn tool_write_file(file_path: String, content: String) -> Result<WriteResult, String> {
    let path = Path::new(&file_path);

    // auto-create parent directories
    if let Some(parent) = path.parent() {
        if !parent.exists() {
            tokio::fs::create_dir_all(parent)
                .await
                .map_err(|e| format!("创建目录失败: {}", e))?;
        }
    }

    let bytes = content.as_bytes().len();
    tokio::fs::write(path, &content)
        .await
        .map_err(|e| format!("写入失败: {}", e))?;

    Ok(WriteResult {
        success: true,
        bytes_written: bytes,
    })
}

pub async fn tool_edit_file(
    file_path: String,
    old_str: String,
    new_str: String,
    replace_all: Option<bool>,
    last_read_hash: Option<String>,
) -> Result<EditResult, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("文件不存在: {}", file_path));
    }

    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;

    // conflict detection: check hash if provided
    if let Some(expected_hash) = &last_read_hash {
        let current_hash = compute_hash(&content);
        if &current_hash != expected_hash {
            return Err("文件已被外部修改（hash 不匹配），请重新读取后再编辑".to_string());
        }
    }

    let occurrences = content.matches(&old_str).count();
    if occurrences == 0 {
        return Err(format!(
            "未找到匹配的内容: {}",
            if old_str.len() > 80 {
                format!("{}...", &old_str[..80])
            } else {
                old_str
            }
        ));
    }

    let do_all = replace_all.unwrap_or(false);
    if occurrences > 1 && !do_all {
        return Err(format!(
            "找到 {} 处匹配，请使用 replace_all=true 替换全部，或提供更精确的内容",
            occurrences
        ));
    }

    let new_content = if do_all {
        content.replace(&old_str, &new_str)
    } else {
        content.replacen(&old_str, &new_str, 1)
    };

    let new_hash = compute_hash(&new_content);
    tokio::fs::write(path, &new_content)
        .await
        .map_err(|e| format!("写入失败: {}", e))?;

    Ok(EditResult {
        success: true,
        replacements: if do_all { occurrences } else { 1 },
        new_hash,
    })
}
