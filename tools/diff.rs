use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct DiffHunk {
    pub old_start: usize,
    pub old_count: usize,
    pub new_start: usize,
    pub new_count: usize,
    pub lines: Vec<DiffLine>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DiffLine {
    pub tag: String, // "equal", "insert", "delete"
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DiffResult {
    pub hunks: Vec<DiffHunk>,
    pub additions: usize,
    pub deletions: usize,
    pub is_identical: bool,
}

pub async fn tool_diff(file_a: String, file_b: String) -> Result<DiffResult, String> {
    let path_a = Path::new(&file_a);
    let path_b = Path::new(&file_b);

    if !path_a.exists() {
        return Err(format!("文件不存在: {}", file_a));
    }
    if !path_b.exists() {
        return Err(format!("文件不存在: {}", file_b));
    }

    let content_a = tokio::fs::read_to_string(path_a)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;
    let content_b = tokio::fs::read_to_string(path_b)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;

    Ok(compute_diff(&content_a, &content_b))
}

/// Compute unified diff between two strings
fn compute_diff(old: &str, new: &str) -> DiffResult {
    let old_lines: Vec<&str> = old.lines().collect();
    let new_lines: Vec<&str> = new.lines().collect();

    if old_lines == new_lines {
        return DiffResult {
            hunks: Vec::new(),
            additions: 0,
            deletions: 0,
            is_identical: true,
        };
    }

    // Simple LCS-based diff
    let mut hunks = Vec::new();
    let mut additions = 0;
    let mut deletions = 0;

    let lcs = lcs_table(&old_lines, &new_lines);
    let diff_ops = backtrack_diff(&lcs, &old_lines, &new_lines);

    // Group diff ops into hunks (context of 3 lines)
    let context = 3;
    let mut current_lines: Vec<DiffLine> = Vec::new();
    let mut old_pos = 0usize;
    let mut new_pos = 0usize;
    let mut hunk_old_start = 0usize;
    let mut hunk_new_start = 0usize;
    let mut in_hunk = false;
    let mut trailing_context = 0usize;

    for op in &diff_ops {
        match op {
            DiffOp::Equal(line) => {
                if in_hunk {
                    trailing_context += 1;
                    current_lines.push(DiffLine {
                        tag: "equal".to_string(),
                        content: line.to_string(),
                    });
                    if trailing_context >= context {
                        // close hunk
                        let old_count = current_lines.iter().filter(|l| l.tag != "insert").count();
                        let new_count = current_lines.iter().filter(|l| l.tag != "delete").count();
                        hunks.push(DiffHunk {
                            old_start: hunk_old_start + 1,
                            old_count,
                            new_start: hunk_new_start + 1,
                            new_count,
                            lines: std::mem::take(&mut current_lines),
                        });
                        in_hunk = false;
                    }
                }
                old_pos += 1;
                new_pos += 1;
            }
            DiffOp::Insert(line) => {
                if !in_hunk {
                    in_hunk = true;
                    hunk_old_start = old_pos.saturating_sub(context);
                    hunk_new_start = new_pos.saturating_sub(context);
                    // add leading context
                    let start = old_pos.saturating_sub(context);
                    for i in start..old_pos {
                        if i < old_lines.len() {
                            current_lines.push(DiffLine {
                                tag: "equal".to_string(),
                                content: old_lines[i].to_string(),
                            });
                        }
                    }
                }
                trailing_context = 0;
                current_lines.push(DiffLine {
                    tag: "insert".to_string(),
                    content: line.to_string(),
                });
                additions += 1;
                new_pos += 1;
            }
            DiffOp::Delete(line) => {
                if !in_hunk {
                    in_hunk = true;
                    hunk_old_start = old_pos.saturating_sub(context);
                    hunk_new_start = new_pos.saturating_sub(context);
                    let start = old_pos.saturating_sub(context);
                    for i in start..old_pos {
                        if i < old_lines.len() {
                            current_lines.push(DiffLine {
                                tag: "equal".to_string(),
                                content: old_lines[i].to_string(),
                            });
                        }
                    }
                }
                trailing_context = 0;
                current_lines.push(DiffLine {
                    tag: "delete".to_string(),
                    content: line.to_string(),
                });
                deletions += 1;
                old_pos += 1;
            }
        }
    }

    // flush remaining hunk
    if in_hunk && !current_lines.is_empty() {
        let old_count = current_lines.iter().filter(|l| l.tag != "insert").count();
        let new_count = current_lines.iter().filter(|l| l.tag != "delete").count();
        hunks.push(DiffHunk {
            old_start: hunk_old_start + 1,
            old_count,
            new_start: hunk_new_start + 1,
            new_count,
            lines: current_lines,
        });
    }

    DiffResult {
        hunks,
        additions,
        deletions,
        is_identical: false,
    }
}

enum DiffOp<'a> {
    Equal(&'a str),
    Insert(&'a str),
    Delete(&'a str),
}

fn lcs_table(old: &[&str], new: &[&str]) -> Vec<Vec<usize>> {
    let m = old.len();
    let n = new.len();
    let mut table = vec![vec![0usize; n + 1]; m + 1];
    for i in 1..=m {
        for j in 1..=n {
            if old[i - 1] == new[j - 1] {
                table[i][j] = table[i - 1][j - 1] + 1;
            } else {
                table[i][j] = table[i - 1][j].max(table[i][j - 1]);
            }
        }
    }
    table
}

fn backtrack_diff<'a>(table: &[Vec<usize>], old: &[&'a str], new: &[&'a str]) -> Vec<DiffOp<'a>> {
    let mut ops = Vec::new();
    let mut i = old.len();
    let mut j = new.len();

    while i > 0 || j > 0 {
        if i > 0 && j > 0 && old[i - 1] == new[j - 1] {
            ops.push(DiffOp::Equal(old[i - 1]));
            i -= 1;
            j -= 1;
        } else if j > 0 && (i == 0 || table[i][j - 1] >= table[i - 1][j]) {
            ops.push(DiffOp::Insert(new[j - 1]));
            j -= 1;
        } else if i > 0 {
            ops.push(DiffOp::Delete(old[i - 1]));
            i -= 1;
        }
    }

    ops.reverse();
    ops
}
