use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct ProjectConfig {
    pub project_type: String,
    pub name: Option<String>,
    pub version: Option<String>,
    pub dependencies: HashMap<String, String>,
    pub dev_dependencies: HashMap<String, String>,
    pub scripts: HashMap<String, String>,
    pub entry: Option<String>,
}

pub async fn tool_read_config(project_path: String) -> Result<ProjectConfig, String> {
    let root = Path::new(&project_path);

    // Node.js — package.json
    let pkg_json = root.join("package.json");
    if pkg_json.exists() {
        return read_node_config(&pkg_json);
    }

    // Rust — Cargo.toml
    let cargo_toml = root.join("Cargo.toml");
    if cargo_toml.exists() {
        return read_rust_config(&cargo_toml);
    }

    // Python — pyproject.toml
    let pyproject = root.join("pyproject.toml");
    if pyproject.exists() {
        return read_python_config(&pyproject);
    }

    // Python — requirements.txt (fallback)
    let reqs = root.join("requirements.txt");
    if reqs.exists() {
        return read_requirements_txt(&reqs);
    }

    // Go — go.mod
    let go_mod = root.join("go.mod");
    if go_mod.exists() {
        return read_go_config(&go_mod);
    }

    Err("未检测到已知项目配置文件".to_string())
}

pub async fn tool_write_config(
    project_path: String,
    action: String,
    package_name: String,
    version: Option<String>,
    dev: Option<bool>,
) -> Result<String, String> {
    let root = Path::new(&project_path);

    // Node.js
    let pkg_json = root.join("package.json");
    if pkg_json.exists() {
        return write_node_dep(
            &pkg_json,
            &action,
            &package_name,
            version.as_deref(),
            dev.unwrap_or(false),
        );
    }

    // Rust
    let cargo_toml = root.join("Cargo.toml");
    if cargo_toml.exists() {
        return write_rust_dep(&cargo_toml, &action, &package_name, version.as_deref());
    }

    // Python requirements.txt
    let reqs = root.join("requirements.txt");
    if reqs.exists() {
        return write_python_dep(&reqs, &action, &package_name, version.as_deref());
    }

    Err("未检测到可写入的配置文件".to_string())
}

// ── Node.js ──

fn read_node_config(path: &Path) -> Result<ProjectConfig, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let val: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;

    let deps = extract_json_map(val.get("dependencies"));
    let dev_deps = extract_json_map(val.get("devDependencies"));
    let scripts = extract_json_map(val.get("scripts"));

    Ok(ProjectConfig {
        project_type: "node".to_string(),
        name: val
            .get("name")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        version: val
            .get("version")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        dependencies: deps,
        dev_dependencies: dev_deps,
        scripts,
        entry: val
            .get("main")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
    })
}

fn write_node_dep(
    path: &Path,
    action: &str,
    name: &str,
    version: Option<&str>,
    dev: bool,
) -> Result<String, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut val: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;

    let key = if dev {
        "devDependencies"
    } else {
        "dependencies"
    };

    match action {
        "add" => {
            let ver = version.unwrap_or("*");
            if val.get(key).is_none() {
                val[key] = serde_json::json!({});
            }
            val[key][name] = serde_json::Value::String(ver.to_string());
        }
        "remove" => {
            if let Some(obj) = val.get_mut(key).and_then(|v| v.as_object_mut()) {
                obj.remove(name);
            }
        }
        _ => return Err(format!("未知操作: {}", action)),
    }

    let out = serde_json::to_string_pretty(&val).map_err(|e| e.to_string())?;
    std::fs::write(path, out).map_err(|e| e.to_string())?;
    Ok(format!("{} {} 成功", action, name))
}

// ── Rust ──

fn read_rust_config(path: &Path) -> Result<ProjectConfig, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let val: toml::Value = content
        .parse()
        .map_err(|e: toml::de::Error| e.to_string())?;

    let name = val
        .get("package")
        .and_then(|p| p.get("name"))
        .and_then(|n| n.as_str())
        .map(|s| s.to_string());
    let version = val
        .get("package")
        .and_then(|p| p.get("version"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let deps = extract_toml_deps(val.get("dependencies"));
    let dev_deps = extract_toml_deps(val.get("dev-dependencies"));

    Ok(ProjectConfig {
        project_type: "rust".to_string(),
        name,
        version,
        dependencies: deps,
        dev_dependencies: dev_deps,
        scripts: HashMap::new(),
        entry: None,
    })
}

fn write_rust_dep(
    path: &Path,
    action: &str,
    name: &str,
    version: Option<&str>,
) -> Result<String, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;

    match action {
        "add" => {
            let ver = version.unwrap_or("*");
            let dep_line = format!("{} = \"{}\"", name, ver);
            // simple: append under [dependencies]
            let new_content = if content.contains("[dependencies]") {
                content.replacen(
                    "[dependencies]",
                    &format!("[dependencies]\n{}", dep_line),
                    1,
                )
            } else {
                format!("{}\n[dependencies]\n{}\n", content, dep_line)
            };
            std::fs::write(path, new_content).map_err(|e| e.to_string())?;
        }
        "remove" => {
            let lines: Vec<&str> = content
                .lines()
                .filter(|l| {
                    let trimmed = l.trim();
                    !trimmed.starts_with(&format!("{} ", name))
                        && !trimmed.starts_with(&format!("{}=", name))
                })
                .collect();
            std::fs::write(path, lines.join("\n")).map_err(|e| e.to_string())?;
        }
        _ => return Err(format!("未知操作: {}", action)),
    }
    Ok(format!("{} {} 成功", action, name))
}

// ── Python ──

fn read_python_config(path: &Path) -> Result<ProjectConfig, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let val: toml::Value = content
        .parse()
        .map_err(|e: toml::de::Error| e.to_string())?;

    let name = val
        .get("project")
        .and_then(|p| p.get("name"))
        .and_then(|n| n.as_str())
        .map(|s| s.to_string());
    let version = val
        .get("project")
        .and_then(|p| p.get("version"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let deps = val
        .get("project")
        .and_then(|p| p.get("dependencies"))
        .and_then(|d| d.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .map(|s| {
                    let parts: Vec<&str> = s.splitn(2, ">=").collect();
                    if parts.len() == 2 {
                        (
                            parts[0].trim().to_string(),
                            format!(">={}", parts[1].trim()),
                        )
                    } else {
                        (s.to_string(), "*".to_string())
                    }
                })
                .collect()
        })
        .unwrap_or_default();

    Ok(ProjectConfig {
        project_type: "python".to_string(),
        name,
        version,
        dependencies: deps,
        dev_dependencies: HashMap::new(),
        scripts: HashMap::new(),
        entry: None,
    })
}

fn read_requirements_txt(path: &Path) -> Result<ProjectConfig, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut deps = HashMap::new();
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = trimmed.splitn(2, "==").collect();
        if parts.len() == 2 {
            deps.insert(parts[0].trim().to_string(), parts[1].trim().to_string());
        } else {
            deps.insert(trimmed.to_string(), "*".to_string());
        }
    }

    Ok(ProjectConfig {
        project_type: "python".to_string(),
        name: None,
        version: None,
        dependencies: deps,
        dev_dependencies: HashMap::new(),
        scripts: HashMap::new(),
        entry: None,
    })
}

fn write_python_dep(
    path: &Path,
    action: &str,
    name: &str,
    version: Option<&str>,
) -> Result<String, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    match action {
        "add" => {
            let line = match version {
                Some(v) => format!("{}=={}", name, v),
                None => name.to_string(),
            };
            let new_content = format!("{}\n{}\n", content.trim_end(), line);
            std::fs::write(path, new_content).map_err(|e| e.to_string())?;
        }
        "remove" => {
            let lines: Vec<&str> = content
                .lines()
                .filter(|l| {
                    let trimmed = l.trim();
                    !trimmed.starts_with(name)
                })
                .collect();
            std::fs::write(path, lines.join("\n")).map_err(|e| e.to_string())?;
        }
        _ => return Err(format!("未知操作: {}", action)),
    }
    Ok(format!("{} {} 成功", action, name))
}

// ── Go ──

fn read_go_config(path: &Path) -> Result<ProjectConfig, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut name = None;
    let mut deps = HashMap::new();

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("module ") {
            name = Some(
                trimmed
                    .strip_prefix("module ")
                    .unwrap_or("")
                    .trim()
                    .to_string(),
            );
        }
        if trimmed.starts_with("require ") || (!trimmed.starts_with("//") && trimmed.contains(" v"))
        {
            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() >= 2 && parts[1].starts_with('v') {
                deps.insert(parts[0].to_string(), parts[1].to_string());
            }
        }
    }

    Ok(ProjectConfig {
        project_type: "go".to_string(),
        name,
        version: None,
        dependencies: deps,
        dev_dependencies: HashMap::new(),
        scripts: HashMap::new(),
        entry: None,
    })
}

// ── Helpers ──

fn extract_json_map(val: Option<&serde_json::Value>) -> HashMap<String, String> {
    val.and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .map(|(k, v)| (k.clone(), v.as_str().unwrap_or("*").to_string()))
                .collect()
        })
        .unwrap_or_default()
}

fn extract_toml_deps(val: Option<&toml::Value>) -> HashMap<String, String> {
    val.and_then(|v| v.as_table())
        .map(|table| {
            table
                .iter()
                .map(|(k, v)| {
                    let ver = match v {
                        toml::Value::String(s) => s.clone(),
                        toml::Value::Table(t) => t
                            .get("version")
                            .and_then(|v| v.as_str())
                            .unwrap_or("*")
                            .to_string(),
                        _ => "*".to_string(),
                    };
                    (k.clone(), ver)
                })
                .collect()
        })
        .unwrap_or_default()
}
