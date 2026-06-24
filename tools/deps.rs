use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
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

#[derive(Debug, Serialize, Deserialize)]
pub struct DepGraphResult {
    pub files: usize,
    pub edges: usize,
    pub graph: HashMap<String, Vec<String>>,
    pub orphans: Vec<String>,
    pub cycles: Vec<Vec<String>>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ImpactResult {
    pub source: String,
    pub direct_dependents: Vec<String>,
    pub transitive_dependents: Vec<String>,
    pub total_affected: usize,
}

pub async fn tool_dep_graph(project_path: String) -> Result<DepGraphResult, String> {
    let root = Path::new(&project_path);
    if !root.is_dir() {
        return Err(format!("目录不存在: {}", project_path));
    }

    let mut graph: HashMap<String, Vec<String>> = HashMap::new();
    let mut all_files: HashSet<String> = HashSet::new();
    let mut imported_files: HashSet<String> = HashSet::new();

    // collect all source files
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

            if !is_source_file(&name) {
                continue;
            }

            let rel = pathdiff(root, &path);
            all_files.insert(rel.clone());

            // parse imports
            if let Ok(content) = std::fs::read_to_string(&path) {
                let imports = extract_imports(&content, &path, root);
                for imp in &imports {
                    imported_files.insert(imp.clone());
                }
                if !imports.is_empty() {
                    graph.insert(rel, imports);
                }
            }
        }
    }

    let edges: usize = graph.values().map(|v| v.len()).sum();

    // find orphans (files that neither import nor are imported)
    let importing_files: HashSet<&String> = graph.keys().collect();
    let orphans: Vec<String> = all_files
        .iter()
        .filter(|f| !importing_files.contains(f) && !imported_files.contains(*f))
        .cloned()
        .collect();

    // detect cycles (simple DFS)
    let cycles = detect_cycles(&graph);

    Ok(DepGraphResult {
        files: all_files.len(),
        edges,
        graph,
        orphans,
        cycles,
    })
}

pub async fn tool_impact_analysis(
    project_path: String,
    file_path: String,
) -> Result<ImpactResult, String> {
    let root = Path::new(&project_path);
    let target = if Path::new(&file_path).is_absolute() {
        pathdiff(root, Path::new(&file_path))
    } else {
        file_path.clone()
    };

    // build the graph first
    let dep_result = tool_dep_graph(project_path).await?;

    // build reverse graph (who depends on target)
    let mut reverse: HashMap<String, Vec<String>> = HashMap::new();
    for (file, deps) in &dep_result.graph {
        for dep in deps {
            reverse.entry(dep.clone()).or_default().push(file.clone());
        }
    }

    // BFS from target
    let direct = reverse.get(&target).cloned().unwrap_or_default();
    let mut visited: HashSet<String> = HashSet::new();
    let mut queue: VecDeque<String> = VecDeque::new();
    let mut transitive = Vec::new();

    for d in &direct {
        queue.push_back(d.clone());
        visited.insert(d.clone());
    }

    while let Some(current) = queue.pop_front() {
        transitive.push(current.clone());
        if let Some(dependents) = reverse.get(&current) {
            for dep in dependents {
                if visited.insert(dep.clone()) {
                    queue.push_back(dep.clone());
                }
            }
        }
    }

    let total = transitive.len();

    Ok(ImpactResult {
        source: target,
        direct_dependents: direct,
        transitive_dependents: transitive,
        total_affected: total,
    })
}

// ── Import extraction (regex-based, multi-language) ──

fn extract_imports(content: &str, file_path: &Path, root: &Path) -> Vec<String> {
    let mut imports = Vec::new();
    let ext = file_path
        .extension()
        .map(|e| e.to_string_lossy().to_string())
        .unwrap_or_default();

    for line in content.lines() {
        let trimmed = line.trim();
        match ext.as_str() {
            "js" | "jsx" | "ts" | "tsx" | "mjs" => {
                // import X from './Y' or require('./Y')
                if let Some(path) = extract_js_import(trimmed) {
                    if let Some(resolved) = resolve_relative(&path, file_path, root) {
                        imports.push(resolved);
                    }
                }
            }
            "py" => {
                // from X import Y or import X
                if let Some(module) = extract_py_import(trimmed) {
                    if let Some(resolved) = resolve_py_module(&module, file_path, root) {
                        imports.push(resolved);
                    }
                }
            }
            "rs" => {
                // use crate::X or mod X
                if let Some(module) = extract_rust_import(trimmed) {
                    imports.push(module);
                }
            }
            "go" => {
                if let Some(pkg) = extract_go_import(trimmed) {
                    imports.push(pkg);
                }
            }
            _ => {}
        }
    }
    imports
}

fn extract_js_import(line: &str) -> Option<String> {
    // import ... from '...' or import '...'
    if line.starts_with("import ") {
        if let Some(start) = line.find(['\'', '"']) {
            let rest = &line[start + 1..];
            if let Some(end) = rest.find(['\'', '"']) {
                let path = &rest[..end];
                if path.starts_with('.') {
                    return Some(path.to_string());
                }
            }
        }
    }
    // require('...')
    if line.contains("require(") {
        if let Some(start) = line.find("require(") {
            let after = &line[start + 8..];
            if let Some(q_start) = after.find(['\'', '"']) {
                let rest = &after[q_start + 1..];
                if let Some(q_end) = rest.find(['\'', '"']) {
                    let path = &rest[..q_end];
                    if path.starts_with('.') {
                        return Some(path.to_string());
                    }
                }
            }
        }
    }
    None
}

fn extract_py_import(line: &str) -> Option<String> {
    if line.starts_with("from ") {
        let rest = line.strip_prefix("from ")?.trim();
        let module = rest.split_whitespace().next()?;
        if module.starts_with('.') {
            return Some(module.to_string());
        }
    }
    None
}

fn extract_rust_import(line: &str) -> Option<String> {
    if line.starts_with("mod ") && line.ends_with(';') {
        let module = line.strip_prefix("mod ")?.strip_suffix(';')?.trim();
        return Some(module.to_string());
    }
    if line.starts_with("use crate::") {
        let path = line.strip_prefix("use crate::")?.split("::").next()?;
        return Some(path.to_string());
    }
    None
}

fn extract_go_import(line: &str) -> Option<String> {
    let trimmed = line.trim().trim_start_matches("import ");
    if trimmed.starts_with('"') {
        let pkg = trimmed.trim_matches('"');
        return Some(pkg.to_string());
    }
    None
}

fn resolve_relative(import_path: &str, from_file: &Path, root: &Path) -> Option<String> {
    let dir = from_file.parent()?;
    let candidate = dir.join(import_path);

    // try with extensions
    let extensions = [
        "",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        "/index.js",
        "/index.ts",
        "/index.tsx",
    ];
    for ext in &extensions {
        let full = PathBuf::from(format!("{}{}", candidate.to_string_lossy(), ext));
        if full.exists() {
            return Some(pathdiff(root, &full));
        }
    }
    None
}

fn resolve_py_module(module: &str, from_file: &Path, root: &Path) -> Option<String> {
    let dir = from_file.parent()?;
    let dots = module.chars().take_while(|c| *c == '.').count();
    let mut base = dir.to_path_buf();
    for _ in 1..dots {
        base = base.parent()?.to_path_buf();
    }
    let rest = &module[dots..];
    if rest.is_empty() {
        return None;
    }
    let file = base.join(rest.replace('.', "/"));
    let candidates = [file.with_extension("py"), file.join("__init__.py")];
    for c in &candidates {
        if c.exists() {
            return Some(pathdiff(root, c));
        }
    }
    None
}

fn pathdiff(root: &Path, target: &Path) -> String {
    target
        .strip_prefix(root)
        .unwrap_or(target)
        .to_string_lossy()
        .replace('\\', "/")
}

fn is_source_file(name: &str) -> bool {
    let exts = [
        "js", "jsx", "ts", "tsx", "mjs", "py", "rs", "go", "java", "c", "cpp", "h", "hpp", "vue",
        "svelte", "rb", "php",
    ];
    if let Some(ext) = name.rsplit('.').next() {
        exts.contains(&ext.to_lowercase().as_str())
    } else {
        false
    }
}

fn detect_cycles(graph: &HashMap<String, Vec<String>>) -> Vec<Vec<String>> {
    let mut cycles = Vec::new();
    let mut visited: HashSet<String> = HashSet::new();
    let mut rec_stack: HashSet<String> = HashSet::new();
    let mut path: Vec<String> = Vec::new();

    for node in graph.keys() {
        if !visited.contains(node) {
            dfs_cycle(
                node,
                graph,
                &mut visited,
                &mut rec_stack,
                &mut path,
                &mut cycles,
            );
        }
    }
    cycles
}

fn dfs_cycle(
    node: &str,
    graph: &HashMap<String, Vec<String>>,
    visited: &mut HashSet<String>,
    rec_stack: &mut HashSet<String>,
    path: &mut Vec<String>,
    cycles: &mut Vec<Vec<String>>,
) {
    visited.insert(node.to_string());
    rec_stack.insert(node.to_string());
    path.push(node.to_string());

    if let Some(neighbors) = graph.get(node) {
        for next in neighbors {
            if !visited.contains(next) {
                dfs_cycle(next, graph, visited, rec_stack, path, cycles);
            } else if rec_stack.contains(next) {
                // found cycle
                if let Some(start) = path.iter().position(|n| n == next) {
                    let cycle: Vec<String> = path[start..].to_vec();
                    if cycles.len() < 10 {
                        cycles.push(cycle);
                    }
                }
            }
        }
    }

    path.pop();
    rec_stack.remove(node);
}
