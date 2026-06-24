# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pmc
file: pmc/PmcBlueprint.py
responsibility: AI 蓝图接收与确定性校验、落盘（不做业务模块拆分）
exports: PmcBlueprint
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from pathlib import Path
from typing import Dict, List, Tuple
from copy import deepcopy

import yaml


class PmcBlueprint:
    """处理 AI 明确给出的项目蓝图，本地代码只做确定性结构处理。"""

    OUTPUT_DIR = Path(__file__).parent.parent / "output"
    REQUIRED_TOP_LEVEL_KEYS = [
        "project_map",
        "module_cards",
        "interface_registry",
        "dependency_graph",
        "batch_plan",
        "assembly",
    ]

    @classmethod
    def from_ai_blueprint(cls, session_id: str, project: Dict, ai_blueprint: Dict) -> Dict:
        """接收 AI 蓝图并补齐机械元数据；不根据需求推断模块。"""
        if not ai_blueprint:
            return {}

        blueprint = deepcopy(ai_blueprint)
        blueprint.setdefault("version", "1.0")
        blueprint["session_id"] = session_id
        blueprint.setdefault("project", {
            "name": project.get("project_name") or "未命名项目",
            "tech_stack": project.get("tech_stack") or "",
        })
        blueprint.setdefault("rules", {})
        blueprint["rules"].update({
            "module_split_owner": "AI",
            "local_code_role": "validate_and_persist_only",
            "single_interface_ledger": "interfaces/index.yaml",
            "code_development_scope": "only modules in the active batch enter code generation",
            "assembler_rule": "assembler reads assembly.yaml and interfaces/index.yaml, not module internals",
        })

        cls._attach_mechanical_metadata(session_id, blueprint)
        return blueprint

    @classmethod
    def validate(cls, blueprint: Dict) -> Tuple[List[str], List[str]]:
        """确定性校验蓝图结构和引用关系。"""
        issues = []
        suggestions = []

        if not blueprint:
            return issues, suggestions

        for key in cls.REQUIRED_TOP_LEVEL_KEYS:
            if key not in blueprint:
                issues.append(f"项目蓝图缺少 {key}")

        modules = blueprint.get("module_cards", [])
        registry = blueprint.get("interface_registry", {})
        dependency_graph = blueprint.get("dependency_graph", {})
        batch_plan = blueprint.get("batch_plan", {})
        assembly = blueprint.get("assembly", {})

        if not isinstance(modules, list) or not modules:
            issues.append("项目蓝图缺少模块卡片")
            return issues, suggestions

        module_ids = [module.get("id") for module in modules]
        missing_module_ids = [index for index, module_id in enumerate(module_ids, start=1) if not module_id]
        if missing_module_ids:
            issues.append(f"模块卡片缺少 id: {missing_module_ids}")

        normalized_module_ids = [module_id for module_id in module_ids if module_id]
        module_id_set = set(normalized_module_ids)
        if len(normalized_module_ids) != len(module_id_set):
            issues.append("模块卡片存在重复 module id")

        for module in modules:
            for field in ("name", "responsibility", "public_interfaces", "depends_on", "status"):
                if field not in module:
                    issues.append(f"模块 {module.get('id', '<unknown>')} 缺少字段 {field}")
            for dep in module.get("depends_on", []):
                if dep not in module_id_set:
                    issues.append(f"模块 {module.get('id')} 依赖不存在的模块 {dep}")

        public_interfaces = registry.get("public_interfaces", [])
        if not isinstance(public_interfaces, list) or not public_interfaces:
            issues.append("项目蓝图缺少统一接口总账")
        interface_ids = [item.get("id") for item in public_interfaces if item.get("id")]
        if len(interface_ids) != len(set(interface_ids)):
            issues.append("接口总账存在重复 interface id")

        interface_id_set = set(interface_ids)
        interface_by_id = {}
        for item in public_interfaces:
            if not item.get("id"):
                issues.append("接口总账存在缺少 id 的接口")
            else:
                interface_by_id[item.get("id")] = item
            if item.get("owner_module") not in module_id_set:
                issues.append(f"接口 {item.get('id')} 指向不存在的模块 {item.get('owner_module')}")
            for field in ("method", "path"):
                if field not in item:
                    issues.append(f"接口 {item.get('id', '<unknown>')} 缺少字段 {field}")

        for module in modules:
            for interface_id in module.get("public_interfaces", []):
                if interface_id not in interface_id_set:
                    issues.append(f"模块 {module.get('id')} 引用了未登记接口 {interface_id}")

        graph_nodes = {node.get("id") for node in dependency_graph.get("nodes", [])}
        if graph_nodes and graph_nodes != module_id_set:
            issues.append("依赖图节点与模块卡片不一致")
        for edge in dependency_graph.get("edges", []):
            if edge.get("from") not in module_id_set or edge.get("to") not in module_id_set:
                issues.append(f"依赖图存在无效边 {edge}")

        batch_modules = [
            module_id
            for batch in batch_plan.get("batches", [])
            for module_id in batch.get("modules", [])
        ]
        module_batch = {}
        for batch_index, batch in enumerate(batch_plan.get("batches", []), start=1):
            for module_id in batch.get("modules", []):
                module_batch[module_id] = (batch.get("id"), batch_index)
        if set(batch_modules) != module_id_set:
            issues.append("批次计划没有覆盖全部模块，或引用了不存在的模块")
        if len(batch_modules) != len(set(batch_modules)):
            issues.append("批次计划中存在重复模块")
        for module in modules:
            module_id = module.get("id")
            current_batch = module_batch.get(module_id)
            for dep in module.get("depends_on", []):
                dep_batch = module_batch.get(dep)
                if not current_batch or not dep_batch:
                    continue
                if dep_batch[1] >= current_batch[1]:
                    issues.append(
                        f"批次计划错误：模块 {module_id} 依赖 {dep}，"
                        f"但依赖不在更早批次"
                    )
        active_batch = batch_plan.get("active_batch")
        batch_ids = {batch.get("id") for batch in batch_plan.get("batches", [])}
        if active_batch and active_batch not in batch_ids:
            issues.append(f"active_batch 不存在: {active_batch}")
        if modules and not active_batch:
            suggestions.append("建议指定 active_batch，避免规划池模块全部进入代码开发区")

        assembly_modules = {item.get("module") for item in assembly.get("module_exports", [])}
        if assembly_modules != module_id_set:
            issues.append("组装清单与模块卡片不一致")
        for item in assembly.get("module_exports", []):
            mount_path = item.get("mount_path")
            if not mount_path:
                issues.append(f"组装清单模块 {item.get('module')} 缺少 mount_path")
            for interface_id in item.get("interfaces", []):
                if interface_id not in interface_id_set:
                    issues.append(f"组装清单引用了未登记接口 {interface_id}")
                    continue
                interface_path = interface_by_id[interface_id].get("path", "")
                if mount_path and interface_path and not cls._path_matches_mount(interface_path, mount_path):
                    issues.append(
                        f"组装清单模块 {item.get('module')} 的 mount_path {mount_path} "
                        f"与接口 {interface_id} 路径 {interface_path} 不一致"
                    )

        return issues, suggestions

    @classmethod
    def write_artifacts(cls, session_id: str, blueprint: Dict) -> Dict[str, str]:
        """写入 PMC 蓝图产物到 output/{session_id}/spec/。"""
        spec_dir = cls.OUTPUT_DIR / session_id / "spec"
        module_cards_dir = spec_dir / "module_cards"
        interfaces_dir = spec_dir / "interfaces"
        module_cards_dir.mkdir(parents=True, exist_ok=True)
        interfaces_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "project_map": spec_dir / "project_map.yaml",
            "interfaces_index": interfaces_dir / "index.yaml",
            "dependency_graph": spec_dir / "dependency_graph.yaml",
            "batch_plan": spec_dir / "batch_plan.yaml",
            "assembly": spec_dir / "assembly.yaml",
            "blueprint": spec_dir / "project_blueprint.yaml",
        }

        cls._write_yaml(files["project_map"], blueprint["project_map"])
        cls._write_yaml(files["interfaces_index"], blueprint["interface_registry"])
        cls._write_yaml(files["dependency_graph"], blueprint["dependency_graph"])
        cls._write_yaml(files["batch_plan"], blueprint["batch_plan"])
        cls._write_yaml(files["assembly"], blueprint["assembly"])
        cls._write_yaml(files["blueprint"], blueprint)

        module_paths = {}
        for module in blueprint["module_cards"]:
            path = module_cards_dir / f"{module['id']}.yaml"
            cls._write_yaml(path, module)
            module_paths[module["id"]] = cls._relative(path)

        artifact_paths = {key: cls._relative(path) for key, path in files.items()}
        artifact_paths["module_cards"] = cls._relative(module_cards_dir)
        artifact_paths["module_card_files"] = module_paths
        return artifact_paths

    @classmethod
    def _attach_mechanical_metadata(cls, session_id: str, blueprint: Dict):
        """只补不会改变业务边界的元数据。"""
        registry = blueprint.get("interface_registry")
        if not isinstance(registry, dict):
            return

        registry.setdefault("version", blueprint.get("version", "1.0"))
        registry["session_id"] = session_id
        registry.setdefault("authority", "interfaces/index.yaml")
        registry.setdefault("rules", {})
        registry["rules"].update({
            "interface_id_unique": True,
            "module_calls_public_interfaces_only": True,
            "assembler_uses_this_ledger": True,
        })

    @staticmethod
    def _write_yaml(path: Path, data: Dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    @staticmethod
    def _relative(path: Path) -> str:
        return str(path.relative_to(Path(__file__).parent.parent)).replace("\\", "/")

    @staticmethod
    def _path_matches_mount(interface_path: str, mount_path: str) -> bool:
        """检查接口路径是否位于组装挂载前缀下。"""
        normalized_interface = interface_path.rstrip("/")
        normalized_mount = mount_path.rstrip("/")
        return (
            normalized_interface == normalized_mount
            or normalized_interface.startswith(normalized_mount + "/")
        )


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 修正：只接收 AI 蓝图并做确定性校验、落盘
# contract: 12_接手文档.md
# next: PmcPlanner/PmcRouter 接入 AI 蓝图输入
# </YGA_END_ANCHOR>
