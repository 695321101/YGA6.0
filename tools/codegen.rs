use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct CodegenResult {
    pub success: bool,
    pub files_generated: Vec<String>,
    pub types_count: usize,
}

/// type_codegen: Read contracts.json + type_mapping.json → generate type files per language (§6.6)
/// Zero AI, deterministic 100%
pub async fn tool_type_codegen(
    contracts_path: String,
    type_mapping_path: Option<String>,
    output_dir: String,
    languages: Vec<String>,
) -> Result<CodegenResult, String> {
    let contracts_content = tokio::fs::read_to_string(&contracts_path)
        .await
        .map_err(|e| format!("contracts.json 读取失败: {}", e))?;

    let contracts: serde_json::Value = serde_json::from_str(&contracts_content)
        .map_err(|e| format!("contracts.json 解析失败: {}", e))?;

    // Load type mapping (or use defaults)
    let type_map = if let Some(ref tmp) = type_mapping_path {
        load_type_mapping(tmp)?
    } else {
        default_type_mapping()
    };

    let shared_types = contracts
        .get("shared_types")
        .and_then(|st| st.as_object())
        .ok_or("contracts.json 缺少 shared_types")?;

    let out = Path::new(&output_dir);
    tokio::fs::create_dir_all(out)
        .await
        .map_err(|e| format!("创建输出目录失败: {}", e))?;

    let mut files_generated = Vec::new();
    let types_count = shared_types.len();

    for lang in &languages {
        let content = match lang.as_str() {
            "typescript" | "ts" => generate_typescript(shared_types, &type_map),
            "python" | "py" => generate_python(shared_types, &type_map),
            "go" => generate_go(shared_types, &type_map),
            "rust" | "rs" => generate_rust(shared_types, &type_map),
            "java" => generate_java(shared_types, &type_map),
            other => return Err(format!("不支持的语言: {}", other)),
        };

        let filename = match lang.as_str() {
            "typescript" | "ts" => "types.ts",
            "python" | "py" => "types.py",
            "go" => "types.go",
            "rust" | "rs" => "types.rs",
            "java" => "Types.java",
            _ => "types.txt",
        };

        let file_path = out.join(filename);
        tokio::fs::write(&file_path, &content)
            .await
            .map_err(|e| format!("写入 {} 失败: {}", filename, e))?;
        files_generated.push(file_path.to_string_lossy().to_string());
    }

    Ok(CodegenResult {
        success: true,
        files_generated,
        types_count,
    })
}

// ── Type mapping ──

type TypeMap = HashMap<String, HashMap<String, String>>;

fn load_type_mapping(path: &str) -> Result<TypeMap, String> {
    let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&content).map_err(|e| e.to_string())
}

fn default_type_mapping() -> TypeMap {
    let mut map: TypeMap = HashMap::new();

    let types = [
        (
            "string",
            vec![
                ("typescript", "string"),
                ("python", "str"),
                ("go", "string"),
                ("rust", "String"),
                ("java", "String"),
            ],
        ),
        (
            "integer",
            vec![
                ("typescript", "number"),
                ("python", "int"),
                ("go", "int64"),
                ("rust", "i64"),
                ("java", "long"),
            ],
        ),
        (
            "decimal",
            vec![
                ("typescript", "number"),
                ("python", "Decimal"),
                ("go", "float64"),
                ("rust", "f64"),
                ("java", "BigDecimal"),
            ],
        ),
        (
            "boolean",
            vec![
                ("typescript", "boolean"),
                ("python", "bool"),
                ("go", "bool"),
                ("rust", "bool"),
                ("java", "boolean"),
            ],
        ),
        (
            "datetime",
            vec![
                ("typescript", "Date"),
                ("python", "datetime"),
                ("go", "time.Time"),
                ("rust", "chrono::DateTime<Utc>"),
                ("java", "LocalDateTime"),
            ],
        ),
        (
            "uuid",
            vec![
                ("typescript", "string"),
                ("python", "UUID"),
                ("go", "uuid.UUID"),
                ("rust", "uuid::Uuid"),
                ("java", "UUID"),
            ],
        ),
    ];

    for (abstract_type, mappings) in types {
        let mut lang_map = HashMap::new();
        for (lang, concrete) in mappings {
            lang_map.insert(lang.to_string(), concrete.to_string());
        }
        map.insert(abstract_type.to_string(), lang_map);
    }
    map
}

fn resolve_type(abstract_type: &str, lang: &str, type_map: &TypeMap) -> String {
    // Handle generic types: array<T>, map<K,V>, optional<T>
    if abstract_type.starts_with("array<") {
        let inner = abstract_type
            .strip_prefix("array<")
            .unwrap()
            .strip_suffix('>')
            .unwrap_or("string");
        let resolved_inner = resolve_type(inner, lang, type_map);
        return match lang {
            "typescript" => format!("{}[]", resolved_inner),
            "python" => format!("list[{}]", resolved_inner),
            "go" => format!("[]{}", resolved_inner),
            "rust" => format!("Vec<{}>", resolved_inner),
            "java" => format!("List<{}>", resolved_inner),
            _ => format!("array<{}>", resolved_inner),
        };
    }
    if abstract_type.starts_with("optional<") {
        let inner = abstract_type
            .strip_prefix("optional<")
            .unwrap()
            .strip_suffix('>')
            .unwrap_or("string");
        let resolved_inner = resolve_type(inner, lang, type_map);
        return match lang {
            "typescript" => format!("{} | null", resolved_inner),
            "python" => format!("{} | None", resolved_inner),
            "go" => format!("*{}", resolved_inner),
            "rust" => format!("Option<{}>", resolved_inner),
            "java" => format!("@Nullable {}", resolved_inner),
            _ => format!("optional<{}>", resolved_inner),
        };
    }
    if abstract_type.starts_with("map<") {
        let inner = abstract_type
            .strip_prefix("map<")
            .unwrap()
            .strip_suffix('>')
            .unwrap_or("string,string");
        let parts: Vec<&str> = inner.splitn(2, ',').collect();
        let k = resolve_type(parts.first().unwrap_or(&"string").trim(), lang, type_map);
        let v = resolve_type(parts.get(1).unwrap_or(&"string").trim(), lang, type_map);
        return match lang {
            "typescript" => format!("Record<{}, {}>", k, v),
            "python" => format!("dict[{}, {}]", k, v),
            "go" => format!("map[{}]{}", k, v),
            "rust" => format!("HashMap<{}, {}>", k, v),
            "java" => format!("Map<{}, {}>", k, v),
            _ => format!("map<{},{}>", k, v),
        };
    }

    // Simple type lookup
    type_map
        .get(abstract_type)
        .and_then(|m| m.get(lang))
        .cloned()
        .unwrap_or_else(|| abstract_type.to_string())
}

// ── Code generators ──

fn generate_typescript(
    types: &serde_json::Map<String, serde_json::Value>,
    type_map: &TypeMap,
) -> String {
    let mut out = String::from("// Auto-generated by YGA type_codegen — DO NOT EDIT\n\n");
    for (name, fields) in types {
        out.push_str(&format!("export interface {} {{\n", name));
        if let Some(obj) = fields.as_object() {
            for (field, ftype) in obj {
                let ts_type =
                    resolve_type(ftype.as_str().unwrap_or("string"), "typescript", type_map);
                out.push_str(&format!("  {}: {};\n", field, ts_type));
            }
        }
        out.push_str("}\n\n");
    }
    out
}

fn generate_python(
    types: &serde_json::Map<String, serde_json::Value>,
    type_map: &TypeMap,
) -> String {
    let mut out = String::from("# Auto-generated by YGA type_codegen — DO NOT EDIT\n\nfrom pydantic import BaseModel\nfrom typing import Optional\nfrom decimal import Decimal\nfrom datetime import datetime\nfrom uuid import UUID\n\n");
    for (name, fields) in types {
        out.push_str(&format!("class {}(BaseModel):\n", name));
        if let Some(obj) = fields.as_object() {
            for (field, ftype) in obj {
                let py_type = resolve_type(ftype.as_str().unwrap_or("string"), "python", type_map);
                out.push_str(&format!("    {}: {}\n", field, py_type));
            }
        }
        out.push('\n');
    }
    out
}

fn generate_go(types: &serde_json::Map<String, serde_json::Value>, type_map: &TypeMap) -> String {
    let mut out = String::from("// Auto-generated by YGA type_codegen — DO NOT EDIT\npackage shared\n\nimport \"time\"\n\n");
    for (name, fields) in types {
        out.push_str(&format!("type {} struct {{\n", name));
        if let Some(obj) = fields.as_object() {
            for (field, ftype) in obj {
                let go_type = resolve_type(ftype.as_str().unwrap_or("string"), "go", type_map);
                let go_field = to_pascal_case(field);
                out.push_str(&format!(
                    "\t{} {} `json:\"{}\"`\n",
                    go_field, go_type, field
                ));
            }
        }
        out.push_str("}\n\n");
    }
    out
}

fn generate_rust(types: &serde_json::Map<String, serde_json::Value>, type_map: &TypeMap) -> String {
    let mut out = String::from("// Auto-generated by YGA type_codegen — DO NOT EDIT\nuse serde::{Deserialize, Serialize};\nuse std::collections::HashMap;\n\n");
    for (name, fields) in types {
        out.push_str(&format!(
            "#[derive(Debug, Clone, Serialize, Deserialize)]\npub struct {} {{\n",
            name
        ));
        if let Some(obj) = fields.as_object() {
            for (field, ftype) in obj {
                let rs_type = resolve_type(ftype.as_str().unwrap_or("string"), "rust", type_map);
                out.push_str(&format!("    pub {}: {},\n", field, rs_type));
            }
        }
        out.push_str("}\n\n");
    }
    out
}

fn generate_java(types: &serde_json::Map<String, serde_json::Value>, type_map: &TypeMap) -> String {
    let mut out = String::from("// Auto-generated by YGA type_codegen — DO NOT EDIT\nimport java.util.*;\nimport java.math.BigDecimal;\nimport java.time.LocalDateTime;\n\n");
    for (name, fields) in types {
        out.push_str(&format!("public class {} {{\n", name));
        if let Some(obj) = fields.as_object() {
            for (field, ftype) in obj {
                let java_type = resolve_type(ftype.as_str().unwrap_or("string"), "java", type_map);
                out.push_str(&format!("    private {} {};\n", java_type, field));
            }
        }
        out.push_str("}\n\n");
    }
    out
}

fn to_pascal_case(s: &str) -> String {
    s.split('_')
        .map(|part| {
            let mut chars = part.chars();
            match chars.next() {
                None => String::new(),
                Some(c) => c.to_uppercase().to_string() + &chars.as_str().to_lowercase(),
            }
        })
        .collect()
}
