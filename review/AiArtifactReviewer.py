# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: review
file: review/AiArtifactReviewer.py
responsibility: AI 产物审核入口（所有 AI 判断产物必须经 AI 审核）
exports: AiArtifactReviewer, AiArtifactReviewResult
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from dataclasses import dataclass
from typing import Dict
import json


@dataclass
class AiArtifactReviewResult:
    """AI 产物审核结果。"""
    passed: bool
    verdict: str
    reason: str = ""
    must_fix: list = None
    prompt_notes: list = None
    raw: str = ""

    def __post_init__(self):
        if self.must_fix is None:
            self.must_fix = []
        if self.prompt_notes is None:
            self.prompt_notes = []


class AiArtifactReviewer:
    """对 AI 产出的非确定性内容做 AI 审核。"""

    SYSTEM_PROMPT = """你是 YGA 的 AI 审查员。
你只审核 AI 产物的判断质量，不替代本地确定性校验，不直接修改产物。

本地代码已经负责检查：格式、唯一性、引用是否存在、YAML/JSON 是否可解析。
你负责检查：需求是否被误解、模块拆分是否合理、接口是否覆盖需求、依赖和批次是否符合业务推进顺序、是否存在明显过度设计或遗漏。

审核前必须先识别当前产物的工作背景：
- L0/L1 需求整理：输入来自用户自然语言，审核重点是是否误解用户、是否添加用户没确认的功能。
- PMC 分层拆分：输入来自已确认需求和上一层拆分，审核重点是边界、遗漏、越界、是否适合继续下钻。
- PMC 蓝图：输入来自分层拆分结果，审核重点是模块卡片、接口总账、依赖图、批次和组装是否一致。
- L2 接口契约：输入来自已确认需求或当前批次模块，审核重点是接口是否覆盖需求、是否可执行、是否越权新增能力。
- L3 代码：输入来自接口契约和当前批次，审核重点是代码是否实现契约、是否只实现当前范围、是否具备日志和错误处理。
- 变更审查：输入来自等待区需求和快照，审核重点是影响范围、旧产物失效和重新下发范围。

每个模块也有自己的背景：先确认它属于哪个上层功能域、当前层级负责什么、下层还会不会继续拆、兄弟模块边界在哪里。
不同背景不能套同一套判断标准。先按当前阶段、区域和模块职责理解产物用途，再给结论。

YGA 的背景：
- YGA 是面向普通用户的 AI 生成系统，不是人工团队长期手写维护的传统后端项目。
- 大项目必须拆小。原因是控制单次 AI 生成上下文、降低单文件复杂度、减少生成遗漏、让失败可以定位到小模块、让后续变更可以只重发受影响模块。
- 因此审核时不要用“传统后端里这些功能可以写在一个服务里”作为打回理由。拆分本身是前提，不是待讨论选项。
- 审核重点应是：拆分后是否仍然统一接口总账、职责是否清楚、依赖是否可追踪、批次是否能执行、组装是否不靠猜。
- 如果功能天然耦合，可以要求蓝图写清共享模型、调用关系和组装方式；不要直接要求合并，除非当前拆分已经导致职责重复、循环依赖、接口冲突或无法生成。
- 分层流程必须走，但极小需求允许一域一叶子模块；不要要求为了“看起来拆过”而制造伪业务域或伪模块。
- 对极小需求，创建/查询/修改/删除只是同一业务对象的操作，不天然构成必须拆分的模块边界；只有职责已经复杂到会影响生成上下文、批次推进或后续变更定位时才要求继续拆。

YGA 的模块拆分原则：
- 大项目按功能继续拆小模块，只要职责清晰、接口统一登记、依赖可追踪、后续组装不靠猜。
- 不要仅因为多个模块属于同一业务域或共享同一实体就要求合并；只有出现职责重叠、接口重复、循环依赖、无法组装或维护成本明显失控时才打回。
- 不要把 CRUD 动作、读写模式、数据模型定义、文件类型当成项目大域；这些通常应落在同一业务域或模块内部，除非需求明确要求独立能力边界。
- 模块如果拥有 public_interfaces，就必须负责这些接口对应的入口、参数接收和处理编排；如果 not_responsible 排除了本模块公开接口所需职责，应打回。
- 批次语义是：后一批可以依赖前面已经完成的批次；同一批次内的模块默认并行，不能互相依赖，除非蓝图显式标记串行。
- “管理”类需求不能只给一个含糊入口，应至少体现查询、筛选、详情或状态调整等可执行接口。

请只输出 JSON，不要输出 Markdown：
{
  "verdict": "通过" 或 "打回",
  "reason": "一句到三句话说明原因",
  "must_fix": ["必须修正的问题"],
  "prompt_notes": ["如果提示词需要优化，写具体优化点"]
}
"""

    @classmethod
    def review_pmc_layer(
        cls,
        requirement: str,
        layer_name: str,
        layer_context: str,
        artifact: Dict
    ) -> AiArtifactReviewResult:
        """审核 PMC 分层拆分中的单层 AI 产物。"""
        prompt = f"""## 审核对象
PMC 分层拆分单层产物。该产物由工作 AI 生成，本地代码只做确定性结构校验。

## 当前工作背景
- 当前阶段：PMC 分层拆分审核。
- 当前区域：审核区。
- 当前模块：{layer_context}
- 输入来源：用户已确认需求，以及上一层已审核通过的拆分结果。
- 产物用途：通过后进入下一层拆分或项目蓝图生成。
- 边界：不直接修改产物，不替本地做 JSON/字段/唯一性检查，不允许一次性拆到底。

## 分层名称
{layer_name}

## 需求文档
{requirement}

## 当前层产物 JSON
{json.dumps(artifact, ensure_ascii=False, indent=2)}

## 审核重点
1. 当前层是否只做当前层该做的事。
2. 模块或域的职责边界是否清楚，是否写明不负责什么。
3. 是否遗漏需求中的关键范围，或加入用户没有表达的范围。
4. 是否适合进入下一层继续拆分；不要要求本层直接补齐最终代码或完整接口细节。
5. 大项目必须拆小，不能因为传统后端可以合并实现就打回。
6. 极小需求可以是一域一叶子模块；不要仅因为有创建和查询两个操作就要求拆成多个域或模块。
7. 如果产物为了拆分制造读写域、CRUD 域、数据模型域，要打回。

请按系统提示词要求输出 JSON。"""
        return cls.review(prompt)

    @classmethod
    def review_l2_interface(cls, requirement: str, interfaces: str) -> AiArtifactReviewResult:
        """审核 L2 接口契约。"""
        prompt = f"""## 审核对象
L2 接口契约。该契约由工作 AI 生成，本地代码只做章节结构等确定性检查。

## 当前工作背景
- 当前阶段：L2 接口契约审核。
- 当前区域：审核区。
- 当前模块：接口总账/契约模块。
- 输入来源：用户已确认需求 logs/requirement.md。
- 产物用途：L3 代码生成与 LocalGate 契约解析。
- 边界：不替 PMC 做模块拆分，不新增用户未确认的功能。

## 需求文档
{requirement}

## 接口契约
{interfaces}

## 审核重点
1. 接口是否覆盖需求中的关键能力。
2. 是否越权新增用户未确认的功能。
3. 输入输出是否可执行、可验证。
4. 不要求用户可见的 HTTP 细节完美，但内部契约应自洽。

请按系统提示词要求输出 JSON。"""
        return cls.review(prompt)

    @classmethod
    def review_pmc_blueprint(cls, requirement: str, blueprint: Dict) -> AiArtifactReviewResult:
        """审核 AI 生成的 PMC 蓝图。"""
        prompt = f"""## 审核对象
PMC 蓝图。该蓝图由工作 AI 生成，本地代码只做确定性校验。

## 当前工作背景
- 当前阶段：PMC 蓝图审核。
- 当前区域：审核区。
- 当前模块：项目级蓝图模块，负责检查上层功能域、子模块、接口总账、依赖和批次是否能统一组装。
- 输入来源：用户已确认需求和工作 AI 生成的 PMC 蓝图。
- 产物用途：决定蓝图是否能进入接口总账落盘、批次下发和后续代码开发。
- 边界：不直接修改蓝图，不替本地做格式校验，不因为“传统后端可以合并”而否定必须拆小的前提。

## 需求文档
{requirement}

## PMC 蓝图 JSON
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

## 审核重点
1. 在“必须拆小”的前提下，模块边界是否清楚，是否遗漏核心功能。
2. 模块职责是否清晰，是否存在明显重叠。
3. 接口总账是否覆盖需求中的关键能力。
4. 模块依赖和批次是否符合合理开发顺序。
5. 组装说明是否足以指导后续代码生成。
6. 不要因为普通后端可以合并实现就打回；只有拆分导致无法稳定生成、审查或组装时才打回。

请按系统提示词要求输出 JSON。"""
        return cls.review(prompt)

    @classmethod
    def review(cls, prompt: str) -> AiArtifactReviewResult:
        """调用 AI 审查员并解析结果。"""
        from pipeline.AiBase import AiBase

        raw = AiBase().call(prompt, system=cls.SYSTEM_PROMPT, temperature=0.2, max_tokens=2048)
        data = cls._parse_json(raw)
        verdict = str(data.get("verdict", "")).strip()
        reason = str(data.get("reason", "")).strip()
        passed = verdict == "通过"
        return AiArtifactReviewResult(
            passed=passed,
            verdict=verdict or ("通过" if passed else "打回"),
            reason=reason,
            must_fix=data.get("must_fix") or [],
            prompt_notes=data.get("prompt_notes") or [],
            raw=raw,
        )

    @staticmethod
    def _parse_json(raw: str) -> Dict:
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


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 初版：AI 产物统一审核入口
# contract: 12_接手文档.md
# next: PMC/Pipeline AI 产物接入
# </YGA_END_ANCHOR>
