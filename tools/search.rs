use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

// ── 跳过的目录 ──

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
    ".idea",
    ".vscode",
];

fn should_skip(name: &str) -> bool {
    SKIP_DIRS.contains(&name)
}

// ── 内容搜索 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct SearchMatch {
    pub file: String,
    pub line_number: usize,
    pub line_content: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SearchResult {
    pub matches: Vec<SearchMatch>,
    pub total_matches: usize,
    pub files_searched: usize,
    pub truncated: bool,
}

pub async fn tool_search(
    pattern: String,
    search_path: String,
    ignore_case: Option<bool>,
    glob_filter: Option<String>,
    max_results: Option<usize>,
) -> Result<SearchResult, String> {
    let root = Path::new(&search_path);
    if !root.exists() {
        return Err(format!("路径不存在: {}", search_path));
    }

    let case_insensitive = ignore_case.unwrap_or(false);
    let max = max_results.unwrap_or(200);

    let regex = if case_insensitive {
        regex::RegexBuilder::new(&pattern)
            .case_insensitive(true)
            .build()
            .map_err(|e| format!("正则无效: {}", e))?
    } else {
        regex::Regex::new(&pattern).map_err(|e| format!("正则无效: {}", e))?
    };

    let glob_pat = glob_filter
        .as_deref()
        .map(|g| glob::Pattern::new(g).ok())
        .flatten();

    let mut matches = Vec::new();
    let mut files_searched = 0;
    let mut truncated = false;

    if root.is_file() {
        let name = root
            .file_name()
            .map(|name| name.to_string_lossy().to_string())
            .unwrap_or_default();

        if is_likely_binary(&name) {
            return Ok(SearchResult {
                matches,
                total_matches: 0,
                files_searched,
                truncated,
            });
        }

        if let Some(ref pat) = glob_pat {
            if !pat.matches(&name) {
                return Ok(SearchResult {
                    matches,
                    total_matches: 0,
                    files_searched,
                    truncated,
                });
            }
        }

        let content = std::fs::read_to_string(root).map_err(|e| format!("读取失败: {}", e))?;
        files_searched += 1;

        for (i, line) in content.lines().enumerate() {
            if regex.is_match(line) {
                if matches.len() >= max {
                    truncated = true;
                    break;
                }
                matches.push(SearchMatch {
                    file: root.to_string_lossy().to_string(),
                    line_number: i + 1,
                    line_content: line.to_string(),
                });
            }
        }

        let total = matches.len();
        return Ok(SearchResult {
            matches,
            total_matches: total,
            files_searched,
            truncated,
        });
    }

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
                if !should_skip(&name) {
                    stack.push(path);
                }
                continue;
            }

            // glob filter
            if let Some(ref pat) = glob_pat {
                if !pat.matches(&name) {
                    continue;
                }
            }

            // skip binary files (simple heuristic: check extension)
            if is_likely_binary(&name) {
                continue;
            }

            let content = match std::fs::read_to_string(&path) {
                Ok(c) => c,
                Err(_) => continue,
            };
            files_searched += 1;

            for (i, line) in content.lines().enumerate() {
                if regex.is_match(line) {
                    if matches.len() >= max {
                        truncated = true;
                        break;
                    }
                    matches.push(SearchMatch {
                        file: path.to_string_lossy().to_string(),
                        line_number: i + 1,
                        line_content: line.to_string(),
                    });
                }
            }
            if truncated {
                break;
            }
        }
        if truncated {
            break;
        }
    }

    let total = matches.len();
    Ok(SearchResult {
        matches,
        total_matches: total,
        files_searched,
        truncated,
    })
}

// ── Glob 文件查找 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct GlobResult {
    pub files: Vec<String>,
    pub total: usize,
}

pub async fn tool_glob(
    pattern: String,
    search_path: String,
    max_results: Option<usize>,
) -> Result<GlobResult, String> {
    let full_pattern = if Path::new(&pattern).is_absolute() {
        pattern.clone()
    } else {
        format!("{}/{}", search_path.trim_end_matches(['/', '\\']), pattern)
    };

    let max = max_results.unwrap_or(500);
    let mut files = Vec::new();

    for entry in glob::glob(&full_pattern).map_err(|e| format!("glob 模式无效: {}", e))? {
        if let Ok(path) = entry {
            // skip irrelevant dirs
            let path_str = path.to_string_lossy().to_string();
            if SKIP_DIRS
                .iter()
                .any(|d| path_str.contains(&format!("{}{}", std::path::MAIN_SEPARATOR, d)))
            {
                continue;
            }
            files.push(path_str);
            if files.len() >= max {
                break;
            }
        }
    }

    let total = files.len();
    Ok(GlobResult { files, total })
}

// ── 目录树 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct TreeNode {
    pub name: String,
    pub path: String,
    #[serde(rename = "type")]
    pub node_type: String,
    pub size: Option<u64>,
    pub children: Option<Vec<TreeNode>>,
}

pub async fn tool_tree(dir_path: String, max_depth: Option<u32>) -> Result<TreeNode, String> {
    let root = Path::new(&dir_path);
    if !root.is_dir() {
        return Err(format!("目录不存在: {}", dir_path));
    }

    let depth = max_depth.unwrap_or(3);
    Ok(build_tree(root, depth, 0))
}

fn build_tree(path: &Path, max_depth: u32, current_depth: u32) -> TreeNode {
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string_lossy().to_string());

    if path.is_file() {
        let size = std::fs::metadata(path).map(|m| m.len()).ok();
        return TreeNode {
            name,
            path: path.to_string_lossy().to_string(),
            node_type: "file".to_string(),
            size,
            children: None,
        };
    }

    let children = if current_depth < max_depth {
        let mut kids = Vec::new();
        if let Ok(entries) = std::fs::read_dir(path) {
            let mut sorted: Vec<_> = entries.flatten().collect();
            sorted.sort_by(|a, b| {
                let a_dir = a.path().is_dir();
                let b_dir = b.path().is_dir();
                b_dir
                    .cmp(&a_dir)
                    .then_with(|| a.file_name().cmp(&b.file_name()))
            });
            for entry in sorted {
                let entry_name = entry.file_name().to_string_lossy().to_string();
                if should_skip(&entry_name) || entry_name.starts_with('.') {
                    continue;
                }
                kids.push(build_tree(&entry.path(), max_depth, current_depth + 1));
            }
        }
        Some(kids)
    } else {
        None
    };

    TreeNode {
        name,
        path: path.to_string_lossy().to_string(),
        node_type: "directory".to_string(),
        size: None,
        children,
    }
}

fn is_likely_binary(name: &str) -> bool {
    let binary_exts = [
        "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "svg", "mp3", "mp4", "avi", "mov",
        "wav", "flac", "zip", "tar", "gz", "7z", "rar", "exe", "dll", "so", "dylib", "o", "a",
        "woff", "woff2", "ttf", "eot", "otf", "pdf", "doc", "docx", "xls", "xlsx", "lock", "bin",
        "dat",
    ];
    if let Some(ext) = name.rsplit('.').next() {
        binary_exts.contains(&ext.to_lowercase().as_str())
    } else {
        false
    }
}
