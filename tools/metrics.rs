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

#[derive(Debug, Serialize, Deserialize)]
pub struct MetricsReport {
    pub total_files: usize,
    pub total_lines: usize,
    pub code_lines: usize,
    pub comment_lines: usize,
    pub blank_lines: usize,
    pub languages: Vec<LanguageMetrics>,
    pub top_files: Vec<FileMetrics>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LanguageMetrics {
    pub language: String,
    pub files: usize,
    pub code_lines: usize,
    pub comment_lines: usize,
    pub blank_lines: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FileMetrics {
    pub file: String,
    pub language: String,
    pub lines: usize,
    pub functions: usize,
}

struct LangDef {
    name: &'static str,
    extensions: &'static [&'static str],
    line_comment: &'static str,
    block_start: &'static str,
    block_end: &'static str,
    fn_pattern: &'static str,
}

const LANGUAGES: &[LangDef] = &[
    LangDef {
        name: "JavaScript",
        extensions: &["js", "jsx", "mjs"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "function ",
    },
    LangDef {
        name: "TypeScript",
        extensions: &["ts", "tsx"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "function ",
    },
    LangDef {
        name: "Python",
        extensions: &["py"],
        line_comment: "#",
        block_start: "\"\"\"",
        block_end: "\"\"\"",
        fn_pattern: "def ",
    },
    LangDef {
        name: "Rust",
        extensions: &["rs"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "fn ",
    },
    LangDef {
        name: "Go",
        extensions: &["go"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "func ",
    },
    LangDef {
        name: "Java",
        extensions: &["java"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "",
    },
    LangDef {
        name: "C",
        extensions: &["c", "h"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "",
    },
    LangDef {
        name: "C++",
        extensions: &["cpp", "cc", "cxx", "hpp"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "",
    },
    LangDef {
        name: "HTML",
        extensions: &["html", "htm"],
        line_comment: "",
        block_start: "<!--",
        block_end: "-->",
        fn_pattern: "",
    },
    LangDef {
        name: "CSS",
        extensions: &["css", "scss", "less"],
        line_comment: "//",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "",
    },
    LangDef {
        name: "JSON",
        extensions: &["json"],
        line_comment: "",
        block_start: "",
        block_end: "",
        fn_pattern: "",
    },
    LangDef {
        name: "YAML",
        extensions: &["yaml", "yml"],
        line_comment: "#",
        block_start: "",
        block_end: "",
        fn_pattern: "",
    },
    LangDef {
        name: "Markdown",
        extensions: &["md"],
        line_comment: "",
        block_start: "",
        block_end: "",
        fn_pattern: "",
    },
    LangDef {
        name: "Shell",
        extensions: &["sh", "bash"],
        line_comment: "#",
        block_start: "",
        block_end: "",
        fn_pattern: "",
    },
    LangDef {
        name: "SQL",
        extensions: &["sql"],
        line_comment: "--",
        block_start: "/*",
        block_end: "*/",
        fn_pattern: "",
    },
    LangDef {
        name: "Vue",
        extensions: &["vue"],
        line_comment: "//",
        block_start: "<!--",
        block_end: "-->",
        fn_pattern: "",
    },
];

fn detect_language(ext: &str) -> Option<&'static LangDef> {
    LANGUAGES.iter().find(|l| l.extensions.contains(&ext))
}

pub async fn tool_code_metrics(project_path: String) -> Result<MetricsReport, String> {
    let root = Path::new(&project_path);
    if !root.is_dir() {
        return Err(format!("目录不存在: {}", project_path));
    }

    let mut lang_stats: HashMap<String, LanguageMetrics> = HashMap::new();
    let mut all_files: Vec<FileMetrics> = Vec::new();
    let mut total_lines = 0usize;
    let mut total_code = 0usize;
    let mut total_comment = 0usize;
    let mut total_blank = 0usize;
    let mut total_files = 0usize;

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

            let ext = name.rsplit('.').next().unwrap_or("").to_lowercase();
            let lang = match detect_language(&ext) {
                Some(l) => l,
                None => continue,
            };

            let content = match std::fs::read_to_string(&path) {
                Ok(c) => c,
                Err(_) => continue,
            };

            total_files += 1;
            let mut code = 0usize;
            let mut comment = 0usize;
            let mut blank = 0usize;
            let mut functions = 0usize;
            let mut in_block = false;

            for line in content.lines() {
                let trimmed = line.trim();

                if trimmed.is_empty() {
                    blank += 1;
                    continue;
                }

                // block comment tracking
                if in_block {
                    comment += 1;
                    if !lang.block_end.is_empty() && trimmed.contains(lang.block_end) {
                        in_block = false;
                    }
                    continue;
                }

                if !lang.block_start.is_empty() && trimmed.starts_with(lang.block_start) {
                    comment += 1;
                    if !trimmed.contains(lang.block_end) || lang.block_start == lang.block_end {
                        in_block = true;
                    }
                    continue;
                }

                if !lang.line_comment.is_empty() && trimmed.starts_with(lang.line_comment) {
                    comment += 1;
                    continue;
                }

                code += 1;

                // simple function counting
                if !lang.fn_pattern.is_empty() && trimmed.contains(lang.fn_pattern) {
                    functions += 1;
                }
            }

            let lines = code + comment + blank;
            total_lines += lines;
            total_code += code;
            total_comment += comment;
            total_blank += blank;

            // aggregate per language
            let entry = lang_stats
                .entry(lang.name.to_string())
                .or_insert(LanguageMetrics {
                    language: lang.name.to_string(),
                    files: 0,
                    code_lines: 0,
                    comment_lines: 0,
                    blank_lines: 0,
                });
            entry.files += 1;
            entry.code_lines += code;
            entry.comment_lines += comment;
            entry.blank_lines += blank;

            all_files.push(FileMetrics {
                file: path.to_string_lossy().to_string(),
                language: lang.name.to_string(),
                lines,
                functions,
            });
        }
    }

    // sort files by lines descending, take top 20
    all_files.sort_by(|a, b| b.lines.cmp(&a.lines));
    all_files.truncate(20);

    // sort languages by code_lines descending
    let mut languages: Vec<LanguageMetrics> = lang_stats.into_values().collect();
    languages.sort_by(|a, b| b.code_lines.cmp(&a.code_lines));

    Ok(MetricsReport {
        total_files,
        total_lines,
        code_lines: total_code,
        comment_lines: total_comment,
        blank_lines: total_blank,
        languages,
        top_files: all_files,
    })
}
