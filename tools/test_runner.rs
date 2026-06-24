use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::process::Command;

// ── 测试结果结构 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct TestRunResult {
    pub success: bool,
    pub passed: u32,
    pub failed: u32,
    pub skipped: u32,
    pub total: u32,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub failures: Vec<TestFailureInfo>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TestFailureInfo {
    pub test_name: String,
    pub file: Option<String>,
    pub line: Option<u32>,
    pub error_message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SyntaxCheckResult {
    pub success: bool,
    pub errors: Vec<SyntaxError>,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SyntaxError {
    pub file: Option<String>,
    pub line: Option<u32>,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FormatResult {
    pub success: bool,
    pub files_formatted: Vec<String>,
    pub stdout: String,
    pub stderr: String,
}

// ── 辅助 ──

fn load_stack_json(stack_path: &str) -> Result<serde_json::Value, String> {
    let content =
        std::fs::read_to_string(stack_path).map_err(|e| format!("stack.json 读取失败: {}", e))?;
    serde_json::from_str(&content).map_err(|e| format!("stack.json 解析失败: {}", e))
}

fn get_tool_cmd(stack: &serde_json::Value, section: &str, tool_name: &str) -> Option<String> {
    stack
        .get(section)?
        .get("tools")?
        .get(tool_name)?
        .as_str()
        .map(|s| s.to_string())
}

pub async fn run_shell(cmd: &str, cwd: &str) -> (String, String, i32) {
    #[cfg(target_os = "windows")]
    let result = Command::new("cmd.exe")
        .args(["/C", cmd])
        .current_dir(cwd)
        .output()
        .await;

    #[cfg(not(target_os = "windows"))]
    let result = Command::new("sh")
        .args(["-c", cmd])
        .current_dir(cwd)
        .output()
        .await;

    match result {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            let code = output.status.code().unwrap_or(-1);
            (stdout, stderr, code)
        }
        Err(e) => (String::new(), format!("执行失败: {}", e), -1),
    }
}

// ── 事实提取（正则提取 stderr 中的信息，不做判断） ──

pub fn extract_failure_facts(stdout: &str, stderr: &str) -> Vec<TestFailureInfo> {
    let mut failures = Vec::new();
    let combined = format!("{}\n{}", stdout, stderr);

    // pytest: FAILED file::test_name - message
    let re_pytest =
        regex::Regex::new(r"FAILED\s+(?P<file>[^:]+)::(?P<test>\S+)\s*-\s*(?P<msg>.+)").ok();
    if let Some(re) = re_pytest {
        for caps in re.captures_iter(&combined) {
            failures.push(TestFailureInfo {
                test_name: caps.name("test").map_or("", |m| m.as_str()).to_string(),
                file: caps.name("file").map(|m| m.as_str().to_string()),
                line: None,
                error_message: caps.name("msg").map_or("", |m| m.as_str()).to_string(),
            });
        }
    }

    // jest/vitest: ✕ test name
    let re_jest = regex::Regex::new(r"[✕×]\s+(?P<test>.+?)(?:\s+\(\d+\s*ms\))?$").ok();
    if let Some(re) = re_jest {
        for caps in re.captures_iter(&combined) {
            failures.push(TestFailureInfo {
                test_name: caps.name("test").map_or("", |m| m.as_str()).to_string(),
                file: None,
                line: None,
                error_message: String::new(),
            });
        }
    }

    // cargo test: test name ... FAILED
    let re_cargo = regex::Regex::new(r"test\s+(?P<test>\S+)\s+\.\.\.\s+FAILED").ok();
    if let Some(re) = re_cargo {
        for caps in re.captures_iter(&combined) {
            failures.push(TestFailureInfo {
                test_name: caps.name("test").map_or("", |m| m.as_str()).to_string(),
                file: None,
                line: None,
                error_message: String::new(),
            });
        }
    }

    // go test: --- FAIL: TestName
    let re_go = regex::Regex::new(r"---\s+FAIL:\s+(?P<test>\S+)").ok();
    if let Some(re) = re_go {
        for caps in re.captures_iter(&combined) {
            failures.push(TestFailureInfo {
                test_name: caps.name("test").map_or("", |m| m.as_str()).to_string(),
                file: None,
                line: None,
                error_message: String::new(),
            });
        }
    }

    // extract pass/fail counts from pytest summary
    failures
}

pub fn extract_test_counts(stdout: &str, stderr: &str) -> (u32, u32, u32) {
    let combined = format!("{}\n{}", stdout, stderr);
    let mut passed = 0u32;
    let mut failed = 0u32;
    let mut skipped = 0u32;

    // pytest: "5 passed, 2 failed, 1 skipped"
    if let Some(re) = regex::Regex::new(r"(\d+)\s+passed").ok() {
        if let Some(caps) = re.captures(&combined) {
            passed = caps[1].parse().unwrap_or(0);
        }
    }
    if let Some(re) = regex::Regex::new(r"(\d+)\s+failed").ok() {
        if let Some(caps) = re.captures(&combined) {
            failed = caps[1].parse().unwrap_or(0);
        }
    }
    if let Some(re) = regex::Regex::new(r"(\d+)\s+skipped").ok() {
        if let Some(caps) = re.captures(&combined) {
            skipped = caps[1].parse().unwrap_or(0);
        }
    }

    // jest/vitest: "Tests: 2 failed, 5 passed, 7 total"
    if passed == 0 && failed == 0 {
        if let Some(re) = regex::Regex::new(
            r"Tests:\s+(?:(\d+)\s+failed,\s+)?(?:(\d+)\s+passed,\s+)?(\d+)\s+total",
        )
        .ok()
        {
            if let Some(caps) = re.captures(&combined) {
                failed = caps
                    .get(1)
                    .and_then(|m| m.as_str().parse().ok())
                    .unwrap_or(0);
                passed = caps
                    .get(2)
                    .and_then(|m| m.as_str().parse().ok())
                    .unwrap_or(0);
            }
        }
    }

    // cargo test: "test result: ok. 5 passed; 0 failed"
    if passed == 0 && failed == 0 {
        if let Some(re) = regex::Regex::new(r"(\d+)\s+passed;\s+(\d+)\s+failed").ok() {
            if let Some(caps) = re.captures(&combined) {
                passed = caps[1].parse().unwrap_or(0);
                failed = caps[2].parse().unwrap_or(0);
            }
        }
    }

    (passed, failed, skipped)
}

// ── IPC 命令 ──

/// 根据 stack.json 跑测试，返回结构化结果
pub async fn tool_run_tests(
    project_path: String,
    stack_json_path: String,
    section: String,
    filter: Option<String>,
) -> Result<TestRunResult, String> {
    let stack = load_stack_json(&stack_json_path)?;

    let cmd = if let Some(ref f) = filter {
        get_tool_cmd(&stack, &section, "test_filter").map(|c| c.replace("{fn}", f))
    } else {
        get_tool_cmd(&stack, &section, "test_run")
    }
    .ok_or(format!("stack.json 中未找到 {}.tools.test_run", section))?;

    let (stdout, stderr, exit_code) = run_shell(&cmd, &project_path).await;
    let success = exit_code == 0;
    let failures = extract_failure_facts(&stdout, &stderr);
    let (passed, failed, skipped) = extract_test_counts(&stdout, &stderr);

    Ok(TestRunResult {
        success,
        passed,
        failed,
        skipped,
        total: passed + failed + skipped,
        stdout,
        stderr,
        exit_code,
        failures,
    })
}

/// 根据 stack.json 跑语法检查
pub async fn tool_syntax_check(
    project_path: String,
    stack_json_path: String,
    section: String,
    file_path: Option<String>,
) -> Result<SyntaxCheckResult, String> {
    let stack = load_stack_json(&stack_json_path)?;
    let cmd_template = get_tool_cmd(&stack, &section, "syntax_check").ok_or(format!(
        "stack.json 中未找到 {}.tools.syntax_check",
        section
    ))?;

    let cmd = if let Some(ref fp) = file_path {
        cmd_template.replace("{file}", fp)
    } else {
        cmd_template
    };

    let (stdout, stderr, exit_code) = run_shell(&cmd, &project_path).await;
    let success = exit_code == 0;

    // extract error locations (fact extraction only)
    let mut errors = Vec::new();
    let re_file_line = regex::Regex::new(r"(?P<file>[^\s:]+):(?P<line>\d+)").ok();
    if !success {
        if let Some(re) = re_file_line {
            for line in stderr.lines().chain(stdout.lines()) {
                if let Some(caps) = re.captures(line) {
                    errors.push(SyntaxError {
                        file: caps.name("file").map(|m| m.as_str().to_string()),
                        line: caps.name("line").and_then(|m| m.as_str().parse().ok()),
                        message: line.trim().to_string(),
                    });
                }
            }
        }
        // if no structured errors found, add the whole stderr as one error
        if errors.is_empty() && !stderr.is_empty() {
            errors.push(SyntaxError {
                file: file_path.clone(),
                line: None,
                message: stderr.lines().take(5).collect::<Vec<_>>().join("\n"),
            });
        }
    }

    Ok(SyntaxCheckResult {
        success,
        errors,
        stdout,
        stderr,
    })
}

/// 根据 stack.json 跑格式化
pub async fn tool_format_code(
    project_path: String,
    stack_json_path: String,
    section: String,
    file_path: Option<String>,
) -> Result<FormatResult, String> {
    let stack = load_stack_json(&stack_json_path)?;
    let cmd_template = get_tool_cmd(&stack, &section, "format")
        .ok_or(format!("stack.json 中未找到 {}.tools.format", section))?;

    let cmd = if let Some(ref fp) = file_path {
        format!("{} {}", cmd_template, fp)
    } else {
        cmd_template
    };

    let (stdout, stderr, exit_code) = run_shell(&cmd, &project_path).await;
    let success = exit_code == 0;

    let files_formatted = if success && file_path.is_some() {
        vec![file_path.unwrap()]
    } else {
        Vec::new()
    };

    Ok(FormatResult {
        success,
        files_formatted,
        stdout,
        stderr,
    })
}

/// 读取出错行 ±N 行上下文（HOTSPOT 命令）
pub async fn tool_read_hotspot(
    file_path: String,
    line: u32,
    context_lines: Option<u32>,
) -> Result<String, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("文件不存在: {}", file_path));
    }

    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| format!("读取失败: {}", e))?;

    let lines: Vec<&str> = content.lines().collect();
    let ctx = context_lines.unwrap_or(5) as usize;
    let target = (line as usize).saturating_sub(1); // 0-indexed
    let start = target.saturating_sub(ctx);
    let end = (target + ctx + 1).min(lines.len());

    let mut result = String::new();
    for i in start..end {
        let marker = if i == target { " >>>" } else { "    " };
        result.push_str(&format!("{} {:>4} | {}\n", marker, i + 1, lines[i]));
    }

    Ok(result)
}
