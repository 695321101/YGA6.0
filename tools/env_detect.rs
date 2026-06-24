use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use tokio::process::Command;

// ── 环境探测结果 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct EnvInfo {
    pub os: String,
    pub arch: String,
    pub cpu_cores: usize,
    pub memory_gb: f64,
    pub runtimes: HashMap<String, Option<String>>,
    pub git: GitInfo,
    pub databases: HashMap<String, ServiceStatus>,
    pub network: NetworkConfig,
    pub available_ports: Vec<u16>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GitInfo {
    pub available: bool,
    pub version: Option<String>,
    pub user_name: Option<String>,
    pub user_email: Option<String>,
    pub default_branch: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ServiceStatus {
    pub available: bool,
    pub port: Option<u16>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct NetworkConfig {
    pub npm_registry: Option<String>,
    pub pip_index: Option<String>,
    pub cargo_mirror: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InstalledPackage {
    pub name: String,
    pub version: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InstalledPackages {
    pub python: Vec<InstalledPackage>,
    pub node: Vec<InstalledPackage>,
    pub global_tools: HashMap<String, String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EnvOverrides {
    pub variables: HashMap<String, String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExistingFiles {
    pub is_new_project: bool,
    pub total_files: usize,
    pub directories: Vec<String>,
    pub config_files: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LangInfo {
    pub language: String,
    pub version: Option<String>,
    pub path: Option<String>,
    pub available: bool,
    pub details: HashMap<String, serde_json::Value>,
}

// ── 辅助：运行命令取输出 ──

async fn run_cmd(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program).args(args).output().await.ok()?;
    if output.status.success() {
        Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        None
    }
}

async fn run_cmd_with_stderr(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program).args(args).output().await.ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !stdout.is_empty() {
        Some(stdout)
    } else if !stderr.is_empty() {
        Some(stderr)
    } else {
        None
    }
}

fn extract_version(text: &str) -> Option<String> {
    let re = regex::Regex::new(r"(\d+\.\d+(?:\.\d+)?)").ok()?;
    re.captures(text)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_string())
}

async fn check_port(port: u16) -> bool {
    tokio::net::TcpListener::bind(("127.0.0.1", port))
        .await
        .is_ok()
}

// ── IPC 命令 ──

pub async fn tool_detect_env() -> Result<EnvInfo, String> {
    let os = std::env::consts::OS.to_string();
    let arch = std::env::consts::ARCH.to_string();

    let cpu_cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);

    // memory: use systeminfo on Windows, sysinfo crate would be better but keep deps minimal
    let memory_gb = detect_memory().await;

    // runtimes
    let mut runtimes = HashMap::new();
    runtimes.insert(
        "python".to_string(),
        detect_runtime("python", &["--version"]).await,
    );
    runtimes.insert(
        "node".to_string(),
        detect_runtime("node", &["--version"]).await,
    );
    runtimes.insert(
        "rust".to_string(),
        detect_runtime("rustc", &["--version"]).await,
    );
    runtimes.insert("go".to_string(), detect_runtime("go", &["version"]).await);
    runtimes.insert(
        "java".to_string(),
        detect_runtime("java", &["-version"]).await,
    );

    // git
    let git = detect_git().await;

    // databases
    let mut databases = HashMap::new();
    databases.insert("postgresql".to_string(), check_service(5432).await);
    databases.insert("mysql".to_string(), check_service(3306).await);
    databases.insert("redis".to_string(), check_service(6379).await);
    databases.insert(
        "sqlite".to_string(),
        ServiceStatus {
            available: true,
            port: None,
        },
    );

    // network config
    let network = detect_network_config().await;

    // available ports
    let candidate_ports = [3000, 5173, 8000, 8080, 8888, 9000];
    let mut available_ports = Vec::new();
    for port in candidate_ports {
        if check_port(port).await {
            available_ports.push(port);
        }
    }

    Ok(EnvInfo {
        os,
        arch,
        cpu_cores,
        memory_gb,
        runtimes,
        git,
        databases,
        network,
        available_ports,
    })
}

pub async fn tool_detect_packages() -> Result<InstalledPackages, String> {
    let python = detect_python_packages().await;
    let node = detect_node_packages().await;
    let global_tools = detect_global_tools().await;

    Ok(InstalledPackages {
        python,
        node,
        global_tools,
    })
}

pub async fn tool_detect_env_overrides(project_path: String) -> Result<EnvOverrides, String> {
    let env_path = Path::new(&project_path).join(".env");
    let mut variables = HashMap::new();

    if env_path.exists() {
        let content = tokio::fs::read_to_string(&env_path)
            .await
            .map_err(|e| format!("读取 .env 失败: {}", e))?;

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }
            if let Some(eq_pos) = trimmed.find('=') {
                let key = trimmed[..eq_pos].trim().to_string();
                let value = trimmed[eq_pos + 1..].trim().to_string();
                // redact sensitive values
                let safe_value = if is_sensitive_key(&key) {
                    "[REDACTED]".to_string()
                } else {
                    value
                };
                variables.insert(key, safe_value);
            }
        }
    }

    Ok(EnvOverrides { variables })
}

pub async fn tool_detect_existing_files(project_path: String) -> Result<ExistingFiles, String> {
    let root = Path::new(&project_path);
    if !root.is_dir() {
        return Ok(ExistingFiles {
            is_new_project: true,
            total_files: 0,
            directories: Vec::new(),
            config_files: Vec::new(),
        });
    }

    let skip_dirs = [
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
    let config_names = [
        "package.json",
        "Cargo.toml",
        "pyproject.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "requirements.txt",
        "tsconfig.json",
        ".env",
        "docker-compose.yml",
        "Dockerfile",
    ];

    let mut total_files = 0usize;
    let mut directories = Vec::new();
    let mut config_files = Vec::new();

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
                    let rel = path
                        .strip_prefix(root)
                        .unwrap_or(&path)
                        .to_string_lossy()
                        .replace('\\', "/");
                    directories.push(rel);
                    stack.push(path);
                }
                continue;
            }

            total_files += 1;
            if config_names.contains(&name.as_str()) {
                let rel = path
                    .strip_prefix(root)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .replace('\\', "/");
                config_files.push(rel);
            }
        }
    }

    Ok(ExistingFiles {
        is_new_project: total_files == 0,
        total_files,
        directories,
        config_files,
    })
}

pub async fn tool_detect_lang(language: String) -> Result<LangInfo, String> {
    match language.as_str() {
        "python" => detect_lang_python().await,
        "typescript" | "javascript" => detect_lang_typescript().await,
        "rust" => detect_lang_rust().await,
        "go" => detect_lang_go().await,
        "java" => detect_lang_java().await,
        other => Ok(LangInfo {
            language: other.to_string(),
            version: None,
            path: None,
            available: false,
            details: HashMap::new(),
        }),
    }
}

// ── 内部探测函数 ──

async fn detect_runtime(cmd: &str, args: &[&str]) -> Option<String> {
    let output = run_cmd_with_stderr(cmd, args).await?;
    extract_version(&output)
}

async fn detect_memory() -> f64 {
    #[cfg(target_os = "windows")]
    {
        if let Some(output) = run_cmd(
            "wmic",
            &["computersystem", "get", "TotalPhysicalMemory", "/value"],
        )
        .await
        {
            if let Some(line) = output
                .lines()
                .find(|l| l.starts_with("TotalPhysicalMemory="))
            {
                if let Some(val) = line.strip_prefix("TotalPhysicalMemory=") {
                    if let Ok(bytes) = val.trim().parse::<u64>() {
                        return (bytes as f64) / 1_073_741_824.0;
                    }
                }
            }
        }
        0.0
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Some(output) = run_cmd("free", &["-b"]).await {
            for line in output.lines() {
                if line.starts_with("Mem:") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        if let Ok(bytes) = parts[1].parse::<u64>() {
                            return (bytes as f64) / 1_073_741_824.0;
                        }
                    }
                }
            }
        }
        0.0
    }
}

async fn detect_git() -> GitInfo {
    let version = run_cmd("git", &["--version"])
        .await
        .and_then(|v| extract_version(&v));
    let available = version.is_some();
    let user_name = if available {
        run_cmd("git", &["config", "--global", "user.name"]).await
    } else {
        None
    };
    let user_email = if available {
        run_cmd("git", &["config", "--global", "user.email"]).await
    } else {
        None
    };
    let default_branch = if available {
        run_cmd("git", &["config", "--global", "init.defaultBranch"])
            .await
            .or(Some("main".to_string()))
    } else {
        None
    };

    GitInfo {
        available,
        version,
        user_name,
        user_email,
        default_branch,
    }
}

async fn check_service(port: u16) -> ServiceStatus {
    // if we can't bind to the port, something is listening there
    let available = !check_port(port).await;
    ServiceStatus {
        available,
        port: if available { Some(port) } else { None },
    }
}

async fn detect_network_config() -> NetworkConfig {
    let npm_registry = run_cmd("npm", &["config", "get", "registry"]).await;
    let pip_index = run_cmd("pip", &["config", "get", "global.index-url"])
        .await
        .or_else(|| {
            run_cmd_blocking(
                "python",
                &["-m", "pip", "config", "get", "global.index-url"],
            )
        });

    NetworkConfig {
        npm_registry,
        pip_index,
        cargo_mirror: None,
    }
}

fn run_cmd_blocking(program: &str, args: &[&str]) -> Option<String> {
    let output = std::process::Command::new(program)
        .args(args)
        .output()
        .ok()?;
    if output.status.success() {
        Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        None
    }
}

async fn detect_python_packages() -> Vec<InstalledPackage> {
    let output = run_cmd("pip", &["list", "--format=json"]).await;
    if let Some(json_str) = output {
        if let Ok(packages) = serde_json::from_str::<Vec<serde_json::Value>>(&json_str) {
            return packages
                .iter()
                .filter_map(|p| {
                    let name = p.get("name")?.as_str()?.to_string();
                    let version = p.get("version")?.as_str()?.to_string();
                    Some(InstalledPackage { name, version })
                })
                .collect();
        }
    }
    Vec::new()
}

async fn detect_node_packages() -> Vec<InstalledPackage> {
    let output = run_cmd("npm", &["ls", "--global", "--json", "--depth=0"]).await;
    if let Some(json_str) = output {
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
            if let Some(deps) = val.get("dependencies").and_then(|d| d.as_object()) {
                return deps
                    .iter()
                    .filter_map(|(name, info)| {
                        let version = info.get("version")?.as_str()?.to_string();
                        Some(InstalledPackage {
                            name: name.clone(),
                            version,
                        })
                    })
                    .collect();
            }
        }
    }
    Vec::new()
}

async fn detect_global_tools() -> HashMap<String, String> {
    let mut tools = HashMap::new();
    let tool_checks = [
        ("prettier", vec!["prettier", "--version"]),
        ("eslint", vec!["eslint", "--version"]),
        ("ruff", vec!["ruff", "--version"]),
        ("black", vec!["black", "--version"]),
        ("mypy", vec!["mypy", "--version"]),
        ("clippy", vec!["cargo", "clippy", "--version"]),
    ];
    for (name, args) in tool_checks {
        if let Some(output) = run_cmd(args[0], &args[1..]).await {
            if let Some(ver) = extract_version(&output) {
                tools.insert(name.to_string(), ver);
            }
        }
    }
    tools
}

fn is_sensitive_key(key: &str) -> bool {
    let upper = key.to_uppercase();
    upper.contains("SECRET")
        || upper.contains("KEY")
        || upper.contains("PASSWORD")
        || upper.contains("TOKEN")
        || upper.contains("CREDENTIAL")
        || upper.contains("PRIVATE")
}

// ── 语言详细探测 ──

async fn detect_lang_python() -> Result<LangInfo, String> {
    let version = run_cmd_with_stderr("python", &["--version"])
        .await
        .and_then(|v| extract_version(&v));
    let path = run_cmd("python", &["-c", "import sys; print(sys.executable)"]).await;
    let available = version.is_some();
    let mut details = HashMap::new();

    if available {
        // pip source
        if let Some(pip_src) = run_cmd("pip", &["config", "get", "global.index-url"]).await {
            details.insert("pip_source".to_string(), serde_json::Value::String(pip_src));
        }

        // stdlib modules (common ones that AI might confuse with third-party)
        let stdlib: Vec<String> = vec![
            "json",
            "os",
            "sys",
            "pathlib",
            "datetime",
            "typing",
            "re",
            "hashlib",
            "uuid",
            "logging",
            "asyncio",
            "collections",
            "functools",
            "itertools",
            "math",
            "random",
            "time",
            "urllib",
            "http",
            "io",
            "csv",
            "sqlite3",
            "subprocess",
            "shutil",
            "tempfile",
            "unittest",
            "dataclasses",
            "enum",
            "abc",
            "contextlib",
            "copy",
            "decimal",
            "base64",
            "secrets",
            "string",
            "textwrap",
            "struct",
            "threading",
            "multiprocessing",
            "socket",
            "email",
            "html",
            "xml",
            "zipfile",
            "gzip",
            "tarfile",
            "configparser",
            "argparse",
        ]
        .into_iter()
        .map(|s| s.to_string())
        .collect();
        details.insert("stdlib_modules".to_string(), serde_json::json!(stdlib));

        // test framework
        let has_pytest = run_cmd("pytest", &["--version"]).await.is_some();
        details.insert(
            "test_framework".to_string(),
            serde_json::Value::String(if has_pytest { "pytest" } else { "unittest" }.to_string()),
        );

        // conventions
        details.insert(
            "naming".to_string(),
            serde_json::Value::String("snake_case".to_string()),
        );
        details.insert(
            "import_style".to_string(),
            serde_json::Value::String("absolute".to_string()),
        );
        details.insert(
            "error_pattern".to_string(),
            serde_json::Value::String("try/except".to_string()),
        );
        details.insert(
            "test_file_pattern".to_string(),
            serde_json::Value::String("test_*.py".to_string()),
        );
    }

    Ok(LangInfo {
        language: "python".to_string(),
        version,
        path,
        available,
        details,
    })
}

async fn detect_lang_typescript() -> Result<LangInfo, String> {
    let version = run_cmd("tsc", &["--version"])
        .await
        .and_then(|v| extract_version(&v));
    let node_version = run_cmd("node", &["--version"])
        .await
        .and_then(|v| extract_version(&v));
    let available = node_version.is_some();
    let mut details = HashMap::new();

    if available {
        // package manager
        let pm = if run_cmd("pnpm", &["--version"]).await.is_some() {
            "pnpm"
        } else if run_cmd("yarn", &["--version"]).await.is_some() {
            "yarn"
        } else {
            "npm"
        };
        details.insert(
            "package_manager".to_string(),
            serde_json::Value::String(pm.to_string()),
        );

        if let Some(nv) = &node_version {
            details.insert(
                "node_version".to_string(),
                serde_json::Value::String(nv.clone()),
            );
        }

        // registry
        if let Some(reg) = run_cmd("npm", &["config", "get", "registry"]).await {
            details.insert("registry".to_string(), serde_json::Value::String(reg));
        }

        details.insert(
            "naming".to_string(),
            serde_json::Value::String("camelCase".to_string()),
        );
        details.insert(
            "component_naming".to_string(),
            serde_json::Value::String("PascalCase".to_string()),
        );
        details.insert(
            "import_style".to_string(),
            serde_json::Value::String("named imports".to_string()),
        );
        details.insert(
            "error_pattern".to_string(),
            serde_json::Value::String("try/catch".to_string()),
        );
        details.insert(
            "test_file_pattern".to_string(),
            serde_json::Value::String("*.test.ts".to_string()),
        );
    }

    Ok(LangInfo {
        language: "typescript".to_string(),
        version,
        path: None,
        available,
        details,
    })
}

async fn detect_lang_rust() -> Result<LangInfo, String> {
    let version = run_cmd("rustc", &["--version"])
        .await
        .and_then(|v| extract_version(&v));
    let path = run_cmd("rustup", &["which", "rustc"]).await;
    let available = version.is_some();
    let mut details = HashMap::new();

    if available {
        details.insert(
            "edition".to_string(),
            serde_json::Value::String("2021".to_string()),
        );

        if let Some(target) = run_cmd("rustc", &["-vV"]).await {
            for line in target.lines() {
                if line.starts_with("host:") {
                    details.insert(
                        "target".to_string(),
                        serde_json::Value::String(
                            line.trim_start_matches("host:").trim().to_string(),
                        ),
                    );
                }
            }
        }

        let has_clippy = run_cmd("cargo", &["clippy", "--version"]).await.is_some();
        details.insert("clippy".to_string(), serde_json::Value::Bool(has_clippy));

        details.insert(
            "naming".to_string(),
            serde_json::Value::String("snake_case".to_string()),
        );
        details.insert(
            "error_pattern".to_string(),
            serde_json::Value::String("Result<T, E>".to_string()),
        );
        details.insert(
            "test_file_pattern".to_string(),
            serde_json::Value::String("#[test] or tests/".to_string()),
        );
    }

    Ok(LangInfo {
        language: "rust".to_string(),
        version,
        path,
        available,
        details,
    })
}

async fn detect_lang_go() -> Result<LangInfo, String> {
    let version = run_cmd("go", &["version"])
        .await
        .and_then(|v| extract_version(&v));
    let path = run_cmd("go", &["env", "GOROOT"]).await;
    let available = version.is_some();
    let mut details = HashMap::new();

    if available {
        if let Some(gopath) = run_cmd("go", &["env", "GOPATH"]).await {
            details.insert("gopath".to_string(), serde_json::Value::String(gopath));
        }
        details.insert("go_modules".to_string(), serde_json::Value::Bool(true));
        details.insert(
            "naming_exported".to_string(),
            serde_json::Value::String("PascalCase".to_string()),
        );
        details.insert(
            "naming_unexported".to_string(),
            serde_json::Value::String("camelCase".to_string()),
        );
        details.insert(
            "error_pattern".to_string(),
            serde_json::Value::String("if err != nil".to_string()),
        );
        details.insert(
            "test_file_pattern".to_string(),
            serde_json::Value::String("*_test.go".to_string()),
        );
    }

    Ok(LangInfo {
        language: "go".to_string(),
        version,
        path,
        available,
        details,
    })
}

async fn detect_lang_java() -> Result<LangInfo, String> {
    let version = run_cmd_with_stderr("java", &["-version"])
        .await
        .and_then(|v| extract_version(&v));
    let path = std::env::var("JAVA_HOME").ok();
    let available = version.is_some();
    let mut details = HashMap::new();

    if available {
        let has_maven = run_cmd("mvn", &["--version"]).await.is_some();
        let has_gradle = run_cmd("gradle", &["--version"]).await.is_some();
        details.insert("maven".to_string(), serde_json::Value::Bool(has_maven));
        details.insert("gradle".to_string(), serde_json::Value::Bool(has_gradle));
        details.insert(
            "naming".to_string(),
            serde_json::Value::String("camelCase".to_string()),
        );
        details.insert(
            "class_naming".to_string(),
            serde_json::Value::String("PascalCase".to_string()),
        );
        details.insert(
            "test_file_pattern".to_string(),
            serde_json::Value::String("*Test.java".to_string()),
        );
    }

    Ok(LangInfo {
        language: "java".to_string(),
        version,
        path,
        available,
        details,
    })
}

/// 一键采集所有环境信息，保存到项目的 facts/ 目录
pub async fn tool_probe_all(project_path: String) -> Result<String, String> {
    let facts_dir = Path::new(&project_path).join("facts");
    tokio::fs::create_dir_all(&facts_dir)
        .await
        .map_err(|e| format!("创建 facts/ 目录失败: {}", e))?;

    // 1. env.json
    let env_info = tool_detect_env().await?;
    let env_json = serde_json::to_string_pretty(&env_info).map_err(|e| e.to_string())?;
    tokio::fs::write(facts_dir.join("env.json"), &env_json)
        .await
        .map_err(|e| e.to_string())?;

    // 2. installed_packages.json
    let packages = tool_detect_packages().await?;
    let pkg_json = serde_json::to_string_pretty(&packages).map_err(|e| e.to_string())?;
    tokio::fs::write(facts_dir.join("installed_packages.json"), &pkg_json)
        .await
        .map_err(|e| e.to_string())?;

    // 3. env_overrides.json
    let overrides = tool_detect_env_overrides(project_path.clone()).await?;
    let ov_json = serde_json::to_string_pretty(&overrides).map_err(|e| e.to_string())?;
    tokio::fs::write(facts_dir.join("env_overrides.json"), &ov_json)
        .await
        .map_err(|e| e.to_string())?;

    // 4. existing_files.json
    let files = tool_detect_existing_files(project_path.clone()).await?;
    let files_json = serde_json::to_string_pretty(&files).map_err(|e| e.to_string())?;
    tokio::fs::write(facts_dir.join("existing_files.json"), &files_json)
        .await
        .map_err(|e| e.to_string())?;

    // 5. lang_*.json for detected runtimes
    for (lang_name, ver) in &env_info.runtimes {
        if ver.is_some() {
            if let Ok(lang_info) = tool_detect_lang(lang_name.clone()).await {
                let lang_json =
                    serde_json::to_string_pretty(&lang_info).map_err(|e| e.to_string())?;
                tokio::fs::write(
                    facts_dir.join(format!("lang_{}.json", lang_name)),
                    &lang_json,
                )
                .await
                .map_err(|e| e.to_string())?;
            }
        }
    }

    Ok(format!("Probe 完成，facts/ 已写入 {}", facts_dir.display()))
}
