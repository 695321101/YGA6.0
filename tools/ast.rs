use serde::{Deserialize, Serialize};
use std::path::Path;
use std::collections::HashMap;
use std::sync::Arc;
use once_cell::sync::Lazy;
use parking_lot::RwLock;

// ═══════════════════════════════════════════════════════════════════════════════
// 数据结构 - 与原有保持兼容
// ═══════════════════════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AstSignature {
    pub name: String,
    pub kind: String,        // "function", "class", "method", "variable", "struct", "enum"
    pub params: Vec<String>,
    pub return_type: Option<String>,
    pub line: usize,
    pub end_line: usize,
    pub exported: bool,
    pub parent: Option<String>,
    pub fields: Vec<String>,
    pub methods: Vec<String>,
    pub decorators: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AstParseResult {
    pub file: String,
    pub language: String,
    pub signatures: Vec<AstSignature>,
    pub imports: Vec<AstImport>,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AstImport {
    pub statement: String,
    pub module: String,
    pub names: Vec<String>,
    pub line: usize,
}

// ═══════════════════════════════════════════════════════════════════════════════
// 语言解析器接口 - 核心抽象
// ═══════════════════════════════════════════════════════════════════════════════

/// 语言解析器 Trait - 所有语言实现必须实现这个接口
pub trait LanguageParser: Send + Sync {
    /// 语言名称
    fn name(&self) -> &str;

    /// 支持的文件扩展名
    fn extensions(&self) -> Vec<&'static str>;

    /// 解析源码，提取签名和导入
    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>);

    /// 检查源码是否有效
    fn validate(&self, source: &[u8]) -> Result<(), String> {
        let _ = self.parse(source);
        Ok(())
    }
}

/// 解析器工厂函数类型
pub type ParserFactory = fn() -> Box<dyn LanguageParser>;

// ═══════════════════════════════════════════════════════════════════════════════
// 语言注册中心 - 配置驱动，取代硬编码的 get_language()
// ═══════════════════════════════════════════════════════════════════════════════

pub struct LanguageRegistry {
    parsers: HashMap<String, Arc<dyn LanguageParser>>,
    ext_map: HashMap<String, String>,  // ext -> language name
}

impl Default for LanguageRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageRegistry {
    pub fn new() -> Self {
        let mut registry = Self {
            parsers: HashMap::new(),
            ext_map: HashMap::new(),
        };

        // 注册内置语言解析器
        registry.register(Box::new(PythonParser));
        registry.register(Box::new(JavaScriptParser));
        registry.register(Box::new(TypeScriptParser));
        registry.register(Box::new(RustParser));
        registry.register(Box::new(GoParser));

        registry
    }

    pub fn register(&mut self, parser: Box<dyn LanguageParser>) {
        let name = parser.name().to_string();
        for ext in parser.extensions() {
            self.ext_map.insert(ext.to_string(), name.clone());
        }
        self.parsers.insert(name, parser.into());
    }

    pub fn get_parser(&self, name: &str) -> Option<Arc<dyn LanguageParser>> {
        self.parsers.get(name).cloned()
    }

    pub fn get_parser_by_ext(&self, ext: &str) -> Option<Arc<dyn LanguageParser>> {
        self.ext_map.get(ext).and_then(|name| self.parsers.get(name).cloned())
    }

    /// 获取所有支持的扩展名
    pub fn supported_extensions(&self) -> Vec<String> {
        self.ext_map.keys().cloned().collect()
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 全局注册中心实例 - 使用 RwLock 支持运行时注册
// ═══════════════════════════════════════════════════════════════════════════════

pub static GLOBAL_REGISTRY: Lazy<RwLock<LanguageRegistry>> =
    Lazy::new(|| RwLock::new(LanguageRegistry::new()));

/// 获取全局注册中心
pub fn get_registry() -> parking_lot::RwLockReadGuard<'static, LanguageRegistry> {
    GLOBAL_REGISTRY.read()
}

/// 注册自定义语言（运行时扩展）
pub fn register_language(parser: Box<dyn LanguageParser>) {
    let mut registry = GLOBAL_REGISTRY.write();
    registry.register(parser);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 工具函数 - 兼容原有接口
// ═══════════════════════════════════════════════════════════════════════════════

fn node_text<'a>(node: &tree_sitter::Node, source: &'a [u8]) -> &'a str {
    node.utf8_text(source).unwrap_or("")
}

fn find_child_by_kind<'a>(
    node: &'a tree_sitter::Node<'a>,
    kind: &str,
) -> Option<tree_sitter::Node<'a>> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == kind {
            return Some(child);
        }
    }
    None
}

fn collect_children_by_kind<'a>(
    node: &'a tree_sitter::Node<'a>,
    kind: &str,
    source: &[u8],
) -> Vec<String> {
    let mut result = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == kind {
            result.push(node_text(&child, source).to_string());
        }
    }
    result
}

// ═══════════════════════════════════════════════════════════════════════════════
// 通用 import 提取 - 所有语言通用
// ═══════════════════════════════════════════════════════════════════════════════

fn extract_import(node: &tree_sitter::Node, source: &[u8]) -> AstImport {
    let statement = node_text(node, source).to_string();
    let line = node.start_position().row + 1;

    AstImport {
        statement: statement.clone(),
        module: statement.clone(),
        names: Vec::new(),
        line,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Python 解析器
// ═══════════════════════════════════════════════════════════════════════════════

pub struct PythonParser;

impl LanguageParser for PythonParser {
    fn name(&self) -> &str { "python" }
    fn extensions(&self) -> Vec<&'static str> { vec!["py", "pyi", "pyx"] }

    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>) {
        let mut parser = tree_sitter::Parser::new();
        let lang = tree_sitter_python::LANGUAGE.into();
        parser.set_language(&lang).unwrap();

        let mut signatures = Vec::new();
        let mut imports = Vec::new();

        if let Some(tree) = parser.parse(source, None) {
            let mut cursor = tree.walk();
            for node in tree.root_node().children(&mut cursor) {
                match node.kind() {
                    "import_statement" | "import_from_statement" => {
                        imports.push(extract_import(&node, source));
                    },
                    "class_definition" => {
                        if let Some(sig) = parse_python_class(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "function_definition" => {
                        if let Some(sig) = parse_python_function(&node, source, None) {
                            signatures.push(sig);
                        }
                    },
                    _ => {}
                }
            }
        }
        (signatures, imports)
    }
}

fn parse_python_class(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut methods = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_definition" {
            if let Some(name_node) = find_child_by_kind(&child, "identifier") {
                methods.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let decorators = collect_children_by_kind(node, "decorator", source);

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "class".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields: Vec::new(),
        methods,
        decorators,
    })
}

fn parse_python_function(node: &tree_sitter::Node, source: &[u8], parent: Option<String>) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut params = Vec::new();
    let mut return_type = None;

    if let Some(params_node) = find_child_by_kind(node, "parameters") {
        for child in params_node.children(&mut tree_sitter::Node::walk(&params_node)) {
            if child.kind() == "identifier" {
                params.push(node_text(&child, source).to_string());
            }
        }
    }

    if let Some(ann) = find_child_by_kind(node, "annotation") {
        return_type = Some(node_text(&ann, source).to_string());
    }

    let exported = !name.starts_with('_');
    let decorators = collect_children_by_kind(node, "decorator", source);

    Some(AstSignature {
        name,
        kind: "function".to_string(),
        params,
        return_type,
        line,
        end_line,
        exported,
        parent,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators,
    })
}

// ═══════════════════════════════════════════════════════════════════════════════
// JavaScript 解析器
// ═══════════════════════════════════════════════════════════════════════════════

pub struct JavaScriptParser;

impl LanguageParser for JavaScriptParser {
    fn name(&self) -> &str { "javascript" }
    fn extensions(&self) -> Vec<&'static str> { vec!["js", "jsx", "mjs", "cjs"] }

    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>) {
        let mut parser = tree_sitter::Parser::new();
        let lang = tree_sitter_javascript::LANGUAGE.into();
        parser.set_language(&lang).unwrap();

        let mut signatures = Vec::new();
        let mut imports = Vec::new();

        if let Some(tree) = parser.parse(source, None) {
            let mut cursor = tree.walk();
            for node in tree.root_node().children(&mut cursor) {
                match node.kind() {
                    "import_statement" | "export_statement" => {
                        imports.push(extract_import(&node, source));
                    },
                    "class_declaration" => {
                        if let Some(sig) = parse_js_class(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "function_declaration" => {
                        if let Some(sig) = parse_js_function(&node, source, None) {
                            signatures.push(sig);
                        }
                    },
                    "variable_declaration" => {
                        if let Some(sig) = parse_js_variable(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    _ => {}
                }
            }
        }
        (signatures, imports)
    }
}

fn parse_js_class(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut methods = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "method_definition" {
            if let Some(name_node) = find_child_by_kind(&child, "property_identifier") {
                methods.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "class".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields: Vec::new(),
        methods,
        decorators: Vec::new(),
    })
}

fn parse_js_function(node: &tree_sitter::Node, source: &[u8], parent: Option<String>) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut params = Vec::new();
    if let Some(params_node) = find_child_by_kind(node, "formal_parameters") {
        let mut c = params_node.walk();
        for child in params_node.children(&mut c) {
            if child.kind() == "identifier" {
                params.push(node_text(&child, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "function".to_string(),
        params,
        return_type: None,
        line,
        end_line,
        exported,
        parent,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_js_variable(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "variable_declarator" {
            let name = find_child_by_kind(&child, "identifier")
                .map(|n| node_text(&n, source).to_string())?;
            let line = node.start_position().row + 1;

            let exported = !name.starts_with('_');

            return Some(AstSignature {
                name,
                kind: "variable".to_string(),
                params: Vec::new(),
                return_type: None,
                line,
                end_line: line,
                exported,
                parent: None,
                fields: Vec::new(),
                methods: Vec::new(),
                decorators: Vec::new(),
            });
        }
    }
    None
}

// ═══════════════════════════════════════════════════════════════════════════════
// TypeScript 解析器
// ═══════════════════════════════════════════════════════════════════════════════

pub struct TypeScriptParser;

impl LanguageParser for TypeScriptParser {
    fn name(&self) -> &str { "typescript" }
    fn extensions(&self) -> Vec<&'static str> { vec!["ts", "tsx"] }

    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>) {
        let mut parser = tree_sitter::Parser::new();

        // 判断是 TSX 还是普通 TS
        let has_tsx = source.windows(3).any(|w| w == b"tsx" || w == b"<T");
        let lang = if has_tsx {
            tree_sitter_typescript::LANGUAGE_TSX.into()
        } else {
            tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()
        };
        parser.set_language(&lang).unwrap();

        let mut signatures = Vec::new();
        let mut imports = Vec::new();

        if let Some(tree) = parser.parse(source, None) {
            let mut cursor = tree.walk();
            for node in tree.root_node().children(&mut cursor) {
                match node.kind() {
                    "import_statement" | "import_clause" | "export_clause" => {
                        imports.push(extract_import(&node, source));
                    },
                    "class_declaration" => {
                        if let Some(sig) = parse_ts_class(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "function_declaration" => {
                        if let Some(sig) = parse_ts_function(&node, source, None) {
                            signatures.push(sig);
                        }
                    },
                    "interface_declaration" => {
                        if let Some(sig) = parse_ts_interface(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "type_alias_declaration" => {
                        if let Some(sig) = parse_ts_type_alias(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "enum_declaration" => {
                        if let Some(sig) = parse_ts_enum(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    _ => {}
                }
            }
        }
        (signatures, imports)
    }
}

fn parse_ts_class(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "type_identifier")
        .or_else(|| find_child_by_kind(node, "identifier"))
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut methods = Vec::new();
    let mut fields = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "method_definition" => {
                if let Some(name_node) = find_child_by_kind(&child, "property_identifier") {
                    methods.push(node_text(&name_node, source).to_string());
                }
            },
            "public_field_definition" | "field_declaration" => {
                if let Some(name_node) = find_child_by_kind(&child, "property_identifier") {
                    fields.push(node_text(&name_node, source).to_string());
                }
            },
            _ => {}
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "class".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields,
        methods,
        decorators: Vec::new(),
    })
}

fn parse_ts_function(node: &tree_sitter::Node, source: &[u8], parent: Option<String>) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut params = Vec::new();
    let mut return_type = None;

    if let Some(params_node) = find_child_by_kind(node, "formal_parameters") {
        let mut c = params_node.walk();
        for child in params_node.children(&mut c) {
            if child.kind() == "identifier" {
                params.push(node_text(&child, source).to_string());
            }
        }
    }

    if let Some(ann) = find_child_by_kind(node, "type_annotation") {
        return_type = Some(node_text(&ann, source).to_string());
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "function".to_string(),
        params,
        return_type,
        line,
        end_line,
        exported,
        parent,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_ts_interface(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "type_identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut fields = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "property_signature" {
            if let Some(name_node) = find_child_by_kind(&child, "property_identifier") {
                fields.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "interface".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields,
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_ts_type_alias(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "type_identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "type".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_ts_enum(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut fields = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "enum_member" {
            if let Some(name_node) = find_child_by_kind(&child, "property_identifier") {
                fields.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "enum".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields,
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

// ═══════════════════════════════════════════════════════════════════════════════
// Rust 解析器
// ═══════════════════════════════════════════════════════════════════════════════

pub struct RustParser;

impl LanguageParser for RustParser {
    fn name(&self) -> &str { "rust" }
    fn extensions(&self) -> Vec<&'static str> { vec!["rs"] }

    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>) {
        let mut parser = tree_sitter::Parser::new();
        let lang = tree_sitter_rust::LANGUAGE.into();
        parser.set_language(&lang).unwrap();

        let mut signatures = Vec::new();
        let mut imports = Vec::new();

        if let Some(tree) = parser.parse(source, None) {
            let mut cursor = tree.walk();
            for node in tree.root_node().children(&mut cursor) {
                match node.kind() {
                    "use_declaration" => {
                        imports.push(extract_import(&node, source));
                    },
                    "struct_item" => {
                        if let Some(sig) = parse_rs_struct(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "enum_item" => {
                        if let Some(sig) = parse_rs_enum(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "function_item" => {
                        if let Some(sig) = parse_rs_function(&node, source, None) {
                            signatures.push(sig);
                        }
                    },
                    "impl_item" => {
                        if let Some(sigs) = parse_rs_impl(&node, source) {
                            signatures.extend(sigs);
                        }
                    },
                    _ => {}
                }
            }
        }
        (signatures, imports)
    }
}

fn parse_rs_struct(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut fields = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "field_declaration" {
            if let Some(name_node) = find_child_by_kind(&child, "identifier") {
                fields.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "struct".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields,
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_rs_enum(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut fields = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "enum_variant" {
            if let Some(name_node) = find_child_by_kind(&child, "identifier") {
                fields.push(node_text(&name_node, source).to_string());
            }
        }
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "enum".to_string(),
        params: Vec::new(),
        return_type: None,
        line,
        end_line,
        exported,
        parent: None,
        fields,
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_rs_function(node: &tree_sitter::Node, source: &[u8], parent: Option<String>) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut params = Vec::new();
    let mut return_type = None;

    if let Some(params_node) = find_child_by_kind(node, "parameters") {
        let mut c = params_node.walk();
        for child in params_node.children(&mut c) {
            if child.kind() == "identifier" {
                params.push(node_text(&child, source).to_string());
            }
        }
    }

    if let Some(ret) = find_child_by_kind(node, "type_annotation") {
        return_type = Some(node_text(&ret, source).to_string());
    }

    let exported = !name.starts_with('_');

    Some(AstSignature {
        name,
        kind: "function".to_string(),
        params,
        return_type,
        line,
        end_line,
        exported,
        parent,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_rs_impl(node: &tree_sitter::Node, source: &[u8]) -> Option<Vec<AstSignature>> {
    let type_node = find_child_by_kind(node, "type_identifier")
        .or_else(|| find_child_by_kind(node, "primitive_type"))?;
    let parent = Some(node_text(&type_node, source).to_string());

    let mut signatures = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_item" {
            if let Some(sig) = parse_rs_function(&child, source, parent.clone()) {
                signatures.push(sig);
            }
        }
    }

    if signatures.is_empty() { None } else { Some(signatures) }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Go 解析器
// ═══════════════════════════════════════════════════════════════════════════════

pub struct GoParser;

impl LanguageParser for GoParser {
    fn name(&self) -> &str { "go" }
    fn extensions(&self) -> Vec<&'static str> { vec!["go"] }

    fn parse(&self, source: &[u8]) -> (Vec<AstSignature>, Vec<AstImport>) {
        let mut parser = tree_sitter::Parser::new();
        let lang = tree_sitter_go::LANGUAGE.into();
        parser.set_language(&lang).unwrap();

        let mut signatures = Vec::new();
        let mut imports = Vec::new();

        if let Some(tree) = parser.parse(source, None) {
            let mut cursor = tree.walk();
            for node in tree.root_node().children(&mut cursor) {
                match node.kind() {
                    "import_declaration" => {
                        imports.push(extract_import(&node, source));
                    },
                    "type_declaration" => {
                        if let Some(sigs) = parse_go_type(&node, source) {
                            signatures.extend(sigs);
                        }
                    },
                    "function_declaration" => {
                        if let Some(sig) = parse_go_function(&node, source, None) {
                            signatures.push(sig);
                        }
                    },
                    "method_declaration" => {
                        if let Some(sig) = parse_go_method(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "var_declaration" => {
                        if let Some(sig) = parse_go_var(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    "const_declaration" => {
                        if let Some(sig) = parse_go_const(&node, source) {
                            signatures.push(sig);
                        }
                    },
                    _ => {}
                }
            }
        }
        (signatures, imports)
    }
}

fn parse_go_type(node: &tree_sitter::Node, source: &[u8]) -> Option<Vec<AstSignature>> {
    let mut signatures = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_spec" => {
                let name = find_child_by_kind(&child, "type_identifier")
                    .or_else(|| find_child_by_kind(&child, "identifier"))
                    .map(|n| node_text(&n, source).to_string())?;
                let line = child.start_position().row + 1;
                let end_line = child.end_position().row + 1;

                let kind = if find_child_by_kind(&child, "field_declaration_list").is_some() {
                    "struct"
                } else if find_child_by_kind(&child, "literal_type").is_some() {
                    "interface"
                } else {
                    "type"
                };

                let exported = !name.starts_with('_');

                signatures.push(AstSignature {
                    name,
                    kind: kind.to_string(),
                    params: Vec::new(),
                    return_type: None,
                    line,
                    end_line,
                    exported,
                    parent: None,
                    fields: Vec::new(),
                    methods: Vec::new(),
                    decorators: Vec::new(),
                });
            },
            _ => {}
        }
    }

    if signatures.is_empty() { None } else { Some(signatures) }
}

fn parse_go_function(node: &tree_sitter::Node, source: &[u8], parent: Option<String>) -> Option<AstSignature> {
    let name = find_child_by_kind(node, "identifier")
        .map(|n| node_text(&n, source).to_string())?;
    let line = node.start_position().row + 1;
    let end_line = node.end_position().row + 1;

    let mut params = Vec::new();
    let mut return_type = None;

    if let Some(params_node) = find_child_by_kind(node, "parameter_list") {
        let mut c = params_node.walk();
        for child in params_node.children(&mut c) {
            if child.kind() == "parameter_declaration" {
                if let Some(name_node) = find_child_by_kind(&child, "identifier") {
                    params.push(node_text(&name_node, source).to_string());
                }
            }
        }
    }

    if let Some(ret) = find_child_by_kind(node, "result") {
        if let Some(type_node) = find_child_by_kind(&ret, "type_identifier") {
            return_type = Some(node_text(&type_node, source).to_string());
        }
    }

    Some(AstSignature {
        name: name.clone(),
        kind: "function".to_string(),
        params,
        return_type,
        line,
        end_line,
        exported: name.chars().next().map(|c| c.is_uppercase()).unwrap_or(false),
        parent,
        fields: Vec::new(),
        methods: Vec::new(),
        decorators: Vec::new(),
    })
}

fn parse_go_method(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let receiver_node = find_child_by_kind(node, "parameter_list")?;
    let type_node = find_child_by_kind(&receiver_node, "identifier")?;
    let parent = Some(node_text(&type_node, source).to_string());

    parse_go_function(node, source, parent)
}

fn parse_go_var(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "var_declarator" {
            let name = find_child_by_kind(&child, "identifier")
                .map(|n| node_text(&n, source).to_string())?;
            let line = node.start_position().row + 1;
            let exported = !name.starts_with('_');

            return Some(AstSignature {
                name,
                kind: "variable".to_string(),
                params: Vec::new(),
                return_type: None,
                line,
                end_line: line,
                exported,
                parent: None,
                fields: Vec::new(),
                methods: Vec::new(),
                decorators: Vec::new(),
            });
        }
    }
    None
}

fn parse_go_const(node: &tree_sitter::Node, source: &[u8]) -> Option<AstSignature> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "const_declarator" {
            let name = find_child_by_kind(&child, "identifier")
                .map(|n| node_text(&n, source).to_string())?;
            let line = node.start_position().row + 1;
            let exported = !name.starts_with('_');

            return Some(AstSignature {
                name,
                kind: "const".to_string(),
                params: Vec::new(),
                return_type: None,
                line,
                end_line: line,
                exported,
                parent: None,
                fields: Vec::new(),
                methods: Vec::new(),
                decorators: Vec::new(),
            });
        }
    }
    None
}

// ═══════════════════════════════════════════════════════════════════════════════
// 兼容层 API - 向后兼容原有接口
// ═══════════════════════════════════════════════════════════════════════════════

/// 解析单个文件，返回 AST 结构和 imports
pub fn parse_file(source: &[u8], ext: &str) -> AstParseResult {
    let (language, signatures, imports) = match ext {
        "py" | "pyi" | "pyx" => {
            let parser = PythonParser;
            let (sigs, imps) = parser.parse(source);
            ("python".to_string(), sigs, imps)
        },
        "js" | "jsx" | "mjs" | "cjs" => {
            let parser = JavaScriptParser;
            let (sigs, imps) = parser.parse(source);
            ("javascript".to_string(), sigs, imps)
        },
        "ts" | "tsx" => {
            let parser = TypeScriptParser;
            let (sigs, imps) = parser.parse(source);
            ("typescript".to_string(), sigs, imps)
        },
        "rs" => {
            let parser = RustParser;
            let (sigs, imps) = parser.parse(source);
            ("rust".to_string(), sigs, imps)
        },
        "go" => {
            let parser = GoParser;
            let (sigs, imps) = parser.parse(source);
            ("go".to_string(), sigs, imps)
        },
        _ => ("unknown".to_string(), Vec::new(), Vec::new()),
    };

    AstParseResult {
        file: String::new(),
        language,
        signatures,
        imports,
        errors: Vec::new(),
    }
}

/// 根据扩展名获取语言信息
pub fn get_language_info(ext: &str) -> Option<(&'static str, &'static str)> {
    match ext {
        "py" | "pyi" | "pyx" => Some(("python", "Python")),
        "js" | "jsx" | "mjs" | "cjs" => Some(("javascript", "JavaScript")),
        "ts" | "tsx" => Some(("typescript", "TypeScript")),
        "rs" => Some(("rust", "Rust")),
        "go" => Some(("go", "Go")),
        _ => None,
    }
}

/// 列出所有支持的语言
pub fn list_supported_languages() -> Vec<(&'static str, &'static str)> {
    vec![
        ("python", "Python"),
        ("javascript", "JavaScript"),
        ("typescript", "TypeScript"),
        ("rust", "Rust"),
        ("go", "Go"),
    ]
}

/// 解析源码字符串
pub fn parse_source(source: &str, ext: &str) -> AstParseResult {
    parse_file(source.as_bytes(), ext)
}

/// 获取文件扩展名对应的语言
pub fn get_language_by_ext(ext: &str) -> Option<&'static str> {
    match ext {
        "py" | "pyi" | "pyx" => Some("python"),
        "js" | "jsx" | "mjs" | "cjs" => Some("javascript"),
        "ts" | "tsx" => Some("typescript"),
        "rs" => Some("rust"),
        "go" => Some("go"),
        _ => None,
    }
}

/// 检查扩展名是否支持
pub fn is_supported(ext: &str) -> bool {
    matches!(ext,
        "py" | "pyi" | "pyx" |
        "js" | "jsx" | "mjs" | "cjs" |
        "ts" | "tsx" |
        "rs" |
        "go"
    )
}

/// 异步封装 - 解析文件并返回 AST 结果
pub async fn tool_ast_parse(path: String) -> AstParseResult {
    let path_ref: &Path = Path::new(&path);
    let ext = path_ref.extension()
        .and_then(|e| e.to_str())
        .unwrap_or("");

    let source = match std::fs::read(&path) {
        Ok(s) => s,
        Err(e) => return AstParseResult {
            file: path,
            language: "unknown".to_string(),
            signatures: Vec::new(),
            imports: Vec::new(),
            errors: vec![e.to_string()],
        },
    };

    let mut result = parse_file(&source, ext);
    result.file = path;
    result
}

// ═══════════════════════════════════════════════════════════════════════════════
// 扩展名注册表 - 可配置扩展名映射
// ═══════════════════════════════════════════════════════════════════════════════

/// 从 stack.json 读取语言和扩展名配置
pub fn load_extension_map_from_config(config: &serde_json::Value) -> HashMap<String, String> {
    let mut map = HashMap::new();

    if let Some(lang_config) = config.get("language") {
        if let Some(exts) = lang_config.get("extensions").and_then(|e| e.as_array()) {
            for ext in exts {
                if let Some(ext_str) = ext.as_str() {
                    if let Some(name) = lang_config.get("name").and_then(|n| n.as_str()) {
                        map.insert(ext_str.to_string(), name.to_string());
                    }
                }
            }
        }
    }

    // 如果没有配置，使用默认映射
    if map.is_empty() {
        map.insert("py".to_string(), "python".to_string());
        map.insert("js".to_string(), "javascript".to_string());
        map.insert("ts".to_string(), "typescript".to_string());
        map.insert("rs".to_string(), "rust".to_string());
        map.insert("go".to_string(), "go".to_string());
    }

    map
}