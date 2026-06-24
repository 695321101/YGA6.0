# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: pmc
file: pmc/PmcLayeredSplitter.py
responsibility: PMC 分层拆分编排器（AI 决策 + AI 审核 + 本地结构验收）
exports: PmcLayeredSplitter, PmcLayeredSplitResult
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
import json

import yaml

from pmc.PmcBlueprint import PmcBlueprint
from pmc.PmcPlanner import PmcPlanner


@dataclass
class PmcLayeredSplitResult:
    """PMC 分层拆分结果。"""
    session_id: str
    project_domains: Dict
    domain_modules: Dict
    blueprint: Dict
    reviews: List[Dict] = field(default_factory=list)
    artifacts: Dict[str, str] = field(default_factory=dict)


class PmcLayeredSplitter:
    """按层调用 AI 拆分项目，本地只做确定性结构验收。"""

    OUTPUT_DIR = Path(__file__).parent.parent / "output"

    SYSTEM_PROMPT = """你是 YGA 的 PMC 分层拆分工作 AI。
你负责给出明确的业务拆分判断，但每次只处理当前层级，不一次性把项目拆到底。

固定背景：
- 当前阶段：PMC 分层拆分。
- 当前区域：规划池。
- 当前模块：分层拆分编排中的当前工作模块。
- 输入来源：用户已确认需求，以及上一层已通过 AI 审核的拆分产物。
- 产物用途：给下一层拆分、PMC 蓝图验收、接口总账、批次计划和后续代码开发使用。
- 后续审查：每层输出都会经过 AI 审查员审核，再由本地做 JSON/引用/唯一性等确定性验收。

硬规则：
- 大项目必须拆小，这是 YGA 控制 AI 生成上下文和降低失败范围的前提。
- 分层流程必须执行，但极小需求可以是一域一叶子模块；不要为了拆分制造伪业务域。
- 你只能输出当前层产物，不要写代码，不要解释实现过程。
- 不要让一个模块承担整个上层功能域的全部职责。
- 不要生成用户没有表达或上层产物没有包含的业务范围。
- 项目域按业务对象或业务功能域拆，不按 CRUD 动作、读写模式、技术层、数据模型定义来拆。
- 模块如果拥有 public_interfaces，就必须负责这些接口对应的对外入口、参数接收和处理编排；not_responsible 不能排除自己公开接口所需的入口职责。
- 输出必须是 JSON 对象，不要 Markdown。"""

    @classmethod
    def split(
        cls,
        session_id: str,
        requirement_content: str,
        require_ai_review: bool = True
    ) -> PmcLayeredSplitResult:
        """执行项目域 -> 域内模块 -> 项目蓝图的分层拆分。"""
        project = PmcPlanner.parse_requirement(requirement_content)

        project_domains = cls._generate_project_domains(requirement_content)
        project_review = cls._review_layer(
            requirement_content,
            "project_domains",
            "项目域拆分",
            project_domains,
            require_ai_review,
        )
        cls._validate_project_domains(project_domains)

        domain_modules = {
            "stage": "domain_modules",
            "domains": [],
        }
        all_module_ids = set()
        for domain in project_domains.get("domains", []):
            module_artifact = cls._generate_domain_modules(requirement_content, domain)
            module_review = cls._review_layer(
                requirement_content,
                "domain_modules",
                f"域内拆分：{domain.get('id', '')}",
                module_artifact,
                require_ai_review,
            )
            cls._validate_domain_modules(domain, module_artifact, all_module_ids)
            domain_modules["domains"].append({
                "domain": domain,
                "modules": module_artifact.get("modules", []),
                "review": module_review,
            })

        blueprint = cls._generate_blueprint(requirement_content, project_domains, domain_modules)
        normalized_blueprint = PmcBlueprint.from_ai_blueprint(session_id, project, blueprint)
        blueprint_review = cls._review_blueprint(
            requirement_content,
            normalized_blueprint,
            require_ai_review,
        )
        cls._validate_blueprint(normalized_blueprint, all_module_ids)

        result = PmcLayeredSplitResult(
            session_id=session_id,
            project_domains=project_domains,
            domain_modules=domain_modules,
            blueprint=normalized_blueprint,
            reviews=[project_review]
            + [item["review"] for item in domain_modules["domains"]]
            + [blueprint_review],
        )
        result.artifacts = cls.write_artifacts(result)
        return result

    @classmethod
    def _generate_project_domains(cls, requirement_content: str) -> Dict:
        prompt = f"""## 当前工作背景
- 当前阶段：PMC 分层拆分 / 项目域拆分。
- 当前区域：规划池。
- 当前模块：项目域拆分模块。
- 输入来源：用户已确认需求。
- 产物用途：只给下一层“域内拆分”使用。
- 边界：只拆大域，不细拆子模块，不设计接口，不写代码；极小需求可以只输出一个大域。

## 拆分原则
- 大项目必须拆小，但项目域是业务边界，不是技术边界。
- 不要把创建、查询、修改、删除、读写模式、数据模型定义拆成项目大域。
- 如果需求只有一个清楚业务对象或业务功能域，输出一个大域即可，下一层可再决定是否只有一个叶子模块。

## 已确认需求
{requirement_content}

## 输出 JSON Schema
{{
  "stage": "project_domains",
  "domains": [
    {{
      "id": "英文小写点号/下划线 id，例如 user 或 order",
      "name": "中文名称",
      "responsibility": "这个大域负责什么",
      "not_responsible": ["这个大域不负责什么"],
      "split_reason": "为什么需要作为独立大域继续下钻",
      "expected_submodule_count": 1
    }}
  ]
}}

请只输出 JSON。"""
        return cls._call_ai_json(prompt, max_tokens=3072)

    @classmethod
    def _generate_domain_modules(cls, requirement_content: str, domain: Dict) -> Dict:
        prompt = f"""## 当前工作背景
- 当前阶段：PMC 分层拆分 / 域内拆分。
- 当前区域：规划池。
- 当前模块：{domain.get('id', '')} 域内子模块拆分。
- 输入来源：用户已确认需求，以及已审核通过的项目域拆分。
- 产物用途：生成叶子模块候选，后续统一回收成模块卡片和接口总账。
- 边界：只拆当前大域，不处理兄弟域，不生成最终接口总账，不写代码；极小域可以只输出一个叶子模块。

## 拆分原则
- 当前域职责很小时，可以输出一个 `domain.core` 模块。
- 只有当当前域内部存在清楚的多职责边界时，才继续拆成多个叶子模块。
- 不要按 CRUD 动作、读写模式、数据库模型或文件类型机械拆模块。
- `not_responsible` 只能写兄弟模块或系统外职责，不能写“HTTP 路由、参数校验、接口处理”等会和后续公开接口 ownership 冲突的内容。

## 已确认需求
{requirement_content}

## 当前大域
{json.dumps(domain, ensure_ascii=False, indent=2)}

## 输出 JSON Schema
{{
  "stage": "domain_modules",
  "domain_id": "{domain.get('id', '')}",
  "modules": [
    {{
      "id": "{domain.get('id', '')}.core",
      "name": "中文名称",
      "responsibility": "这个子模块负责什么",
      "not_responsible": ["这个子模块不负责什么"],
      "public_capabilities": ["对外能力草案，不是最终接口总账"],
      "depends_on": [],
      "status": "planned"
    }}
  ]
}}

请只输出 JSON。"""
        return cls._call_ai_json(prompt, max_tokens=4096)

    @classmethod
    def _generate_blueprint(cls, requirement_content: str, project_domains: Dict, domain_modules: Dict) -> Dict:
        prompt = f"""## 当前工作背景
- 当前阶段：PMC 分层拆分 / 项目蓝图生成。
- 当前区域：规划池 -> 接口总账区。
- 当前模块：项目级蓝图模块。
- 输入来源：已确认需求、已审核项目域、已审核域内叶子模块。
- 产物用途：生成 PMC 可验收的项目地图、模块卡片、统一接口总账、依赖图、批次计划和组装清单。
- 边界：只能使用已给出的叶子模块；不能新增未在上层拆分中出现的模块；不写代码。

## 蓝图一致性原则
- `module_cards[*].public_interfaces` 表示该模块拥有这些公开接口。
- 拥有公开接口的模块必须负责这些接口的入口、参数接收、业务处理编排和返回结果。
- `not_responsible` 不能排除自己公开接口必需的职责，例如“HTTP 路由注册”“参数校验”“接口处理”。
- 如果要表达不负责全局应用启动或跨模块统一网关，可以写成“不负责全局应用启动和跨模块网关配置”，不能否定本模块接口入口。

## 已确认需求
{requirement_content}

## 已审核项目域
{json.dumps(project_domains, ensure_ascii=False, indent=2)}

## 已审核域内模块
{json.dumps(domain_modules, ensure_ascii=False, indent=2)}

## 输出 JSON Schema
{{
  "version": "1.0",
  "project_map": {{
    "project_name": "项目名",
    "module_count": 1,
    "modules": ["模块 id"]
  }},
  "module_cards": [
    {{
      "id": "模块 id，必须来自域内模块",
      "name": "中文名称",
      "responsibility": "职责",
      "not_responsible": ["不负责内容"],
      "public_interfaces": ["interface id"],
      "depends_on": [],
      "status": "planned"
    }}
  ],
  "interface_registry": {{
    "public_interfaces": [
      {{
        "id": "interface id",
        "owner_module": "模块 id",
        "method": "GET/POST/PUT/PATCH/DELETE",
        "path": "/api/..."
      }}
    ],
    "shared_models": []
  }},
  "dependency_graph": {{
    "nodes": [{{"id": "模块 id"}}],
    "edges": [{{"from": "依赖模块 id", "to": "被支持模块 id", "reason": "原因"}}]
  }},
  "batch_plan": {{
    "active_batch": "batch_1",
    "batches": [
      {{"id": "batch_1", "status": "planned", "modules": ["模块 id"]}}
    ]
  }},
  "assembly": {{
    "entrypoint": "main.py",
    "interface_ledger": "interfaces/index.yaml",
    "module_exports": [
      {{
        "module": "模块 id",
        "package": "modules/模块路径",
        "export": "get_router",
        "mount_path": "/api/...",
        "interfaces": ["interface id"]
      }}
    ]
  }}
}}

请只输出 JSON。"""
        return cls._call_ai_json(prompt, max_tokens=8192)

    @classmethod
    def _review_layer(
        cls,
        requirement_content: str,
        layer_name: str,
        layer_context: str,
        artifact: Dict,
        require_ai_review: bool,
    ) -> Dict:
        if not require_ai_review:
            return {
                "layer": layer_name,
                "context": layer_context,
                "passed": True,
                "verdict": "跳过",
                "reason": "测试模式跳过 AI 审核",
            }

        from review import AiArtifactReviewer

        result = AiArtifactReviewer.review_pmc_layer(
            requirement_content,
            layer_name,
            layer_context,
            artifact,
        )
        review_data = cls._review_to_dict(layer_name, layer_context, result)
        if not result.passed:
            raise ValueError(f"PMC 分层拆分 AI 审核打回：{layer_context} - {result.reason}")
        return review_data

    @classmethod
    def _review_blueprint(cls, requirement_content: str, blueprint: Dict, require_ai_review: bool) -> Dict:
        if not require_ai_review:
            return {
                "layer": "pmc_blueprint",
                "context": "项目蓝图",
                "passed": True,
                "verdict": "跳过",
                "reason": "测试模式跳过 AI 审核",
            }

        from review import AiArtifactReviewer

        result = AiArtifactReviewer.review_pmc_blueprint(requirement_content, blueprint)
        review_data = cls._review_to_dict("pmc_blueprint", "项目蓝图", result)
        if not result.passed:
            raise ValueError(f"PMC 蓝图 AI 审核打回：{result.reason}")
        return review_data

    @staticmethod
    def _review_to_dict(layer_name: str, layer_context: str, result) -> Dict:
        return {
            "layer": layer_name,
            "context": layer_context,
            "passed": result.passed,
            "verdict": result.verdict,
            "reason": result.reason,
            "must_fix": result.must_fix,
            "prompt_notes": result.prompt_notes,
            "raw": result.raw,
        }

    @classmethod
    def _validate_project_domains(cls, artifact: Dict):
        if artifact.get("stage") != "project_domains":
            raise ValueError("项目域拆分产物 stage 必须是 project_domains")
        domains = artifact.get("domains")
        if not isinstance(domains, list) or not domains:
            raise ValueError("项目域拆分产物必须包含 domains")

        domain_ids = []
        for domain in domains:
            cls._require_fields(domain, ("id", "name", "responsibility", "not_responsible"))
            domain_ids.append(domain["id"])
            if not isinstance(domain.get("not_responsible"), list):
                raise ValueError(f"项目域 {domain.get('id')} 的 not_responsible 必须是列表")
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("项目域拆分产物存在重复 domain id")

    @classmethod
    def _validate_domain_modules(cls, domain: Dict, artifact: Dict, all_module_ids: set):
        expected_domain_id = domain.get("id")
        if artifact.get("stage") != "domain_modules":
            raise ValueError(f"域 {expected_domain_id} 的拆分产物 stage 必须是 domain_modules")
        if artifact.get("domain_id") != expected_domain_id:
            raise ValueError(f"域内拆分 domain_id 不匹配：期望 {expected_domain_id}")

        modules = artifact.get("modules")
        if not isinstance(modules, list) or not modules:
            raise ValueError(f"域 {expected_domain_id} 必须至少包含一个子模块")

        local_ids = []
        for module in modules:
            cls._require_fields(
                module,
                ("id", "name", "responsibility", "not_responsible", "public_capabilities", "depends_on", "status"),
            )
            module_id = module["id"]
            local_ids.append(module_id)
            if not module_id.startswith(f"{expected_domain_id}."):
                raise ValueError(f"模块 {module_id} 不属于当前大域 {expected_domain_id}")
            if not isinstance(module.get("not_responsible"), list):
                raise ValueError(f"模块 {module_id} 的 not_responsible 必须是列表")
            if not isinstance(module.get("public_capabilities"), list):
                raise ValueError(f"模块 {module_id} 的 public_capabilities 必须是列表")
            if not isinstance(module.get("depends_on"), list):
                raise ValueError(f"模块 {module_id} 的 depends_on 必须是列表")

        if len(local_ids) != len(set(local_ids)):
            raise ValueError(f"域 {expected_domain_id} 存在重复 module id")
        duplicated = set(local_ids).intersection(all_module_ids)
        if duplicated:
            raise ValueError(f"跨域存在重复 module id: {sorted(duplicated)}")
        all_module_ids.update(local_ids)

    @staticmethod
    def _validate_blueprint(blueprint: Dict, allowed_module_ids: set):
        issues, _suggestions = PmcBlueprint.validate(blueprint)
        if issues:
            raise ValueError("PMC 蓝图确定性验收失败：" + "；".join(issues))
        blueprint_module_ids = {
            module.get("id")
            for module in blueprint.get("module_cards", [])
            if module.get("id")
        }
        if blueprint_module_ids != allowed_module_ids:
            raise ValueError(
                "PMC 蓝图模块必须等于已审核叶子模块："
                f"blueprint={sorted(blueprint_module_ids)}, layered={sorted(allowed_module_ids)}"
            )

    @staticmethod
    def _require_fields(item: Dict, fields: tuple):
        missing = [field for field in fields if field not in item]
        if missing:
            raise ValueError(f"产物缺少字段 {missing}: {item}")

    @classmethod
    def _call_ai_json(cls, prompt: str, max_tokens: int) -> Dict:
        from pipeline.AiBase import AiBase

        raw = AiBase().call(
            prompt,
            system=cls.SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        data = cls._parse_json(raw)
        if not isinstance(data, dict):
            raise ValueError("AI 分层拆分必须返回 JSON 对象")
        return data

    @staticmethod
    def _parse_json(raw: str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start:end + 1]
        return json.loads(text)

    @classmethod
    def write_artifacts(cls, result: PmcLayeredSplitResult) -> Dict[str, str]:
        """保存分层拆分中间产物。"""
        split_dir = cls.OUTPUT_DIR / result.session_id / "spec" / "layered_split"
        split_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "project_domains": split_dir / "project_domains.yaml",
            "domain_modules": split_dir / "domain_modules.yaml",
            "reviews": split_dir / "reviews.yaml",
        }
        cls._write_yaml(files["project_domains"], result.project_domains)
        cls._write_yaml(files["domain_modules"], result.domain_modules)
        cls._write_yaml(files["reviews"], {"reviews": result.reviews})
        return {key: cls._relative(path) for key, path in files.items()}

    @staticmethod
    def _write_yaml(path: Path, data: Dict):
        with open(path, "w", encoding="utf-8-sig") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    @staticmethod
    def _relative(path: Path) -> str:
        return str(path.relative_to(Path(__file__).parent.parent)).replace("\\", "/")


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 初版：实现 PMC 分层拆分编排、每层 AI 审核和中间产物落盘
# contract: 12_接手文档.md
# next: PmcRouter 接入分层拆分入口
# </YGA_END_ANCHOR>
