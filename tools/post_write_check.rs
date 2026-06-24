use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::Path;

// ── 检测结果 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct PostWriteReport {
    pub file: String,
    pub passed: bool,
    pub checks: Vec<CheckItem>,
    pub header_issues: Vec<String>,
    pub tail_issues: Vec<String>,
    pub cross_issues: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CheckItem {
    pub name: String,
    pub passed: bool,
    pub level: String,
    pub message: String,
}

// ── 文件头尾解析结构（简化版，从注释中提取） ──

#[derive(Debug, Default)]
struct ParsedHeader {
    file: String,
    module: String,
    purpose: String,
    exports: Vec<String>,
    deps: Vec<String>,
    usage: String,
    related_contracts: Vec<String>,
    constraints: Vec<String>,
    do_not: Vec<String>,
}

#[derive(Debug, Default)]
struct ParsedTail {
    test_functions: Vec<String>,
    mock_deps: Vec<String>,
    edge_cases: Vec<String>,
    contracts: Vec<String>,
    serialization_notes: Vec<String>,
    env_sensitive: Vec<String>,
    error_types: Vec<String>,
    concurrency_notes: Vec<String>,
}

fn get_comment_prefix(ext: &str) -> &'static str {
    match ext {
        "py" => "#",
        "js" | "jsx" | "ts" | "tsx" | "mjs" | "rs" | "go" | "java" | "c" | "cpp" | "h" => "//",
        _ => "#",
    }
}

fn parse_list_field(value: &str) -> Vec<String> {
    let trimmed = value.trim();
    if trimmed.starts_with('[') && trimmed.ends_with(']') {
        let inner = &trimmed[1..trimmed.len() - 1];
        inner
            .split(',')
            .map(|s| s.trim().trim_matches('"').trim_matches('\'').to_string())
            .filter(|s| !s.is_empty())
            .collect()
    } else if !trimmed.is_empty() {
        vec![trimmed.to_string()]
    } else {
        Vec::new()
    }
}

fn parse_header_from_content(content: &str, prefix: &str) -> ParsedHeader {
    let mut h = ParsedHeader::default();
    let mut in_exports = false;
    let mut in_header = false;
    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.contains("=== File Header ===") {
            in_header = true;
            continue;
        }
        if in_header && trimmed.contains("=== Test Hints ===") {
            break;
        }
        if in_header && !trimmed.starts_with(prefix) && !trimmed.is_empty() {
            break;
        }

        if !in_header {
            if trimmed.starts_with(&format!("{} File:", prefix)) {
                in_header = true;
            } else {
                continue;
            }
        }

        let stripped = trimmed.strip_prefix(prefix).map(|s| s.trim()).unwrap_or("");

        if stripped.is_empty() {
            in_exports = false;
            continue;
        }

        if let Some(val) = stripped.strip_prefix("File:") {
            h.file = val.trim().to_string();
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Module:") {
            h.module = val.trim().to_string();
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Purpose:") {
            h.purpose = val.trim().to_string();
            in_exports = false;
        } else if stripped.starts_with("Exports:") {
            in_exports = true;
            let val = stripped.strip_prefix("Exports:").unwrap_or("").trim();
            if !val.is_empty() {
                h.exports.push(val.to_string());
                in_exports = false;
            }
        } else if let Some(val) = stripped.strip_prefix("Deps:") {
            h.deps = parse_list_field(val);
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Usage:") {
            h.usage = val.trim().to_string();
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Related_contracts:") {
            h.related_contracts = parse_list_field(val);
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Constraints:") {
            h.constraints = parse_list_field(val);
            in_exports = false;
        } else if let Some(val) = stripped.strip_prefix("Do_not:") {
            h.do_not = parse_list_field(val);
            in_exports = false;
        } else if in_exports {
            h.exports.push(stripped.to_string());
        }
    }
    h
}

fn parse_tail_from_content(content: &str, prefix: &str) -> ParsedTail {
    let mut t = ParsedTail::default();
    let mut in_tail = false;
    let mut current_field: Option<String> = None;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.contains("=== Test Hints ===") || trimmed.contains("--- Test Hints ---") {
            in_tail = true;
            continue;
        }
        if !in_tail {
            continue;
        }

        let stripped = trimmed.strip_prefix(prefix).map(|s| s.trim()).unwrap_or("");

        if stripped.is_empty() {
            continue;
        }

        if let Some(val) = stripped.strip_prefix("test_functions:") {
            t.test_functions = parse_list_field(val);
            current_field = if t.test_functions.is_empty() {
                Some("test_functions".to_string())
            } else {
                None
            };
        } else if let Some(val) = stripped.strip_prefix("mock_deps:") {
            t.mock_deps = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("edge_cases:") {
            t.edge_cases = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("contracts:") {
            t.contracts = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("serialization_notes:") {
            t.serialization_notes = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("env_sensitive:") {
            t.env_sensitive = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("error_types:") {
            t.error_types = parse_list_field(val);
            current_field = None;
        } else if let Some(val) = stripped.strip_prefix("concurrency_notes:") {
            t.concurrency_notes = parse_list_field(val);
            current_field = None;
        } else if stripped.starts_with("- ") {
            if let Some(ref field) = current_field {
                let item = stripped.strip_prefix("- ").unwrap_or(stripped).to_string();
                match field.as_str() {
                    "test_functions" => t.test_functions.push(item),
                    _ => {}
                }
            }
        }
    }
    t
}

// ── 提取代码中的实际信息 ──

fn extract_actual_exports(content: &str, ext: &str) -> Vec<String> {
    let mut exports = Vec::new();
    for line in content.lines() {
        let trimmed = line.trim();
        match ext {
            "py" => {
                if (trimmed.starts_with("def ") || trimmed.starts_with("async def "))
                    && !trimmed.starts_with("def _")
                {
                    let after = trimmed
                        .strip_prefix("async def ")
                        .or_else(|| trimmed.strip_prefix("def "))
                        .unwrap_or("");
                    if let Some(p) = after.find('(') {
                        exports.push(after[..p].to_string());
                    }
                }
                if trimmed.starts_with("class ") && !trimmed.starts_with("class _") {
                    let rest = trimmed.strip_prefix("class ").unwrap_or("");
                    let name = rest.split(['(', ':']).next().unwrap_or("").trim();
                    if !name.is_empty() {
                        exports.push(name.to_string());
                    }
                }
            }
            "js" | "jsx" | "ts" | "tsx" | "mjs" => {
                if trimmed.starts_with("export ") {
                    let rest = trimmed
                        .strip_prefix("export ")
                        .unwrap_or("")
                        .trim_start_matches("default ")
                        .trim_start_matches("async ");
                    if rest.starts_with("function ") {
                        let after = rest.strip_prefix("function ").unwrap_or("");
                        if let Some(p) = after.find('(') {
                            exports.push(after[..p].trim().to_string());
                        }
                    } else if rest.starts_with("class ") {
                        let after = rest.strip_prefix("class ").unwrap_or("");
                        let name = after.split([' ', '{', '(']).next().unwrap_or("").trim();
                        if !name.is_empty() {
                            exports.push(name.to_string());
                        }
                    } else if rest.starts_with("const ") || rest.starts_with("let ") {
                        let after = rest.trim_start_matches("const ").trim_start_matches("let ");
                        if let Some(eq) = after.find('=') {
                            exports.push(after[..eq].trim().to_string());
                        }
                    }
                }
            }
            "rs" => {
                if trimmed.starts_with("pub fn ") || trimmed.starts_with("pub async fn ") {
                    let after = trimmed
                        .strip_prefix("pub async fn ")
                        .or_else(|| trimmed.strip_prefix("pub fn "))
                        .unwrap_or("");
                    if let Some(p) = after.find('(') {
                        exports.push(after[..p].trim().to_string());
                    }
                }
                if trimmed.starts_with("pub struct ") {
                    let after = trimmed.strip_prefix("pub struct ").unwrap_or("");
                    let name = after.split([' ', '{', '(']).next().unwrap_or("").trim();
                    if !name.is_empty() {
                        exports.push(name.to_string());
                    }
                }
                if trimmed.starts_with("pub enum ") {
                    let after = trimmed.strip_prefix("pub enum ").unwrap_or("");
                    let name = after.split([' ', '{']).next().unwrap_or("").trim();
                    if !name.is_empty() {
                        exports.push(name.to_string());
                    }
                }
            }
            "go" => {
                if trimmed.starts_with("func ") {
                    let after = trimmed.strip_prefix("func ").unwrap_or("");
                    let start = if after.starts_with('(') {
                        after.find(')').map(|i| i + 1).unwrap_or(0)
                    } else {
                        0
                    };
                    let rest = after[start..].trim();
                    if let Some(p) = rest.find('(') {
                        let name = rest[..p].trim();
                        if name
                            .chars()
                            .next()
                            .map(|c| c.is_uppercase())
                            .unwrap_or(false)
                        {
                            exports.push(name.to_string());
                        }
                    }
                }
                if trimmed.starts_with("type ") && trimmed.contains("struct") {
                    let after = trimmed.strip_prefix("type ").unwrap_or("");
                    let name = after.split_whitespace().next().unwrap_or("");
                    if !name.is_empty() {
                        exports.push(name.to_string());
                    }
                }
            }
            _ => {}
        }
    }
    exports
}

fn extract_actual_imports(content: &str, ext: &str) -> Vec<String> {
    let mut imports = Vec::new();
    for line in content.lines() {
        let trimmed = line.trim();
        // skip header/tail comments
        if trimmed.starts_with('#')
            && (trimmed.contains("===") || trimmed.contains("---") || trimmed.contains(':'))
        {
            continue;
        }
        match ext {
            "py" => {
                if trimmed.starts_with("from ")
                    || (trimmed.starts_with("import ") && !trimmed.contains("# "))
                {
                    imports.push(trimmed.to_string());
                }
            }
            "js" | "jsx" | "ts" | "tsx" | "mjs" => {
                if trimmed.starts_with("import ") {
                    imports.push(trimmed.to_string());
                }
            }
            "rs" => {
                if trimmed.starts_with("use ") {
                    imports.push(trimmed.to_string());
                }
            }
            "go" => {
                if trimmed.starts_with("import ")
                    || (trimmed.starts_with('"') && trimmed.ends_with('"'))
                {
                    imports.push(trimmed.to_string());
                }
            }
            _ => {}
        }
    }
    imports
}

fn content_contains_any(content: &str, keywords: &[&str]) -> Vec<String> {
    let mut found = Vec::new();
    for kw in keywords {
        if content.contains(kw) {
            found.push(kw.to_string());
        }
    }
    found
}

// ── IPC 命令 ──

pub async fn tool_post_write_check(
    file_path: String,
    _exports_json_path: Option<String>,
) -> Result<PostWriteReport, String> {
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
    let header = parse_header_from_content(&content, prefix);
    let tail = parse_tail_from_content(&content, prefix);
    let actual_exports = extract_actual_exports(&content, &ext);
    let _actual_imports = extract_actual_imports(&content, &ext);

    let mut checks = Vec::new();
    let mut header_issues = Vec::new();
    let mut tail_issues = Vec::new();
    let mut cross_issues = Vec::new();

    // ── 文件头存在性 ──
    let has_header = !header.file.is_empty() || !header.exports.is_empty();
    checks.push(CheckItem {
        name: "header_exists".to_string(),
        passed: has_header,
        level: "hard".to_string(),
        message: if has_header {
            "文件头存在".to_string()
        } else {
            "缺少文件头".to_string()
        },
    });

    // ── 文件尾存在性 ──
    let has_tail = !tail.test_functions.is_empty();
    checks.push(CheckItem {
        name: "tail_exists".to_string(),
        passed: has_tail,
        level: "soft".to_string(),
        message: if has_tail {
            "测试提示存在".to_string()
        } else {
            "缺少 Test Hints".to_string()
        },
    });

    // ── Exports 一致性：文件头声明 vs 代码实际导出 ──
    if has_header && !header.exports.is_empty() {
        let header_names: HashSet<String> = header
            .exports
            .iter()
            .filter_map(|e| {
                // extract name from signatures like "class Settings(BaseSettings)" or "def get_settings() -> Settings"
                let s = e
                    .trim()
                    .trim_start_matches("class ")
                    .trim_start_matches("def ")
                    .trim_start_matches("async def ")
                    .trim_start_matches("function ")
                    .trim_start_matches("pub fn ")
                    .trim_start_matches("pub async fn ")
                    .trim_start_matches("pub struct ")
                    .trim_start_matches("pub enum ")
                    .trim_start_matches("func ");
                s.split(['(', ' ', '<', ':'])
                    .next()
                    .map(|n| n.trim().to_string())
            })
            .filter(|n| !n.is_empty())
            .collect();

        let actual_set: HashSet<String> = actual_exports.iter().cloned().collect();

        // declared but not found in code
        for name in &header_names {
            if !actual_set.contains(name) {
                header_issues.push(format!("文件头声明了 '{}' 但代码中未找到", name));
            }
        }

        // found in code but not declared (potential hallucination)
        for name in &actual_set {
            if !header_names.contains(name) {
                header_issues.push(format!("代码中有 '{}' 但文件头未声明（可能是幻觉）", name));
            }
        }

        let exports_match = header_issues.is_empty();
        checks.push(CheckItem {
            name: "exports_consistency".to_string(),
            passed: exports_match,
            level: "hard".to_string(),
            message: if exports_match {
                "Exports 与代码一致".to_string()
            } else {
                format!("{} 个不一致", header_issues.len())
            },
        });
    }

    // ── Constraints 检测 ──
    for constraint in &header.constraints {
        let lower = constraint.to_lowercase();
        let violated = if lower.contains("sync only") || lower.contains("must be sync") {
            content.contains("async def ")
                || content.contains("async fn ")
                || content.contains("await ")
        } else if lower.contains("must be async") || lower.contains("async") {
            ext == "py" && !content.contains("async def ") && !content.contains("async ")
                || ext == "rs" && !content.contains("async fn ")
        } else {
            false
        };

        if violated {
            header_issues.push(format!("违反约束: {}", constraint));
            checks.push(CheckItem {
                name: format!("constraint_{}", constraint.replace(' ', "_")),
                passed: false,
                level: "hard".to_string(),
                message: format!("违反约束: {}", constraint),
            });
        }
    }

    // ── Do_not 检测 ──
    for rule in &header.do_not {
        let lower = rule.to_lowercase();
        let violated = if lower.contains("no database") {
            let db_keywords = &[
                "import database",
                "from database",
                "import sqlalchemy",
                "import sqlite3",
                "import psycopg",
                "import mysql",
                "get_db",
                "session.query",
                "db.execute",
            ];
            !content_contains_any(&content, db_keywords).is_empty()
        } else if lower.contains("no authentication") || lower.contains("no auth") {
            let auth_keywords = &[
                "import auth",
                "from auth",
                "jwt",
                "token",
                "authenticate",
                "login",
            ];
            !content_contains_any(&content, auth_keywords).is_empty()
        } else if lower.contains("no direct fetch") {
            content.contains("fetch(")
                || content.contains("axios")
                || content.contains("XMLHttpRequest")
        } else if lower.contains("no localstorage") {
            content.contains("localStorage")
        } else if lower.contains("no direct sql") || lower.contains("no raw sql") {
            content.contains("execute(")
                && (content.contains("SELECT")
                    || content.contains("INSERT")
                    || content.contains("UPDATE"))
        } else {
            false
        };

        if violated {
            header_issues.push(format!("违反 Do_not: {}", rule));
            checks.push(CheckItem {
                name: format!("do_not_{}", rule.replace(' ', "_").replace('-', "_")),
                passed: false,
                level: "hard".to_string(),
                message: format!("违反 Do_not: {}", rule),
            });
        }
    }

    // ── 头尾交叉验证 ──
    // Do_not 说不操作数据库，但 mock_deps 里有数据库相关依赖
    if !header.do_not.is_empty() && !tail.mock_deps.is_empty() {
        for rule in &header.do_not {
            let lower = rule.to_lowercase();
            if lower.contains("no database") {
                for mock in &tail.mock_deps {
                    let mock_lower = mock.to_lowercase();
                    if mock_lower.contains("database")
                        || mock_lower.contains("get_db")
                        || mock_lower.contains("session")
                    {
                        cross_issues.push(format!(
                            "矛盾: 文件头 Do_not='{}' 但文件尾 mock_deps 包含 '{}'",
                            rule, mock
                        ));
                    }
                }
            }
        }
    }

    // env_sensitive 声明的变量在代码中是否使用
    for env_var in &tail.env_sensitive {
        let is_used = content.contains(env_var)
            || content.contains(&env_var.to_lowercase())
            || content.contains(&format!("\"{}\"", env_var));
        if !is_used {
            tail_issues.push(format!("env_sensitive 声明了 '{}' 但代码中未使用", env_var));
        }
    }

    // test_functions 引用的函数名是否在 actual_exports 中（提取函数名部分）
    for test_fn in &tail.test_functions {
        // test_xxx_yyy → extract xxx as the function being tested
        let tested = test_fn
            .strip_prefix("test_")
            .or_else(|| test_fn.strip_prefix("Test"))
            .unwrap_or(test_fn);
        let fn_name = tested.split('_').next().unwrap_or(tested);

        // very loose check: function name should appear somewhere in exports
        if !fn_name.is_empty() && fn_name.len() > 2 {
            let found = actual_exports
                .iter()
                .any(|e| e.to_lowercase().contains(&fn_name.to_lowercase()));
            if !found
                && !header
                    .exports
                    .iter()
                    .any(|e| e.to_lowercase().contains(&fn_name.to_lowercase()))
            {
                // only flag if we're confident
                // skip this check for now — too many false positives
            }
        }
    }

    // related_contracts vs tail.contracts 一致性
    if !header.related_contracts.is_empty() && !tail.contracts.is_empty() {
        let header_set: HashSet<&String> = header.related_contracts.iter().collect();
        let tail_set: HashSet<&String> = tail.contracts.iter().collect();
        for c in &header_set {
            if !tail_set.contains(c) {
                cross_issues.push(format!(
                    "文件头 Related_contracts 有 '{}' 但文件尾 contracts 未包含",
                    c
                ));
            }
        }
        for c in &tail_set {
            if !header_set.contains(c) {
                cross_issues.push(format!(
                    "文件尾 contracts 有 '{}' 但文件头 Related_contracts 未包含",
                    c
                ));
            }
        }
    }

    if !cross_issues.is_empty() {
        checks.push(CheckItem {
            name: "cross_validation".to_string(),
            passed: false,
            level: "soft".to_string(),
            message: format!("{} 个头尾矛盾", cross_issues.len()),
        });
    }

    let passed = checks
        .iter()
        .filter(|c| c.level == "hard")
        .all(|c| c.passed);

    Ok(PostWriteReport {
        file: file_path,
        passed,
        checks,
        header_issues,
        tail_issues,
        cross_issues,
    })
}

/// 批量检测一个模块下所有代码文件
pub async fn tool_post_write_check_module(
    module_path: String,
) -> Result<Vec<PostWriteReport>, String> {
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

    let mut reports = Vec::new();
    let mut stack = vec![root.to_path_buf()];

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

            match tool_post_write_check(path.to_string_lossy().to_string(), None).await {
                Ok(report) => reports.push(report),
                Err(_) => continue,
            }
        }
    }

    Ok(reports)
}
