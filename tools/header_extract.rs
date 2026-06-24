use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

// ── 富文件头数据结构 ──

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileHeader {
    pub file: String,
    pub module: Option<String>,
    pub purpose: Option<String>,
    pub exports: Vec<String>,
    pub deps: Vec<String>,
    pub usage: Option<String>,
    pub extra: HashMap<String, String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ModuleExports {
    pub module: String,
    pub files: Vec<FileHeader>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExtractResult {
    pub file: String,
    pub header: FileHeader,
    pub had_header: bool,
}

// ── 提取单个文件的富文件头 ──

fn get_comment_prefix(ext: &str) -> &'static str {
    match ext {
        "py" => "#",
        "js" | "jsx" | "ts" | "tsx" | "mjs" | "rs" | "go" | "java" | "c" | "cpp" | "h" => "//",
        _ => "#",
    }
}

fn parse_header(content: &str, comment_prefix: &str) -> (FileHeader, bool) {
    let mut file = String::new();
    let mut module = None;
    let mut purpose = None;
    let mut exports = Vec::new();
    let mut deps = Vec::new();
    let mut usage = None;
    let mut extra = HashMap::new();
    let mut had_header = false;
    let mut in_exports = false;

    for line in content.lines() {
        let trimmed = line.trim();

        // stop at first non-comment, non-empty line (= end of header block)
        if !trimmed.is_empty()
            && !trimmed.starts_with(comment_prefix)
            && !trimmed.starts_with("#!/")
        {
            break;
        }

        let stripped = trimmed
            .strip_prefix(comment_prefix)
            .map(|s| s.trim())
            .unwrap_or("");

        if stripped.is_empty() {
            in_exports = false;
            continue;
        }

        // detect header key-value pairs
        if let Some(val) = stripped.strip_prefix("File:") {
            file = val.trim().to_string();
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Module:") {
            module = Some(val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Purpose:") {
            purpose = Some(val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if stripped.starts_with("Exports:") {
            had_header = true;
            in_exports = true;
            // might have inline value: "Exports: func1, func2"
            let val = stripped.strip_prefix("Exports:").unwrap_or("").trim();
            if !val.is_empty() {
                exports.push(val.to_string());
                in_exports = false;
            }
        } else if let Some(val) = stripped.strip_prefix("Deps:") {
            deps.push(val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Usage:") {
            usage = Some(val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Covers:") {
            extra.insert("covers".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("TestCount:") {
            extra.insert("test_count".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Verdict:") {
            extra.insert("verdict".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Issues:") {
            extra.insert("issues".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Type:") {
            extra.insert("type".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Root:") {
            extra.insert("root".to_string(), val.trim().to_string());
            had_header = true;
            in_exports = false;
        } else if in_exports {
            // continuation of exports block (indented lines)
            exports.push(stripped.to_string());
        }
    }

    let header = FileHeader {
        file,
        module,
        purpose,
        exports,
        deps,
        usage,
        extra,
    };

    (header, had_header)
}

// ── 兜底：AI 没写文件头时，从内容中提取基本信息 ──

fn fallback_extract(content: &str, file_path: &str, ext: &str) -> FileHeader {
    let mut exports = Vec::new();
    let mut deps = Vec::new();

    for line in content.lines() {
        let trimmed = line.trim();
        match ext {
            "py" => {
                if (trimmed.starts_with("def ") || trimmed.starts_with("async def "))
                    && !trimmed.starts_with("def _")
                {
                    if trimmed.find('(').is_some() {
                        let after_def = trimmed
                            .strip_prefix("async def ")
                            .or_else(|| trimmed.strip_prefix("def "))
                            .unwrap_or("");
                        if let Some(p) = after_def.find('(') {
                            let fn_name = &after_def[..p];
                            if !fn_name.starts_with('_') {
                                exports.push(format!(
                                    "def {}",
                                    after_def.split(')').next().unwrap_or(fn_name)
                                ));
                            }
                        }
                    }
                }
                if trimmed.starts_with("class ") && !trimmed.starts_with("class _") {
                    let class_part = trimmed.strip_prefix("class ").unwrap_or("");
                    let name = class_part.split(['(', ':']).next().unwrap_or("").trim();
                    if !name.is_empty() {
                        exports.push(format!("class {}", name));
                    }
                }
                if trimmed.starts_with("from ") || trimmed.starts_with("import ") {
                    deps.push(trimmed.to_string());
                }
            }
            "js" | "jsx" | "ts" | "tsx" | "mjs" => {
                if trimmed.starts_with("export ") {
                    let rest = trimmed
                        .strip_prefix("export ")
                        .unwrap_or("")
                        .trim_start_matches("default ");
                    if let Some(sig) = rest.split('{').next() {
                        let short = sig.trim();
                        if !short.is_empty() && short.len() < 120 {
                            exports.push(short.to_string());
                        }
                    }
                }
                if trimmed.starts_with("import ") {
                    deps.push(trimmed.to_string());
                }
            }
            "rs" => {
                if trimmed.starts_with("pub fn ")
                    || trimmed.starts_with("pub async fn ")
                    || trimmed.starts_with("pub struct ")
                    || trimmed.starts_with("pub enum ")
                {
                    let sig = trimmed.split('{').next().unwrap_or(trimmed).trim();
                    if sig.len() < 150 {
                        exports.push(sig.to_string());
                    }
                }
                if trimmed.starts_with("use ") {
                    deps.push(trimmed.to_string());
                }
            }
            "go" => {
                if trimmed.starts_with("func ") {
                    let sig = trimmed.split('{').next().unwrap_or(trimmed).trim();
                    // only exported (PascalCase) functions
                    let name_start = if sig.contains(") ") {
                        sig.find(") ").map(|i| i + 2)
                    } else {
                        Some(5) // after "func "
                    };
                    if let Some(start) = name_start {
                        if sig
                            .get(start..start + 1)
                            .map(|c| {
                                c.chars()
                                    .next()
                                    .map(|ch| ch.is_uppercase())
                                    .unwrap_or(false)
                            })
                            .unwrap_or(false)
                        {
                            exports.push(sig.to_string());
                        }
                    }
                }
            }
            _ => {}
        }
    }

    // deduplicate deps (only keep unique import statements)
    deps.sort();
    deps.dedup();

    FileHeader {
        file: file_path.to_string(),
        module: None,
        purpose: None,
        exports,
        deps,
        usage: None,
        extra: HashMap::new(),
    }
}

// ── IPC 命令 ──

/// 提取单个文件的富文件头
pub async fn tool_extract_header(file_path: String) -> Result<ExtractResult, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("文件不存在: {}", file_path));
    }

    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;

    let ext = path
        .extension()
        .map(|e| e.to_string_lossy().to_string())
        .unwrap_or_default();

    let prefix = get_comment_prefix(&ext);
    let (mut header, had_header) = parse_header(&content, prefix);

    // 兜底：没有文件头时从内容中提取
    if !had_header {
        header = fallback_extract(&content, &file_path, &ext);
    }

    // 确保 file 字段有值
    if header.file.is_empty() {
        header.file = file_path.clone();
    }

    Ok(ExtractResult {
        file: file_path,
        header,
        had_header,
    })
}

/// 聚合一个模块目录下所有文件的文件头 → exports.json
pub async fn tool_aggregate_headers(
    module_path: String,
    module_name: String,
    output_path: Option<String>,
) -> Result<ModuleExports, String> {
    let root = Path::new(&module_path);
    if !root.is_dir() {
        return Err(format!("目录不存在: {}", module_path));
    }

    let source_exts = ["py", "js", "jsx", "ts", "tsx", "mjs", "rs", "go", "java"];
    let skip_dirs = [
        "node_modules",
        ".git",
        "target",
        "__pycache__",
        ".venv",
        "dist",
        "build",
        "tests",
        "__tests__",
        "test",
    ];

    let mut files = Vec::new();
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
                if !skip_dirs.contains(&name.as_str()) && !name.starts_with('.') {
                    stack.push(path);
                }
                continue;
            }

            let ext = path
                .extension()
                .map(|e| e.to_string_lossy().to_string())
                .unwrap_or_default();

            if !source_exts.contains(&ext.as_str()) {
                continue;
            }

            let file_str = path.to_string_lossy().to_string();
            match tool_extract_header(file_str).await {
                Ok(result) => {
                    // 设置相对路径
                    let mut header = result.header;
                    header.file = path
                        .strip_prefix(root)
                        .unwrap_or(&path)
                        .to_string_lossy()
                        .replace('\\', "/");
                    files.push(header);
                }
                Err(_) => continue,
            }
        }
    }

    let exports = ModuleExports {
        module: module_name,
        files,
    };

    // 写入 output_path（如果指定）
    if let Some(out) = output_path {
        let json = serde_json::to_string_pretty(&exports).map_err(|e| e.to_string())?;
        tokio::fs::write(&out, &json)
            .await
            .map_err(|e| format!("写入失败: {}", e))?;
    }

    Ok(exports)
}
