use serde::{Deserialize, Serialize};
use std::process::Command as StdCommand;

#[derive(Debug, Serialize, Deserialize)]
pub struct GitResult {
    pub success: bool,
    pub output: String,
}

fn run_git(args: &[&str], cwd: &str) -> Result<GitResult, String> {
    let output = StdCommand::new("git")
        .args(args)
        .current_dir(cwd)
        .output()
        .map_err(|e| format!("Git 执行失败: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if output.status.success() {
        Ok(GitResult {
            success: true,
            output: stdout,
        })
    } else {
        Ok(GitResult {
            success: false,
            output: if stderr.is_empty() { stdout } else { stderr },
        })
    }
}

pub async fn tool_git_status(cwd: String) -> Result<GitResult, String> {
    run_git(&["status", "--porcelain", "-b"], &cwd)
}

pub async fn tool_git_log(count: Option<u32>, cwd: String) -> Result<GitResult, String> {
    let n = count.unwrap_or(20);
    let n_str = format!("-{}", n);
    run_git(&["log", &n_str, "--oneline", "--graph", "--decorate"], &cwd)
}

pub async fn tool_git_diff(staged: Option<bool>, cwd: String) -> Result<GitResult, String> {
    if staged.unwrap_or(false) {
        run_git(&["diff", "--cached"], &cwd)
    } else {
        run_git(&["diff"], &cwd)
    }
}

pub async fn tool_git_add(files: Vec<String>, cwd: String) -> Result<GitResult, String> {
    let mut args: Vec<&str> = vec!["add"];
    let refs: Vec<&str> = files.iter().map(|s| s.as_str()).collect();
    args.extend(refs);
    run_git(&args, &cwd)
}

pub async fn tool_git_commit(message: String, cwd: String) -> Result<GitResult, String> {
    run_git(&["commit", "-m", &message], &cwd)
}

pub async fn tool_git_branch(cwd: String) -> Result<GitResult, String> {
    run_git(&["branch", "-a"], &cwd)
}

pub async fn tool_git_raw(args: Vec<String>, cwd: String) -> Result<GitResult, String> {
    let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
    run_git(&refs, &cwd)
}
