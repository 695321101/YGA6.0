use serde::{Deserialize, Serialize};
use std::path::Path;

// ── Gate Check Result ──

#[derive(Debug, Serialize, Deserialize)]
pub struct GateCheckResult {
    pub passed: bool,
    pub checks: Vec<GateCheck>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GateCheck {
    pub name: String,
    pub passed: bool,
    pub level: String, // "hard" or "soft"
    pub message: String,
}

// ── Signature ──

#[derive(Debug, Serialize, Deserialize)]
pub struct FunctionSignature {
    pub name: String,
    pub params: Vec<String>,
    pub return_type: Option<String>,
    pub line: usize,
    pub exported: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SignatureResult {
    pub file: String,
    pub language: String,
    pub signatures: Vec<FunctionSignature>,
}

// ── Skeleton Verify ──

#[derive(Debug, Serialize, Deserialize)]
pub struct SkeletonVerifyResult {
    pub passed: bool,
    pub coverage_issues: Vec<String>,
    pub hallucination_issues: Vec<String>,
    pub dependency_issues: Vec<String>,
}

// ── IPC Commands ──

/// Function-level gate check (§6.9 W 门禁)
/// Reads stack.json for language-specific rules, runs zero-AI checks.
pub async fn tool_gate_check(
    file_path: String,
    function_name: String,
    stack_json_path: Option<String>,
    file_plan_path: Option<String>,
) -> Result<GateCheckResult, String> {
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
    let mut checks = Vec::new();

    // Load stack.json empty_impl_patterns if available
    let empty_patterns = if let Some(ref sjp) = stack_json_path {
        load_empty_patterns(sjp, &ext)
    } else {
        default_empty_patterns(&ext)
    };

    // Check 1: Empty implementation detection (hard block)
    let has_empty_impl = check_empty_impl(&content, &function_name, &empty_patterns);
    checks.push(GateCheck {
        name: "empty_impl".to_string(),
        passed: !has_empty_impl,
        level: "hard".to_string(),
        message: if has_empty_impl {
            format!(
                "函数 {} 包含空实现（pass/TODO/NotImplementedError）",
                function_name
            )
        } else {
            "无空实现".to_string()
        },
    });

    // Check 2: Import validity (soft warning)
    let invalid_imports = check_import_validity(&content, path);
    checks.push(GateCheck {
        name: "import_validity".to_string(),
        passed: invalid_imports.is_empty(),
        level: "soft".to_string(),
        message: if invalid_imports.is_empty() {
            "所有 import 路径有效".to_string()
        } else {
            format!("无效的 import: {}", invalid_imports.join(", "))
        },
    });

    // Check 3: Signature match vs file_plan (soft warning)
    if let Some(ref fpp) = file_plan_path {
        let sig_match = check_signature_match(&content, &function_name, &ext, fpp);
        checks.push(sig_match);
    }

    let passed = checks
        .iter()
        .filter(|c| c.level == "hard")
        .all(|c| c.passed);

    Ok(GateCheckResult { passed, checks })
}

/// Extract all function signatures from a file
pub async fn tool_extract_signatures(file_path: String) -> Result<SignatureResult, String> {
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
    let language = ext_to_language(&ext);
    let signatures = extract_signatures_regex(&content, &ext);

    Ok(SignatureResult {
        file: file_path,
        language,
        signatures,
    })
}

/// S-verify: skeleton vs file_plan coverage check (§6.7)
pub async fn tool_verify_skeleton(
    project_path: String,
    file_plan_path: String,
) -> Result<SkeletonVerifyResult, String> {
    let plan_content = tokio::fs::read_to_string(&file_plan_path)
        .await
        .map_err(|e| format!("file_plan 读取失败: {}", e))?;

    let plan: serde_json::Value = serde_json::from_str(&plan_content)
        .map_err(|e| format!("file_plan JSON 解析失败: {}", e))?;

    let root = Path::new(&project_path);
    let mut coverage_issues = Vec::new();
    let mut hallucination_issues = Vec::new();
    let mut dependency_issues = Vec::new();

    // Check 1: Every file in file_plan exists
    if let Some(files) = plan.get("files").and_then(|f| f.as_array()) {
        for file_entry in files {
            if let Some(path_str) = file_entry.get("path").and_then(|p| p.as_str()) {
                let full = root.join(path_str);
                if !full.exists() {
                    coverage_issues.push(format!("file_plan 中的文件不存在: {}", path_str));
                    continue;
                }

                // Check each declared export exists in skeleton
                if let Some(exports) = file_entry.get("exports").and_then(|e| e.as_array()) {
                    if let Ok(content) = std::fs::read_to_string(&full) {
                        for export in exports {
                            if let Some(fn_name) = export.as_str() {
                                if !content.contains(fn_name) {
                                    coverage_issues.push(format!(
                                        "{}: 缺少声明的 export '{}'",
                                        path_str, fn_name
                                    ));
                                }
                            }
                        }

                        // Check 2: Hallucination detection — functions in skeleton but not in plan
                        let ext = full
                            .extension()
                            .map(|e| e.to_string_lossy().to_string())
                            .unwrap_or_default();
                        let actual_sigs = extract_signatures_regex(&content, &ext);
                        let declared: Vec<String> = exports
                            .iter()
                            .filter_map(|e| e.as_str().map(|s| s.to_string()))
                            .collect();

                        for sig in &actual_sigs {
                            if sig.exported && !declared.contains(&sig.name) {
                                hallucination_issues.push(format!(
                                    "{}: 骨架中有未声明的函数 '{}'（可能是幻觉）",
                                    path_str, sig.name
                                ));
                            }
                        }
                    }
                }

                // Check 3: Dependency consistency
                if let Some(imports_from) =
                    file_entry.get("imports_from").and_then(|i| i.as_array())
                {
                    if let Ok(_content) = std::fs::read_to_string(&full) {
                        for imp in imports_from {
                            if let Some(imp_path) = imp.as_str() {
                                let imp_full = root.join(imp_path);
                                if !imp_full.exists() {
                                    dependency_issues.push(format!(
                                        "{}: imports_from '{}' 但该文件不存在",
                                        path_str, imp_path
                                    ));
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    let passed = coverage_issues.is_empty()
        && hallucination_issues.is_empty()
        && dependency_issues.is_empty();

    Ok(SkeletonVerifyResult {
        passed,
        coverage_issues,
        hallucination_issues,
        dependency_issues,
    })
}

// ── Internal helpers ──

fn load_empty_patterns(stack_json_path: &str, ext: &str) -> Vec<String> {
    let content = match std::fs::read_to_string(stack_json_path) {
        Ok(c) => c,
        Err(_) => return default_empty_patterns(ext),
    };
    let val: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return default_empty_patterns(ext),
    };

    // Find the language section matching this extension
    let lang_key = ext_to_stack_key(ext);
    val.get(&lang_key)
        .or_else(|| val.get("frontend"))
        .or_else(|| val.get("backend"))
        .and_then(|section| section.get("tools"))
        .and_then(|tools| tools.get("empty_impl_patterns"))
        .and_then(|patterns| patterns.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_else(|| default_empty_patterns(ext))
}

fn default_empty_patterns(ext: &str) -> Vec<String> {
    match ext {
        "py" => vec![
            "pass".into(),
            "raise NotImplementedError".into(),
            "...".into(),
        ],
        "js" | "jsx" | "ts" | "tsx" => vec![
            "throw new Error('TODO')".into(),
            "throw new Error(\"TODO\")".into(),
            "// TODO".into(),
        ],
        "rs" => vec!["todo!()".into(), "unimplemented!()".into()],
        "go" => vec!["panic(\"not implemented\")".into(), "// TODO".into()],
        _ => vec!["TODO".into(), "FIXME".into()],
    }
}

fn check_empty_impl(content: &str, function_name: &str, patterns: &[String]) -> bool {
    // Find the function body and check for empty implementation patterns
    let mut in_function = false;
    let mut brace_depth = 0i32;
    let mut fn_body = String::new();

    for line in content.lines() {
        let trimmed = line.trim();
        if !in_function && trimmed.contains(function_name) {
            in_function = true;
        }
        if in_function {
            fn_body.push_str(trimmed);
            fn_body.push('\n');
            brace_depth += trimmed.matches('{').count() as i32;
            brace_depth -= trimmed.matches('}').count() as i32;
            // Python: detect function by indentation (simplified)
            if brace_depth <= 0 && fn_body.lines().count() > 2 {
                break;
            }
        }
    }

    if fn_body.is_empty() {
        return false;
    }

    for pattern in patterns {
        if fn_body.contains(pattern.as_str()) {
            return true;
        }
    }
    false
}

fn check_import_validity(content: &str, file_path: &Path) -> Vec<String> {
    let mut invalid = Vec::new();
    let dir = file_path.parent().unwrap_or(Path::new("."));

    for line in content.lines() {
        let trimmed = line.trim();
        // JS/TS relative imports
        if (trimmed.starts_with("import ") || trimmed.contains("require("))
            && trimmed.contains("'./")
        {
            if let Some(start) = trimmed.find("'./").or(trimmed.find("\"./")) {
                let rest = &trimmed[start + 1..];
                if let Some(end) = rest.find(['\'', '"']) {
                    let imp_path = &rest[..end];
                    let candidate = dir.join(imp_path);
                    let exts = ["", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts"];
                    let exists = exts.iter().any(|ext| {
                        std::path::PathBuf::from(format!("{}{}", candidate.display(), ext)).exists()
                    });
                    if !exists {
                        invalid.push(imp_path.to_string());
                    }
                }
            }
        }
    }
    invalid
}

fn check_signature_match(
    content: &str,
    function_name: &str,
    ext: &str,
    _file_plan_path: &str,
) -> GateCheck {
    // Simplified: just check the function exists in the file
    let sigs = extract_signatures_regex(content, ext);
    let found = sigs.iter().any(|s| s.name == function_name);
    GateCheck {
        name: "signature_match".to_string(),
        passed: found,
        level: "soft".to_string(),
        message: if found {
            format!("函数 {} 签名存在", function_name)
        } else {
            format!("函数 {} 未在文件中找到", function_name)
        },
    }
}

/// Regex-based function signature extraction (will be replaced by tree-sitter later)
fn extract_signatures_regex(content: &str, ext: &str) -> Vec<FunctionSignature> {
    let mut sigs = Vec::new();

    for (i, line) in content.lines().enumerate() {
        let trimmed = line.trim();
        match ext {
            "py" => {
                if trimmed.starts_with("def ") || trimmed.starts_with("async def ") {
                    if let Some(sig) = parse_py_function(trimmed, i + 1) {
                        sigs.push(sig);
                    }
                }
            }
            "js" | "jsx" | "ts" | "tsx" | "mjs" => {
                if trimmed.contains("function ")
                    || trimmed.contains("=> ")
                    || trimmed.starts_with("export ")
                {
                    if let Some(sig) = parse_js_function(trimmed, i + 1) {
                        sigs.push(sig);
                    }
                }
            }
            "rs" => {
                if trimmed.starts_with("pub fn ")
                    || trimmed.starts_with("fn ")
                    || trimmed.starts_with("pub async fn ")
                    || trimmed.starts_with("async fn ")
                {
                    if let Some(sig) = parse_rust_function(trimmed, i + 1) {
                        sigs.push(sig);
                    }
                }
            }
            "go" => {
                if trimmed.starts_with("func ") {
                    if let Some(sig) = parse_go_function(trimmed, i + 1) {
                        sigs.push(sig);
                    }
                }
            }
            _ => {}
        }
    }
    sigs
}

fn parse_py_function(line: &str, line_num: usize) -> Option<FunctionSignature> {
    let stripped = line.trim_start_matches("async ").trim_start_matches("def ");
    let paren = stripped.find('(')?;
    let name = stripped[..paren].trim().to_string();
    let params_end = stripped.find(')')?;
    let params_str = &stripped[paren + 1..params_end];
    let params: Vec<String> = params_str
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && s != "self")
        .collect();
    let return_type = stripped.find("->").map(|i| {
        stripped[i + 2..]
            .trim()
            .trim_end_matches(':')
            .trim()
            .to_string()
    });

    Some(FunctionSignature {
        name,
        params,
        return_type,
        line: line_num,
        exported: true,
    })
}

fn parse_js_function(line: &str, line_num: usize) -> Option<FunctionSignature> {
    let exported = line.starts_with("export ");
    let stripped = line
        .trim_start_matches("export ")
        .trim_start_matches("default ")
        .trim_start_matches("async ");

    if stripped.starts_with("function ") {
        let rest = stripped.strip_prefix("function ")?;
        let paren = rest.find('(')?;
        let name = rest[..paren].trim().to_string();
        if name.is_empty() {
            return None;
        }
        let params_end = rest.find(')')?;
        let params: Vec<String> = rest[paren + 1..params_end]
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        return Some(FunctionSignature {
            name,
            params,
            return_type: None,
            line: line_num,
            exported,
        });
    }

    // const name = (...) =>
    if stripped.starts_with("const ") || stripped.starts_with("let ") {
        let rest = stripped
            .trim_start_matches("const ")
            .trim_start_matches("let ");
        if let Some(eq) = rest.find('=') {
            let name = rest[..eq].trim().to_string();
            if rest[eq..].contains("=>") {
                return Some(FunctionSignature {
                    name,
                    params: Vec::new(),
                    return_type: None,
                    line: line_num,
                    exported,
                });
            }
        }
    }
    None
}

fn parse_rust_function(line: &str, line_num: usize) -> Option<FunctionSignature> {
    let exported = line.starts_with("pub ");
    let stripped = line.trim_start_matches("pub ").trim_start_matches("async ");

    if stripped.starts_with("fn ") {
        let rest = stripped.strip_prefix("fn ")?;
        let paren = rest.find('(')?;
        let name = rest[..paren].trim().to_string();
        let params_end = rest.find(')')?;
        let params: Vec<String> = rest[paren + 1..params_end]
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty() && !s.starts_with("&self"))
            .collect();
        let return_type = rest.find("->").map(|i| {
            rest[i + 2..]
                .trim()
                .trim_end_matches('{')
                .trim()
                .to_string()
        });
        return Some(FunctionSignature {
            name,
            params,
            return_type,
            line: line_num,
            exported,
        });
    }
    None
}

fn parse_go_function(line: &str, line_num: usize) -> Option<FunctionSignature> {
    let rest = line.strip_prefix("func ")?;
    // skip methods: func (r *Receiver) Name(...)
    let start = if rest.starts_with('(') {
        rest.find(')')? + 1
    } else {
        0
    };
    let rest = rest[start..].trim();
    let paren = rest.find('(')?;
    let name = rest[..paren].trim().to_string();
    let exported = name
        .chars()
        .next()
        .map(|c| c.is_uppercase())
        .unwrap_or(false);
    Some(FunctionSignature {
        name,
        params: Vec::new(),
        return_type: None,
        line: line_num,
        exported,
    })
}

fn ext_to_language(ext: &str) -> String {
    match ext {
        "py" => "python",
        "js" | "jsx" | "mjs" => "javascript",
        "ts" | "tsx" => "typescript",
        "rs" => "rust",
        "go" => "go",
        "java" => "java",
        "c" | "h" => "c",
        "cpp" | "cc" | "hpp" => "cpp",
        _ => "unknown",
    }
    .to_string()
}

fn ext_to_stack_key(ext: &str) -> String {
    match ext {
        "js" | "jsx" | "ts" | "tsx" | "mjs" => "frontend",
        _ => "backend",
    }
    .to_string()
}
