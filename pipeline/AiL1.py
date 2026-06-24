# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: ai
file: pipeline/AiL1.py
responsibility: L1 AI 模块 - 需求理解
authority: .claude/planning/06_Simple链路.md
</YGA_FILE_ANCHOR>
"""
from typing import Dict
from pipeline.AiBase import AiBase


class AiL1:
    """
    L1 需求理解模块

    职责：
    1. 读取用户需求
    2. 理解用户想做什么
    3. 输出结构化需求描述
    """

    def __init__(self):
        self.ai = AiBase()

    def understand(self, prompt: str, user_input: str) -> str:
        """
        理解用户需求

        Args:
            prompt: L1 提示词
            user_input: 用户原始需求

        Returns:
            结构化需求描述
        """
        full_prompt = f"""{prompt}

## 用户需求
{user_input}

请按照上述格式整理用户需求，输出结构化的需求描述。
"""
        return self.ai.call(full_prompt)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>