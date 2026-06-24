use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

const SKIP_DIRS: &[&str] = &[
    "node_modules",
    ".git",
    "target",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".yga_snapshots",
];

const LARGE_FILE_THRESHOLD: u64 = 500_000; // 500KB

#[derive(Debug, Serialize, Deserialize)]
pub struct HealthReport {
    pub score: u32,
    pub total_files: usize,
    pub issues: Vec<HealthIssue>,
    pub summary: HealthSummary,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct HealthSummary {
    pub todos: usize,
    pub large_files: usize,
    pub empty_files: usize,
    pub duplicate_names: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct HealthIssue {
    pub level: String, // "warning", "info"
    pub category: String,
    pub file: String,
    pub message: String,
}

pub async fn tool_health_check(project_path: String) -> Result<HealthReport, String> {
    let root = Path::new(&project_path);
    if !root.is_dir() {
        return Err(format!("目录不存在: {}", project_path));
    }

    let mut issues = Vec::new();
    let mut total_files = 0usize;
    let mut todos = 0usize;
    let mut large_files = 0usize;
    let mut empty_files = 0usize;
    let mut name_count: HashMap<String, Vec<String>> = HashMap::new();

    let mut stack: Vec<PathBuf> = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let entries = match std::fs::read_dir(&dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();

            if path.is_dir() {
                if !SKIP_DIRS.contains(&name.as_str()) && !name.starts_with('.') {
                    stack.push(path);
                }
                continue;
            }

            total_files += 1;
            let path_str = path.to_string_lossy().to_string();

            // track duplicate names
            name_count
                .entry(name.clone())
                .or_default()
                .push(path_str.clone());

            // check file size
            if let Ok(meta) = std::fs::metadata(&path) {
                if meta.len() == 0 {
                    empty_files += 1;
                    issues.push(HealthIssue {
                        level: "info".into(),
                        category: "empty_file".into(),
                        file: path_str.clone(),
                        message: "空文件".into(),
                    });
                } else if meta.len() > LARGE_FILE_THRESHOLD {
                    large_files += 1;
                    issues.push(HealthIssue {
                        level: "warning".into(),
                        category: "large_file".into(),
                        file: path_str.clone(),
                        message: format!("大文件: {}KB", meta.len() / 1024),
                    });
                }
            }

            // scan for TODO/FIXME in text files
            if is_text_file(&name) {
                if let Ok(content) = std::fs::read_to_string(&path) {
                    for (i, line) in content.lines().enumerate() {
                        let upper = line.to_uppercase();
                        if upper.contains("TODO")
                            || upper.contains("FIXME")
                            || upper.contains("HACK")
                        {
                            todos += 1;
                            issues.push(HealthIssue {
                                level: "info".into(),
                                category: "todo".into(),
                                file: path_str.clone(),
                                message: format!("L{}: {}", i + 1, line.trim()),
                            });
                        }
                    }
                }
            }
        }
    }

    // check duplicate names
    let mut duplicate_names = 0usize;
    for (name, paths) in &name_count {
        if paths.len() > 1 {
            duplicate_names += 1;
            issues.push(HealthIssue {
                level: "warning".into(),
                category: "duplicate_name".into(),
                file: name.clone(),
                message: format!("文件名重复 {} 次: {}", paths.len(), paths.join(", ")),
            });
        }
    }

    // compute score (0~100)
    let mut score = 100u32;
    score = score.saturating_sub((large_files as u32) * 5);
    score = score.saturating_sub((empty_files as u32) * 2);
    score = score.saturating_sub((duplicate_names as u32) * 3);
    score = score.saturating_sub((todos.min(20) as u32) * 1);

    Ok(HealthReport {
        score,
        total_files,
        issues,
        summary: HealthSummary {
            todos,
            large_files,
            empty_files,
            duplicate_names,
        },
    })
}

fn is_text_file(name: &str) -> bool {
    let text_exts = [
        "js", "jsx", "ts", "tsx", "py", "rs", "go", "java", "c", "cpp", "h", "html", "css", "scss",
        "less", "json", "yaml", "yml", "toml", "xml", "md", "txt", "sh", "bat", "ps1", "vue",
        "svelte", "rb", "php", "sql", "graphql", "proto", "env", "ini", "cfg", "conf",
    ];
    if let Some(ext) = name.rsplit('.').next() {
        text_exts.contains(&ext.to_lowercase().as_str())
    } else {
        false
    }
}
