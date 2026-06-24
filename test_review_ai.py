# -*- coding: utf-8 -*-
"""
AI 审核测试
调用 AI API 对 Memory 模块进行完整审核
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import MemRouter, Reviewer


def setup_test_session():
    """创建测试 Session"""
    # 清理旧测试数据
    sessions = MemRouter.list_sessions()
    for sess in sessions:
        if '测试项目' in sess.get('session', {}).get('project_name', ''):
            # 复用已有的测试 session
            return sess['session']['id']

    # 创建新 Session
    session_id = MemRouter.create_session("test_user", "测试项目")
    print(f"创建测试 Session: {session_id}")

    # 写入需求草稿
    requirement = """## 项目信息
- 项目名称：用户管理系统
- 技术栈：Python + FastAPI

## 功能列表
1. 用户注册
2. 用户登录
3. 查询用户
"""
    MemRouter.write(session_id, 'requirement', requirement, source='AI')
    MemRouter.write(session_id, 'requirement_confirm', '', source='User')

    # 写入接口草稿
    interfaces = """## 接口列表

### 1. 用户注册 POST /api/user/register
- 输入: username, password, email
- 输出: user_id, token

### 2. 用户登录 POST /api/user/login
- 输入: username, password
- 输出: user_id, token
"""
    MemRouter.write(session_id, 'interfaces', interfaces, source='AI')
    MemRouter.write(session_id, 'interfaces_confirm', '', source='User')

    return session_id


def main():
    print("=" * 50)
    print("AI 审核测试")
    print("=" * 50)

    try:
        # 创建测试 Session
        session_id = setup_test_session()
        print(f"\n测试 Session ID: {session_id}")

        # 获取当前状态
        status = MemRouter.get_phase_status(session_id)
        print(f"当前阶段: {status['current_phase']}")

        # 执行完整审核
        print("\n" + "=" * 50)
        print("开始 AI 审核...")
        print("=" * 50)

        result = Reviewer.review(session_id)
        print(f"\n最终结果: {result}")

        print("\n" + "=" * 50)
        if result.strip() == "通过":
            print("✓ AI 审核通过")
        else:
            print("✗ AI 审核打回")
            print("请根据反馈修改后重新提交审核")
        print("=" * 50)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()