# -*- coding: utf-8 -*-
"""
AI 集成测试脚本 - Memory 模块
使用 AI 验证 Memory 模块的功能正确性
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import MemRouter


def load_config():
    """加载 AI 配置"""
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'ai_config.json')
    with open(config_path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


AI_SYSTEM_PROMPT = """你是一个专业的代码审查员和测试专家。
你需要验证 Memory 模块的功能是否符合设计规范。

## Memory 模块职责
1. MemSession - Session 管理（创建/获取/更新上下文）
2. MemWriter - 写入文档（需求/接口/进度/对话）
3. MemReader - 读取文档
4. MemPhase - 阶段门禁
5. MemRouter - 统一入口

## 测试要求
1. 验证各模块方法能正常调用
2. 验证文档能正确写入和读取
3. 验证阶段门禁逻辑正确
4. 验证上下文状态正确更新

请生成一个测试报告，包括：
- 测试结果（通过/失败）
- 每个功能的验证状态
- 发现的问题（如有）
"""


def get_ai_response(prompt: str) -> str:
    """调用 AI 获取响应"""
    config = load_config()

    import requests

    payload = {
        "model": config.get('model', 'agnes-2.0-flash'),
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    proxies = None
    if config.get('proxy_url'):
        proxies = {"http": config['proxy_url'], "https": config['proxy_url']}

    response = requests.post(
        config['api_base'] + "/chat/completions",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json"
        },
        json=payload,
        proxies=proxies,
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"AI API 错误: {response.status_code} - {response.text}")

    result = response.json()
    return result['choices'][0]['message']['content']


def get_ai_response_raw(prompt: str) -> str:
    """调用 AI 获取响应（处理 BOM）"""
    config = load_config()

    import requests

    payload = {
        "model": config.get('model', 'agnes-2.0-flash'),
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    proxies = None
    if config.get('proxy_url'):
        proxies = {"http": config['proxy_url'], "https": config['proxy_url']}

    response = requests.post(
        config['api_base'] + "/chat/completions",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json"
        },
        json=payload,
        proxies=proxies,
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"AI API 错误: {response.status_code} - {response.text}")

    # 处理 BOM 编码问题
    result_text = response.content.decode('utf-8-sig')
    result = json.loads(result_text)
    return result['choices'][0]['message']['content']


def test_with_ai():
    """使用 AI 进行集成测试"""
    print("=" * 60)
    print("AI 集成测试 - Memory 模块")
    print("=" * 60)

    # 1. 创建测试 Session
    print("\n[1] 创建测试 Session...")
    session_id = MemRouter.create_session("ai_test_user", "AI测试项目")
    print(f"    Session ID: {session_id}")

    # 2. 准备测试数据
    requirement_content = """## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户

## 约束条件
- 支持 JWT 认证
- 使用 SQLAlchemy ORM
"""

    interfaces_content = """## 接口列表

### 1. 用户注册 POST /api/user/register
- 输入: username, password, email
- 输出: user_id, token

### 2. 用户登录 POST /api/user/login
- 输入: username, password
- 输出: user_id, token

### 3. 查询用户 GET /api/user/{id}
- 输入: user_id
- 输出: user_info
"""

    # 3. 执行写入操作
    print("\n[2] 执行写入操作...")
    MemRouter.write(session_id, 'requirement', requirement_content, source='User')
    print("    - 需求文档已写入")

    MemRouter.write(session_id, 'interfaces', interfaces_content, source='AI')
    print("    - 接口文档已写入")

    MemRouter.write(session_id, 'chat_raw', "用户：我要一个用户管理系统", source='User')
    print("    - 对话记录已写入")

    # 4. 读取验证
    print("\n[3] 读取验证...")
    req = MemRouter.read(session_id, 'requirement')
    iface = MemRouter.read(session_id, 'interfaces')
    chat = MemRouter.read(session_id, 'chat')
    context = MemRouter.read(session_id, 'context')

    print(f"    - 需求文档: {'已读取' if req else '未找到'}")
    print(f"    - 接口文档: {'已读取' if iface else '未找到'}")
    print(f"    - 对话记录: {'已读取' if chat else '未找到'}")
    print(f"    - 上下文状态: {context}")

    # 5. 阶段门禁测试
    print("\n[4] 阶段门禁测试...")
    can_enter_pmc, msg = MemRouter.check_phase_gate(session_id, 'phase_3')
    print(f"    - 进入 phase_3: {can_enter_pmc} ({msg})")

    can_enter_pipe, msg = MemRouter.check_phase_gate(session_id, 'phase_4')
    print(f"    - 进入 phase_4: {can_enter_pipe} ({msg})")

    # 6. 调用 AI 验证
    print("\n[5] 调用 AI 进行功能验证...")

    test_report_prompt = f"""请验证以下 Memory 模块测试结果：

## 已执行的操作
1. 创建 Session: {session_id}
2. 写入需求文档（包含用户管理系统的需求）
3. 写入接口文档（包含注册/登录/查询接口）
4. 写入对话记录

## 已读取的内容
- 需求文档: {'用户管理系统' in (req or '')}
- 接口文档: {'用户注册' in (iface or '')}
- 对话记录: {'用户管理系统' in (chat or '')}

## 上下文状态
{context}

## 阶段门禁
- PMC (phase_3): {can_enter_pmc}
- 流水线 (phase_4): {can_enter_pipe}

请评估：
1. 各功能是否正常工作
2. 上下文状态是否正确（requirement_ready 应该是 True）
3. 阶段门禁逻辑是否正确
4. 是否有遗漏的功能点需要补充测试
"""

    try:
        ai_response = get_ai_response_raw(test_report_prompt)
        print("\n" + ai_response)
    except Exception as e:
        import traceback
        print(f"\n    AI 测试失败: {e}")
        traceback.print_exc()

    # 7. 清理测试数据
    print("\n[6] 清理测试数据...")
    print("    - 测试 Session 保留在 memory/sessions/ 目录")

    print("\n" + "=" * 60)
    print("AI 集成测试完成")
    print("=" * 60)


if __name__ == '__main__':
    test_with_ai()