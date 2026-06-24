# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pipeline
file: pipeline/LocalGate.py
responsibility: 通用薄门禁 - 契约驱动的确定性检测
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
import json
import py_compile
import importlib.util
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None


DEFAULT_CONTRACT = {
    "required_files": [],
    "check_anchors": True,
    "check_logging": True,
    "structured_files": [],
}


class LocalGate:
    """
    通用薄门禁

    只检查 100% 确定性事实，输入来自契约而非模块硬编码。
    """

    ANCHOR_START = "<YGA_FILE_ANCHOR"
    ANCHOR_END = "<YGA_END_ANCHOR"

    LOGGING_MARKERS = {
        "logging_import": "logging",
        "logging_config": ("basicConfig", "FileHandler"),
        "app_log": "app.log",
        "error_log": "error.log",
        "error_stack": ("logger.error", "exc_info=True"),
    }

    def __init__(self):
        self.results: Dict = {}

    @staticmethod
    def parse_contract_from_interfaces(interfaces: str) -> Dict:
        """从接口文档提取薄门禁契约"""
        contract = dict(DEFAULT_CONTRACT)
        required: List[str] = []

        for match in re.findall(r"`([^`]+\.(?:py|json|yaml|yml))`", interfaces):
            if match not in required:
                required.append(match)

        for match in re.findall(
            r"^\s*\d+\.\s*`([^`]+\.(?:py|json|yaml|yml))`",
            interfaces,
            re.MULTILINE,
        ):
            if match not in required:
                required.append(match)

        contract["required_files"] = required
        structured = [
            name for name in required if name.endswith((".json", ".yaml", ".yml"))
        ]
        if structured:
            contract["structured_files"] = structured
        return contract

    @staticmethod
    def merge_contract(contract: Optional[Dict] = None) -> Dict:
        merged = dict(DEFAULT_CONTRACT)
        if contract:
            merged.update(contract)
        return merged

    def run(self, code_dir: Path, contract: Optional[Dict] = None) -> Dict:
        """运行契约驱动的本地薄门禁"""
        code_dir = Path(code_dir)
        contract = self.merge_contract(contract)

        self.results = {
            "files": {"name": "文件检查", "passed": False, "details": ""},
            "syntax": {"name": "语法检查", "passed": False, "details": ""},
            "import": {"name": "导入检查", "passed": False, "details": ""},
            "compile": {"name": "编译检查", "passed": False, "details": ""},
            "format": {"name": "格式检查", "passed": False, "details": ""},
            "anchors": {"name": "锚点检查", "passed": False, "details": ""},
            "logging": {"name": "日志基础检查", "passed": False, "details": ""},
        }

        py_files = sorted(code_dir.glob("*.py"))
        if not py_files and not contract.get("required_files"):
            self.results["files"]["details"] = "没有找到 Python 文件"
            self.results["all_passed"] = False
            return self.results

        self._check_files(code_dir, contract)
        if py_files:
            self._check_syntax(py_files)
            self._check_import(py_files, code_dir)
            self._check_compile(py_files)
        else:
            for key in ("syntax", "import", "compile"):
                self.results[key]["passed"] = True
                self.results[key]["details"] = "无 Python 文件，跳过"

        self._check_structured_files(code_dir, contract)

        if contract.get("check_anchors", True) and py_files:
            self._check_anchors(py_files)
        else:
            self.results["anchors"]["passed"] = True
            self.results["anchors"]["details"] = "未启用锚点检查"

        if contract.get("check_logging", True) and py_files:
            self._check_logging(py_files)
        else:
            self.results["logging"]["passed"] = True
            self.results["logging"]["details"] = "未启用日志检查"

        self.results["all_passed"] = all(
            r.get("passed", False)
            for r in self.results.values()
            if isinstance(r, dict)
        )
        return self.results

    def _check_files(self, code_dir: Path, contract: Dict):
        """检查文件是否存在且可按 UTF-8 读取"""
        errors = []
        required = contract.get("required_files") or []

        if not required:
            py_files = list(code_dir.glob("*.py"))
            if not py_files:
                errors.append("代码目录中没有 Python 文件")
            else:
                for py_file in py_files:
                    ok, err = self._read_utf8(py_file)
                    if not ok:
                        errors.append(err)
        else:
            for rel_path in required:
                file_path = code_dir / rel_path
                if not file_path.exists():
                    errors.append(f"缺少契约要求的文件: {rel_path}")
                    continue
                ok, err = self._read_utf8(file_path)
                if not ok:
                    errors.append(err)

        if not errors:
            count = len(required) if required else len(list(code_dir.glob("*.py")))
            self.results["files"]["passed"] = True
            self.results["files"]["details"] = f"已检查 {count} 个文件，均可读取"
        else:
            self.results["files"]["details"] = "\n".join(errors)

    @staticmethod
    def _read_utf8(file_path: Path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                f.read()
            return True, ""
        except UnicodeDecodeError:
            return False, f"文件无法按 UTF-8 读取: {file_path.name}"
        except OSError as e:
            return False, f"读取文件失败 {file_path.name}: {e}"

    def _check_structured_files(self, code_dir: Path, contract: Dict):
        """检查 JSON/YAML 是否能解析"""
        structured = contract.get("structured_files") or []
        if not structured:
            self.results["format"]["passed"] = True
            self.results["format"]["details"] = "无结构化文件，跳过"
            return

        errors = []
        for rel_path in structured:
            file_path = code_dir / rel_path
            if not file_path.exists():
                errors.append(f"结构化文件不存在: {rel_path}")
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if rel_path.endswith(".json"):
                    json.loads(content)
                elif rel_path.endswith((".yaml", ".yml")):
                    if yaml is None:
                        errors.append(f"缺少 PyYAML，无法解析: {rel_path}")
                    else:
                        yaml.safe_load(content)
            except json.JSONDecodeError as e:
                errors.append(f"{rel_path}: JSON 解析失败 ({e})")
            except Exception as e:
                if yaml and hasattr(yaml, "YAMLError") and isinstance(e, yaml.YAMLError):
                    errors.append(f"{rel_path}: YAML 解析失败 ({e})")
                else:
                    errors.append(f"{rel_path}: 解析失败 ({e})")

        if not errors:
            self.results["format"]["passed"] = True
            self.results["format"]["details"] = f"所有 {len(structured)} 个结构化文件解析成功"
        else:
            self.results["format"]["details"] = "\n".join(errors)

    def _check_syntax(self, py_files: List[Path]):
        errors = []
        for py_file in py_files:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{py_file.name}: {e}")

        if not errors:
            self.results["syntax"]["passed"] = True
            self.results["syntax"]["details"] = f"所有 {len(py_files)} 个文件语法正确"
        else:
            self.results["syntax"]["details"] = "\n".join(errors)

    def _check_import(self, py_files: List[Path], code_dir: Path):
        errors = []
        for py_file in py_files:
            try:
                if str(code_dir) not in sys.path:
                    sys.path.insert(0, str(code_dir))

                spec = importlib.util.spec_from_file_location(py_file.stem, str(py_file))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                error_msg = str(e)
                if "SyntaxError" in error_msg or "IndentationError" in error_msg:
                    errors.append(f"{py_file.name}: {e}")
                elif not any(dep in error_msg for dep in ["No module named", "ImportError"]):
                    errors.append(f"{py_file.name}: {e}")

        if not errors:
            self.results["import"]["passed"] = True
            self.results["import"]["details"] = f"所有 {len(py_files)} 个文件导入成功"
        else:
            self.results["import"]["details"] = "\n".join(errors)

    def _check_compile(self, py_files: List[Path]):
        errors = []
        for py_file in py_files:
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    code = f.read()
                compile(code, str(py_file), "exec")
            except SyntaxError as e:
                errors.append(f"{py_file.name}: {e}")

        if not errors:
            self.results["compile"]["passed"] = True
            self.results["compile"]["details"] = f"所有 {len(py_files)} 个文件编译成功"
        else:
            self.results["compile"]["details"] = "\n".join(errors)

    def _check_anchors(self, py_files: List[Path]):
        errors = []
        for py_file in py_files:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
            if self.ANCHOR_START not in content:
                errors.append(f"{py_file.name}: 缺少 YGA_FILE_ANCHOR")
            if self.ANCHOR_END not in content:
                errors.append(f"{py_file.name}: 缺少 YGA_END_ANCHOR")

        if not errors:
            self.results["anchors"]["passed"] = True
            self.results["anchors"]["details"] = f"所有 {len(py_files)} 个文件锚点完整"
        else:
            self.results["anchors"]["details"] = "\n".join(errors)

    def _check_logging(self, py_files: List[Path]):
        combined = ""
        for py_file in py_files:
            with open(py_file, "r", encoding="utf-8") as f:
                combined += f.read() + "\n"

        missing = []
        if self.LOGGING_MARKERS["logging_import"] not in combined:
            missing.append("缺少 logging 导入")

        config_markers = self.LOGGING_MARKERS["logging_config"]
        if not any(marker in combined for marker in config_markers):
            missing.append("缺少 basicConfig 或 FileHandler 日志配置")

        if self.LOGGING_MARKERS["app_log"] not in combined:
            missing.append("缺少 app.log 配置")

        if self.LOGGING_MARKERS["error_log"] not in combined:
            missing.append("缺少 error.log 配置")

        stack_markers = self.LOGGING_MARKERS["error_stack"]
        if not all(marker in combined for marker in stack_markers):
            missing.append("缺少 logger.error(..., exc_info=True) 错误堆栈记录")

        logs_dir_ref = "logs"
        if logs_dir_ref not in combined:
            missing.append("缺少 logs/ 日志目录引用")

        if not missing:
            self.results["logging"]["passed"] = True
            self.results["logging"]["details"] = "日志基础能力检查通过"
        else:
            self.results["logging"]["details"] = "；".join(missing)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>
