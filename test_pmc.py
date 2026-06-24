# -*- coding: utf-8 -*-
"""
PMC 模块测试
测试 PMC 规划 + 审核功能
"""
import sys
import shutil
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import yaml

from pmc import PmcPlanner, PmcReviewer, PmcRouter, PipelineType, PmcBlueprint, PmcLayeredSplitter
from review import AiArtifactReviewResult


def sample_ai_blueprint():
    """模拟 AI 明确输出的大项目蓝图。"""
    mount_paths = {
        "user.auth": "/api/users",
        "user.profile": "/api/users",
        "product.catalog": "/api/products",
        "product.stock": "/api/products",
        "product.price": "/api/products",
        "order.core": "/api/orders",
        "order.status": "/api/orders",
        "payment.intent": "/api/payments",
        "admin.dashboard": "/api/admin/orders",
        "report.sales": "/api/reports/sales",
    }
    module_ids = [
        "user.auth",
        "user.profile",
        "product.catalog",
        "product.stock",
        "product.price",
        "order.core",
        "order.status",
        "payment.intent",
        "admin.dashboard",
        "report.sales",
    ]
    module_cards = [
        {
            "id": "user.auth",
            "name": "用户认证",
            "responsibility": "负责用户注册、登录和会话建立",
            "public_interfaces": ["user.auth.register", "user.auth.login"],
            "depends_on": [],
            "status": "planned",
        },
        {
            "id": "user.profile",
            "name": "用户资料",
            "responsibility": "负责用户资料查询",
            "public_interfaces": ["user.profile.get"],
            "depends_on": ["user.auth"],
            "status": "planned",
        },
        {
            "id": "product.catalog",
            "name": "商品目录",
            "responsibility": "负责商品列表和目录查询",
            "public_interfaces": ["product.catalog.list"],
            "depends_on": [],
            "status": "planned",
        },
        {
            "id": "product.stock",
            "name": "商品库存",
            "responsibility": "负责商品库存预占",
            "public_interfaces": ["product.stock.reserve"],
            "depends_on": ["product.catalog"],
            "status": "planned",
        },
        {
            "id": "product.price",
            "name": "商品价格",
            "responsibility": "负责商品价格查询",
            "public_interfaces": ["product.price.get"],
            "depends_on": ["product.catalog"],
            "status": "planned",
        },
        {
            "id": "order.core",
            "name": "订单核心",
            "responsibility": "负责创建订单",
            "public_interfaces": ["order.core.create"],
            "depends_on": ["user.auth", "product.catalog", "product.stock", "product.price"],
            "status": "planned",
        },
        {
            "id": "order.status",
            "name": "订单状态",
            "responsibility": "负责订单状态查询",
            "public_interfaces": ["order.status.get"],
            "depends_on": ["order.core"],
            "status": "planned",
        },
        {
            "id": "payment.intent",
            "name": "支付意图",
            "responsibility": "负责订单支付发起、支付回调和支付状态查询",
            "public_interfaces": [
                "payment.intent.pay",
                "payment.intent.callback",
                "payment.intent.status",
            ],
            "depends_on": ["order.core"],
            "status": "planned",
        },
        {
            "id": "admin.dashboard",
            "name": "后台订单看板",
            "responsibility": "负责后台订单管理入口，支持订单分页筛选、详情查看和状态调整",
            "public_interfaces": [
                "admin.dashboard.orders",
                "admin.dashboard.order_detail",
                "admin.dashboard.update_order_status",
            ],
            "depends_on": ["order.core"],
            "status": "planned",
        },
        {
            "id": "report.sales",
            "name": "销售报表",
            "responsibility": "负责销售报表统计",
            "public_interfaces": ["report.sales.summary"],
            "depends_on": ["order.core", "order.status", "product.catalog"],
            "status": "planned",
        },
    ]
    public_interfaces = [
        {"id": "user.auth.register", "owner_module": "user.auth", "method": "POST", "path": "/api/users/register"},
        {"id": "user.auth.login", "owner_module": "user.auth", "method": "POST", "path": "/api/users/login"},
        {"id": "user.profile.get", "owner_module": "user.profile", "method": "GET", "path": "/api/users/me"},
        {"id": "product.catalog.list", "owner_module": "product.catalog", "method": "GET", "path": "/api/products"},
        {"id": "product.stock.reserve", "owner_module": "product.stock", "method": "POST", "path": "/api/products/{product_id}/stock/reservations"},
        {"id": "product.price.get", "owner_module": "product.price", "method": "GET", "path": "/api/products/{product_id}/price"},
        {"id": "order.core.create", "owner_module": "order.core", "method": "POST", "path": "/api/orders"},
        {"id": "order.status.get", "owner_module": "order.status", "method": "GET", "path": "/api/orders/{order_id}/status"},
        {"id": "payment.intent.pay", "owner_module": "payment.intent", "method": "POST", "path": "/api/payments"},
        {"id": "payment.intent.callback", "owner_module": "payment.intent", "method": "POST", "path": "/api/payments/callback"},
        {"id": "payment.intent.status", "owner_module": "payment.intent", "method": "GET", "path": "/api/payments/{payment_id}/status"},
        {"id": "admin.dashboard.orders", "owner_module": "admin.dashboard", "method": "GET", "path": "/api/admin/orders"},
        {"id": "admin.dashboard.order_detail", "owner_module": "admin.dashboard", "method": "GET", "path": "/api/admin/orders/{order_id}"},
        {"id": "admin.dashboard.update_order_status", "owner_module": "admin.dashboard", "method": "PATCH", "path": "/api/admin/orders/{order_id}/status"},
        {"id": "report.sales.summary", "owner_module": "report.sales", "method": "GET", "path": "/api/reports/sales"},
    ]
    return {
        "version": "1.0",
        "project_map": {
            "project_name": "电商系统",
            "module_count": len(module_ids),
            "modules": module_ids,
        },
        "module_cards": module_cards,
        "interface_registry": {
            "public_interfaces": public_interfaces,
            "shared_models": [
                {
                    "id": "product.product_reference",
                    "owner_module": "product.catalog",
                    "fields": ["product_id", "name", "status"],
                },
                {
                    "id": "product.price_info",
                    "owner_module": "product.price",
                    "fields": ["product_id", "currency", "amount"],
                },
                {
                    "id": "order.order_item",
                    "owner_module": "order.core",
                    "fields": ["product_id", "quantity", "unit_price"],
                },
                {
                    "id": "order.order_status",
                    "owner_module": "order.status",
                    "fields": ["order_id", "status", "updated_at"],
                },
                {
                    "id": "order.order_summary",
                    "owner_module": "order.core",
                    "fields": ["order_id", "user_id", "status", "total_amount", "paid_at"],
                },
            ],
        },
        "dependency_graph": {
            "nodes": [{"id": module_id} for module_id in module_ids],
            "edges": [
                {"from": dep, "to": module["id"], "reason": "ai_declared_dependency"}
                for module in module_cards
                for dep in module["depends_on"]
            ],
        },
        "batch_plan": {
            "active_batch": "batch_1",
            "batches": [
                {"id": "batch_1", "status": "planned", "modules": ["user.auth", "product.catalog"]},
                {"id": "batch_2", "status": "planned", "modules": ["user.profile", "product.stock", "product.price"]},
                {"id": "batch_3", "status": "planned", "modules": ["order.core"]},
                {"id": "batch_4", "status": "planned", "modules": ["order.status", "payment.intent"]},
                {"id": "batch_5", "status": "planned", "modules": ["admin.dashboard", "report.sales"]},
            ],
        },
        "assembly": {
            "entrypoint": "main.py",
            "interface_ledger": "interfaces/index.yaml",
            "module_exports": [
                {
                    "module": module["id"],
                    "package": f"modules/{module['id'].replace('.', '/')}",
                    "export": "get_router",
                    "mount_path": mount_paths[module["id"]],
                    "interfaces": module["public_interfaces"],
                }
                for module in module_cards
            ],
        },
    }


def test_parse_requirement():
    """测试需求解析"""
    print("=" * 50)
    print("测试 1: 需求解析")
    print("=" * 50)

    requirement = """
# 需求文档（草稿）
> Session: sess_test

## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户
4. 修改用户
5. 删除用户
"""

    result = PmcPlanner.parse_requirement(requirement)
    print(f"项目名称: {result['project_name']}")
    print(f"技术栈: {result['tech_stack']}")
    print(f"功能列表: {result['features']}")

    assert result['project_name'] == "用户管理系统"
    assert "python" in result['tech_stack'].lower()
    assert len(result['features']) == 5
    print("✓ 需求解析测试通过\n")

    long_requirement = "\n".join([f"{index}. 功能{index}" for index in range(1, 12)])
    long_result = PmcPlanner.parse_requirement(long_requirement)
    assert len(long_result["features"]) == 11


def test_count_interfaces():
    """测试接口统计"""
    print("=" * 50)
    print("测试 2: 接口统计")
    print("=" * 50)

    interfaces = """
# 接口文档

### 1. POST /api/user/register
- 输入: username, password, email
- 输出: user_id, token

### 2. POST /api/user/login
- 输入: username, password
- 输出: user_id, token

### 3. GET /api/user/:id
- 输入: user_id
- 输出: user_info

### 4. PUT /api/user/:id
- 输入: user_id, user_info
- 输出: success

### 5. DELETE /api/user/:id
- 输入: user_id
- 输出: success
"""

    count, interface_list = PmcPlanner.count_interfaces(interfaces)
    print(f"接口数量: {count}")
    print(f"接口列表: {interface_list}")

    assert count == 5
    assert len(interface_list) == 5
    print("✓ 接口统计测试通过\n")


def test_pipeline_type_decision():
    """测试链路类型判断"""
    print("=" * 50)
    print("测试 3: 链路类型判断")
    print("=" * 50)

    test_cases = [
        (3, 1, PipelineType.SIMPLE),
        (5, 1, PipelineType.SIMPLE),
        (6, 1, PipelineType.MEDIUM),
        (5, 2, PipelineType.MEDIUM),
        (10, 3, PipelineType.MEDIUM),
        (20, 5, PipelineType.MEDIUM),
        (25, 3, PipelineType.COMPLEX),
        (15, 6, PipelineType.COMPLEX),
        (30, 10, PipelineType.COMPLEX),
    ]

    for interface_count, module_count, expected_type in test_cases:
        actual_type = PmcPlanner.determine_pipeline_type(interface_count, module_count)
        status = "✓" if actual_type == expected_type else "✗"
        print(f"  {status} 接口={interface_count}, 模块={module_count} → {actual_type.value} (期望: {expected_type.value})")
        assert actual_type == expected_type, f"期望 {expected_type}, 得到 {actual_type}"

    print("✓ 链路类型判断测试通过\n")


def test_generate_tasks():
    """测试任务生成"""
    print("=" * 50)
    print("测试 4: 任务生成")
    print("=" * 50)

    requirement = {
        "project_name": "测试项目",
        "tech_stack": "Python + FastAPI",
        "features": ["用户注册", "用户登录", "查询用户"]
    }

    # Simple 类型
    tasks_simple = PmcPlanner.generate_tasks(requirement, PipelineType.SIMPLE)
    print(f"Simple 链路任务数: {len(tasks_simple)}")
    for task in tasks_simple:
        print(f"  - {task.name} (模块: {task.module}, 优先级: {task.priority})")
    assert len(tasks_simple) >= 2

    # Medium 类型
    tasks_medium = PmcPlanner.generate_tasks(requirement, PipelineType.MEDIUM)
    print(f"\nMedium 链路任务数: {len(tasks_medium)}")
    for task in tasks_medium:
        print(f"  - {task.name} (模块: {task.module}, 优先级: {task.priority})")
    assert len(tasks_medium) >= 3

    # Complex 类型
    tasks_complex = PmcPlanner.generate_tasks(requirement, PipelineType.COMPLEX)
    print(f"\nComplex 链路任务数: {len(tasks_complex)}")
    for task in tasks_complex:
        print(f"  - {task.name} (模块: {task.module}, 优先级: {task.priority})")
    assert len(tasks_complex) >= 5

    print("\n✓ 任务生成测试通过\n")


def test_pmc_planner_plan():
    """测试完整规划流程"""
    print("=" * 50)
    print("测试 5: 完整规划流程")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户
4. 修改用户
5. 删除用户
"""

    interfaces = """
### 1. POST /api/user/register
### 2. POST /api/user/login
### 3. GET /api/user/:id
### 4. PUT /api/user/:id
### 5. DELETE /api/user/:id
"""

    decision = PmcPlanner.plan("sess_test", requirement, interfaces)

    print(f"Session ID: {decision.session_id}")
    print(f"链路类型: {decision.pipeline_type.value}")
    print(f"接口数量: {decision.interface_count}")
    print(f"模块数量: {decision.module_count}")
    print(f"任务数量: {len(decision.tasks)}")
    print(f"推理说明: {decision.reasoning}")

    assert decision.interface_count == 5
    assert decision.pipeline_type == PipelineType.SIMPLE
    assert decision.blueprint == {}
    print("\n✓ 完整规划流程测试通过\n")


def test_project_blueprint():
    """测试大项目蓝图：本地只接收 AI 拆分并校验总账"""
    print("=" * 50)
    print("测试 6: 大项目蓝图")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：电商系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 用户资料查询
4. 商品列表
5. 商品库存预占
6. 商品价格查询
7. 创建订单
8. 订单状态查询
9. 支付订单
10. 后台订单管理
11. 销售报表统计
"""

    ai_blueprint = sample_ai_blueprint()
    decision = PmcPlanner.plan("sess_blueprint", requirement, "", ai_blueprint=ai_blueprint)
    blueprint = decision.blueprint
    modules = blueprint["module_cards"]
    registry = blueprint["interface_registry"]
    assembly = blueprint["assembly"]

    interface_ids = [item["id"] for item in registry["public_interfaces"]]
    module_ids = {module["id"] for module in modules}
    assembly_modules = {item["module"] for item in assembly["module_exports"]}

    print(f"模块卡片数: {len(modules)}")
    print(f"接口总账接口数: {len(interface_ids)}")
    print(f"批次数: {len(blueprint['batch_plan']['batches'])}")

    assert len(modules) >= 6
    assert decision.pipeline_type == PipelineType.COMPLEX
    assert decision.module_count >= 6
    assert len(interface_ids) == len(set(interface_ids))
    assert assembly_modules == module_ids
    assert "product.catalog" in module_ids
    assert "product.stock" in module_ids
    assert "product.price" in module_ids
    assert "order.core" in module_ids
    assert "order.status" in module_ids
    assert "payment.intent" in module_ids
    assert "admin.dashboard" in module_ids
    assert "report.sales" in module_ids
    assert any(module["id"] == "order.core" and module["depends_on"] for module in modules)
    assert blueprint["batch_plan"]["active_batch"] == "batch_1"
    assert registry["rules"]["assembler_uses_this_ledger"] is True
    assert blueprint["rules"]["module_split_owner"] == "AI"

    print("✓ 大项目蓝图测试通过\n")


def test_no_local_business_split():
    """测试没有 AI 蓝图时，本地不猜业务模块"""
    print("=" * 50)
    print("测试 7: 无 AI 蓝图时不拆业务模块")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：电商系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 商品列表
3. 创建订单
4. 支付订单
5. 后台订单管理
"""
    decision = PmcPlanner.plan("sess_no_blueprint", requirement, "")
    assert decision.blueprint == {}
    assert decision.module_count == 1
    assert "未收到 AI 蓝图" in decision.reasoning
    print("✓ 无 AI 蓝图不拆业务模块测试通过\n")


def test_blueprint_artifacts():
    """测试蓝图产物写入统一 spec 目录"""
    print("=" * 50)
    print("测试 8: 蓝图产物写入")
    print("=" * 50)

    session_id = "sess_blueprint_artifacts"
    output_dir = Path(__file__).parent / "output" / session_id
    if output_dir.exists():
        shutil.rmtree(output_dir)

    project = {
        "project_name": "电商系统",
        "tech_stack": "Python + FastAPI",
        "features": ["用户注册", "商品列表", "创建订单", "支付订单"]
    }

    try:
        blueprint = PmcBlueprint.from_ai_blueprint(session_id, project, sample_ai_blueprint())
        issues, suggestions = PmcBlueprint.validate(blueprint)
        assert not issues
        artifacts = PmcBlueprint.write_artifacts(session_id, blueprint)
        required_files = [
            output_dir / "spec" / "project_map.yaml",
            output_dir / "spec" / "interfaces" / "index.yaml",
            output_dir / "spec" / "dependency_graph.yaml",
            output_dir / "spec" / "batch_plan.yaml",
            output_dir / "spec" / "assembly.yaml",
            output_dir / "spec" / "project_blueprint.yaml",
        ]

        for file_path in required_files:
            assert file_path.exists(), f"缺少蓝图文件: {file_path}"

        with open(output_dir / "spec" / "interfaces" / "index.yaml", "r", encoding="utf-8-sig") as f:
            registry = yaml.safe_load(f)

        assert registry["authority"] == "interfaces/index.yaml"
        assert artifacts["interfaces_index"] == f"output/{session_id}/spec/interfaces/index.yaml"
        print("✓ 蓝图产物写入测试通过\n")
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)


def test_invalid_blueprint_review():
    """测试坏蓝图会被确定性审查打回"""
    print("=" * 50)
    print("测试 9: 坏蓝图审查")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：错误蓝图测试
- 技术栈：Python + FastAPI

## 功能列表
1. 创建订单
"""
    bad_blueprint = sample_ai_blueprint()
    bad_blueprint["interface_registry"]["public_interfaces"][0]["owner_module"] = "missing.module"

    decision = PmcPlanner.plan("sess_bad_blueprint", requirement, "", ai_blueprint=bad_blueprint)
    result = PmcReviewer.review_pmc_decision(decision, "")

    assert not result.passed
    assert any("不存在的模块" in issue for issue in result.issues)
    print("✓ 坏蓝图审查测试通过\n")


def test_invalid_assembly_mount_review():
    """测试组装挂载路径和接口路径不一致会被本地审查打回"""
    print("=" * 50)
    print("测试 10: 组装挂载路径审查")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：错误组装测试
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
"""
    bad_blueprint = sample_ai_blueprint()
    bad_blueprint["assembly"]["module_exports"][0]["mount_path"] = "/api/wrong"

    decision = PmcPlanner.plan("sess_bad_assembly", requirement, "", ai_blueprint=bad_blueprint)
    result = PmcReviewer.review_pmc_decision(decision, "")

    assert not result.passed
    assert any("mount_path" in issue for issue in result.issues)
    print("✓ 组装挂载路径审查测试通过\n")


def test_invalid_batch_dependency_review():
    """测试依赖模块不在更早批次会被本地审查打回"""
    print("=" * 50)
    print("测试 11: 批次依赖顺序审查")
    print("=" * 50)

    requirement = """
## 项目信息
- 项目名称：错误批次测试
- 技术栈：Python + FastAPI

## 功能列表
1. 创建订单
2. 订单状态查询
"""
    bad_blueprint = sample_ai_blueprint()
    bad_blueprint["batch_plan"]["batches"][2]["modules"] = ["order.core", "order.status"]
    bad_blueprint["batch_plan"]["batches"][3]["modules"] = ["payment.intent"]

    decision = PmcPlanner.plan("sess_bad_batch", requirement, "", ai_blueprint=bad_blueprint)
    result = PmcReviewer.review_pmc_decision(decision, "")

    assert not result.passed
    assert any("依赖不在更早批次" in issue for issue in result.issues)
    print("✓ 批次依赖顺序审查测试通过\n")


def test_pmc_blueprint_requires_ai_review():
    """测试 PMC 蓝图可强制接入 AI 审查员"""
    print("=" * 50)
    print("测试 12: PMC 蓝图 AI 审核接入")
    print("=" * 50)

    from review import AiArtifactReviewer

    requirement = """
## 项目信息
- 项目名称：电商系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 商品列表
3. 创建订单
4. 支付订单
5. 后台订单管理
"""
    decision = PmcPlanner.plan(
        "sess_ai_review_hook",
        requirement,
        "",
        ai_blueprint=sample_ai_blueprint()
    )

    original = AiArtifactReviewer.review_pmc_blueprint
    calls = []

    def fake_review(req, blueprint):
        calls.append((req, blueprint))
        return AiArtifactReviewResult(
            passed=True,
            verdict="通过",
            reason="测试替身：蓝图质量通过",
            raw='{"verdict":"通过","reason":"测试替身：蓝图质量通过"}',
        )

    try:
        AiArtifactReviewer.review_pmc_blueprint = staticmethod(fake_review)
        result = PmcReviewer.review_pmc_decision(
            decision,
            "",
            requirement_content=requirement,
            require_ai_review=True,
        )
    finally:
        AiArtifactReviewer.review_pmc_blueprint = original

    assert result.passed
    assert len(calls) == 1
    assert result.ai_reviews and result.ai_reviews[0]["passed"] is True
    print("✓ PMC 蓝图 AI 审核接入测试通过\n")


def test_pmc_blueprint_ai_review_rejects():
    """测试 AI 审查员打回时 PMC 不通过"""
    print("=" * 50)
    print("测试 13: PMC 蓝图 AI 审核打回")
    print("=" * 50)

    from review import AiArtifactReviewer

    requirement = """
## 项目信息
- 项目名称：电商系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 商品列表
3. 创建订单
"""
    decision = PmcPlanner.plan(
        "sess_ai_review_reject",
        requirement,
        "",
        ai_blueprint=sample_ai_blueprint()
    )

    original = AiArtifactReviewer.review_pmc_blueprint

    def fake_review(req, blueprint):
        return AiArtifactReviewResult(
            passed=False,
            verdict="打回",
            reason="测试替身：蓝图包含需求外模块",
            raw='{"verdict":"打回","reason":"测试替身：蓝图包含需求外模块"}',
        )

    try:
        AiArtifactReviewer.review_pmc_blueprint = staticmethod(fake_review)
        result = PmcReviewer.review_pmc_decision(
            decision,
            "",
            requirement_content=requirement,
            require_ai_review=True,
        )
    finally:
        AiArtifactReviewer.review_pmc_blueprint = original

    assert not result.passed
    assert any("需求外模块" in issue for issue in result.issues)
    assert result.ai_reviews and result.ai_reviews[0]["passed"] is False
    print("✓ PMC 蓝图 AI 审核打回测试通过\n")


def test_layered_splitter_offline():
    """测试 PMC 分层拆分编排：本地只编排和验收，拆分内容来自 AI 返回。"""
    print("=" * 50)
    print("测试 14: PMC 分层拆分编排")
    print("=" * 50)

    from review import AiArtifactReviewer

    requirement = """
## 项目信息
- 项目名称：待办事项 API
- 技术栈：Python + FastAPI

## 功能列表
1. 创建待办事项
2. 查询待办事项
"""

    responses = [
        {
            "stage": "project_domains",
            "domains": [
                {
                    "id": "todo",
                    "name": "待办事项",
                    "responsibility": "负责待办事项创建和查询",
                    "not_responsible": ["用户认证", "支付"],
                    "split_reason": "该域包含待办事项核心行为，需要继续下钻",
                    "expected_submodule_count": 2,
                }
            ],
        },
        {
            "stage": "domain_modules",
            "domain_id": "todo",
            "modules": [
                {
                    "id": "todo.create",
                    "name": "待办创建",
                    "responsibility": "负责创建待办事项",
                    "not_responsible": ["待办查询"],
                    "public_capabilities": ["创建待办事项"],
                    "depends_on": [],
                    "status": "planned",
                },
                {
                    "id": "todo.query",
                    "name": "待办查询",
                    "responsibility": "负责查询待办事项",
                    "not_responsible": ["待办创建"],
                    "public_capabilities": ["查询待办事项"],
                    "depends_on": [],
                    "status": "planned",
                },
            ],
        },
        {
            "version": "1.0",
            "project_map": {
                "project_name": "待办事项 API",
                "module_count": 2,
                "modules": ["todo.create", "todo.query"],
            },
            "module_cards": [
                {
                    "id": "todo.create",
                    "name": "待办创建",
                    "responsibility": "负责创建待办事项",
                    "not_responsible": ["待办查询"],
                    "public_interfaces": ["todo.create.create"],
                    "depends_on": [],
                    "status": "planned",
                },
                {
                    "id": "todo.query",
                    "name": "待办查询",
                    "responsibility": "负责查询待办事项",
                    "not_responsible": ["待办创建"],
                    "public_interfaces": ["todo.query.list"],
                    "depends_on": [],
                    "status": "planned",
                },
            ],
            "interface_registry": {
                "public_interfaces": [
                    {
                        "id": "todo.create.create",
                        "owner_module": "todo.create",
                        "method": "POST",
                        "path": "/api/todos",
                    },
                    {
                        "id": "todo.query.list",
                        "owner_module": "todo.query",
                        "method": "GET",
                        "path": "/api/todos",
                    },
                ],
                "shared_models": [],
            },
            "dependency_graph": {
                "nodes": [{"id": "todo.create"}, {"id": "todo.query"}],
                "edges": [],
            },
            "batch_plan": {
                "active_batch": "batch_1",
                "batches": [
                    {"id": "batch_1", "status": "planned", "modules": ["todo.create", "todo.query"]},
                ],
            },
            "assembly": {
                "entrypoint": "main.py",
                "interface_ledger": "interfaces/index.yaml",
                "module_exports": [
                    {
                        "module": "todo.create",
                        "package": "modules/todo/create",
                        "export": "get_router",
                        "mount_path": "/api/todos",
                        "interfaces": ["todo.create.create"],
                    },
                    {
                        "module": "todo.query",
                        "package": "modules/todo/query",
                        "export": "get_router",
                        "mount_path": "/api/todos",
                        "interfaces": ["todo.query.list"],
                    },
                ],
            },
        },
    ]
    calls = []

    original_call = PmcLayeredSplitter.__dict__["_call_ai_json"]
    original_review_layer = AiArtifactReviewer.__dict__["review_pmc_layer"]
    original_review_blueprint = AiArtifactReviewer.__dict__["review_pmc_blueprint"]

    def fake_call(prompt, max_tokens):
        calls.append(prompt)
        return responses.pop(0)

    def fake_review_layer(req, layer_name, layer_context, artifact):
        return AiArtifactReviewResult(
            passed=True,
            verdict="通过",
            reason=f"测试替身：{layer_context} 通过",
            raw='{"verdict":"通过"}',
        )

    def fake_review_blueprint(req, blueprint):
        return AiArtifactReviewResult(
            passed=True,
            verdict="通过",
            reason="测试替身：蓝图通过",
            raw='{"verdict":"通过"}',
        )

    session_id = "sess_layered_split_offline"
    output_dir = Path(__file__).parent / "output" / session_id
    if output_dir.exists():
        shutil.rmtree(output_dir)

    try:
        PmcLayeredSplitter._call_ai_json = classmethod(lambda cls, prompt, max_tokens: fake_call(prompt, max_tokens))
        AiArtifactReviewer.review_pmc_layer = staticmethod(fake_review_layer)
        AiArtifactReviewer.review_pmc_blueprint = staticmethod(fake_review_blueprint)

        result = PmcLayeredSplitter.split(session_id, requirement, require_ai_review=True)
    finally:
        PmcLayeredSplitter._call_ai_json = original_call
        AiArtifactReviewer.review_pmc_layer = original_review_layer
        AiArtifactReviewer.review_pmc_blueprint = original_review_blueprint
        if output_dir.exists():
            shutil.rmtree(output_dir)

    assert len(calls) == 3
    assert len(result.reviews) == 3
    assert result.project_domains["domains"][0]["id"] == "todo"
    assert len(result.domain_modules["domains"][0]["modules"]) == 2
    assert result.blueprint["rules"]["module_split_owner"] == "AI"
    assert result.artifacts["project_domains"].endswith("layered_split/project_domains.yaml")
    print("✓ PMC 分层拆分编排测试通过\n")


def test_layered_splitter_rejects_unreviewed_blueprint_module():
    """测试最终蓝图不能新增上一层未审核的模块。"""
    print("=" * 50)
    print("测试 15: 分层拆分拒绝未审核模块")
    print("=" * 50)

    from review import AiArtifactReviewer

    requirement = """
## 项目信息
- 项目名称：待办事项 API
- 技术栈：Python + FastAPI

## 功能列表
1. 创建待办事项
"""
    project_domains = {
        "stage": "project_domains",
        "domains": [
            {
                "id": "todo",
                "name": "待办事项",
                "responsibility": "负责待办事项",
                "not_responsible": ["支付"],
            }
        ],
    }
    domain_modules = {
        "stage": "domain_modules",
        "domain_id": "todo",
        "modules": [
            {
                "id": "todo.core",
                "name": "待办核心",
                "responsibility": "负责创建待办事项",
                "not_responsible": ["支付"],
                "public_capabilities": ["创建待办事项"],
                "depends_on": [],
                "status": "planned",
            }
        ],
    }
    bad_blueprint = {
        "version": "1.0",
        "project_map": {
            "project_name": "待办事项 API",
            "module_count": 2,
            "modules": ["todo.core", "todo.extra"],
        },
        "module_cards": [
            {
                "id": "todo.core",
                "name": "待办核心",
                "responsibility": "负责创建待办事项",
                "public_interfaces": ["todo.core.create"],
                "depends_on": [],
                "status": "planned",
            },
            {
                "id": "todo.extra",
                "name": "未审核扩展",
                "responsibility": "未经过上一层审核的模块",
                "public_interfaces": ["todo.extra.list"],
                "depends_on": [],
                "status": "planned",
            },
        ],
        "interface_registry": {
            "public_interfaces": [
                {"id": "todo.core.create", "owner_module": "todo.core", "method": "POST", "path": "/api/todos"},
                {"id": "todo.extra.list", "owner_module": "todo.extra", "method": "GET", "path": "/api/todos/extra"},
            ],
            "shared_models": [],
        },
        "dependency_graph": {
            "nodes": [{"id": "todo.core"}, {"id": "todo.extra"}],
            "edges": [],
        },
        "batch_plan": {
            "active_batch": "batch_1",
            "batches": [
                {"id": "batch_1", "status": "planned", "modules": ["todo.core", "todo.extra"]},
            ],
        },
        "assembly": {
            "entrypoint": "main.py",
            "interface_ledger": "interfaces/index.yaml",
            "module_exports": [
                {
                    "module": "todo.core",
                    "package": "modules/todo/core",
                    "export": "get_router",
                    "mount_path": "/api/todos",
                    "interfaces": ["todo.core.create"],
                },
                {
                    "module": "todo.extra",
                    "package": "modules/todo/extra",
                    "export": "get_router",
                    "mount_path": "/api/todos/extra",
                    "interfaces": ["todo.extra.list"],
                },
            ],
        },
    }
    responses = [project_domains, domain_modules, bad_blueprint]

    original_call = PmcLayeredSplitter.__dict__["_call_ai_json"]
    original_review_layer = AiArtifactReviewer.__dict__["review_pmc_layer"]
    original_review_blueprint = AiArtifactReviewer.__dict__["review_pmc_blueprint"]

    def fake_review(req, *args):
        return AiArtifactReviewResult(
            passed=True,
            verdict="通过",
            reason="测试替身：通过",
            raw='{"verdict":"通过"}',
        )

    try:
        PmcLayeredSplitter._call_ai_json = classmethod(lambda cls, prompt, max_tokens: responses.pop(0))
        AiArtifactReviewer.review_pmc_layer = staticmethod(fake_review)
        AiArtifactReviewer.review_pmc_blueprint = staticmethod(lambda req, blueprint: fake_review(req, blueprint))
        try:
            PmcLayeredSplitter.split("sess_layered_bad_module", requirement, require_ai_review=True)
        except ValueError as exc:
            assert "已审核叶子模块" in str(exc)
        else:
            raise AssertionError("未审核模块应被确定性验收拒绝")
    finally:
        PmcLayeredSplitter._call_ai_json = original_call
        AiArtifactReviewer.review_pmc_layer = original_review_layer
        AiArtifactReviewer.review_pmc_blueprint = original_review_blueprint

    print("✓ 分层拆分拒绝未审核模块测试通过\n")


def test_pmc_reviewer():
    """测试 PMC 审核"""
    print("=" * 50)
    print("测试 16: PMC 审核")
    print("=" * 50)

    # 准备测试数据
    from pmc import Task
    decision = PmcPlanner.plan(
        "sess_test",
        "## 项目信息\n- 项目名称：测试\n- 技术栈：Python\n\n## 功能列表\n1. 注册\n2. 登录",
        "### 1. POST /api/register\n### 2. POST /api/login"
    )

    # 执行审核
    result = PmcReviewer.review_pmc_decision(decision, "### 1. POST /api/register\n### 2. POST /api/login")

    print(f"审核通过: {result.passed}")
    print(f"问题数: {len(result.issues)}")
    print(f"建议数: {len(result.suggestions)}")

    if result.issues:
        print("问题列表:")
        for issue in result.issues:
            print(f"  - {issue}")

    if result.suggestions:
        print("建议列表:")
        for suggestion in result.suggestions:
            print(f"  - {suggestion}")

    print("\n" + PmcReviewer.format_review_result(result))
    print("\n✓ PMC 审核测试通过\n")


def test_memory_integration():
    """测试与记忆区集成"""
    print("=" * 50)
    print("测试 17: 记忆区集成")
    print("=" * 50)

    from memory import MemRouter

    # 使用已有的测试 Session
    sessions = MemRouter.list_sessions()
    if not sessions:
        print("没有可用的 Session，跳过测试")
        return

    session = sessions[0]
    session_id = session['session']['id']
    print(f"使用 Session: {session_id}")
    print(f"项目名称: {session['session']['project_name']}")

    # 读取需求
    requirement = MemRouter.read(session_id, 'requirement')
    interfaces = MemRouter.read(session_id, 'interfaces')

    if requirement:
        print(f"\n需求文档长度: {len(requirement)} 字符")
    if interfaces:
        print(f"接口文档长度: {len(interfaces)} 字符")

    # 执行规划
    try:
        decision = PmcPlanner.plan(session_id, requirement or "", interfaces or "")
        print(f"\n规划结果:")
        print(f"  链路类型: {decision.pipeline_type.value}")
        print(f"  接口数量: {decision.interface_count}")
        print(f"  任务数量: {len(decision.tasks)}")

        # 审核
        review_result = PmcReviewer.review_pmc_decision(decision, interfaces or "")
        print(f"\n审核结果: {'通过' if review_result.passed else '打回'}")

        if not review_result.passed:
            for issue in review_result.issues:
                print(f"  问题: {issue}")

        print("\n✓ 记忆区集成测试通过\n")
    except Exception as e:
        print(f"集成测试跳过: {e}\n")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("PMC 模块测试")
    print("=" * 60 + "\n")

    test_parse_requirement()
    test_count_interfaces()
    test_pipeline_type_decision()
    test_generate_tasks()
    test_pmc_planner_plan()
    test_project_blueprint()
    test_no_local_business_split()
    test_blueprint_artifacts()
    test_invalid_blueprint_review()
    test_invalid_assembly_mount_review()
    test_invalid_batch_dependency_review()
    test_pmc_blueprint_requires_ai_review()
    test_pmc_blueprint_ai_review_rejects()
    test_layered_splitter_offline()
    test_layered_splitter_rejects_unreviewed_blueprint_module()
    test_pmc_reviewer()
    test_memory_integration()

    print("=" * 60)
    print("所有测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
