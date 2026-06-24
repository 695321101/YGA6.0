# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: ai
file: pipeline/AiL2.py
responsibility: L2 AI 模块 - 接口文档生成
authority: .claude/planning/06_Simple链路.md
</YGA_FILE_ANCHOR>
"""
from typing import Dict
from pipeline.AiBase import AiBase


class AiL2:
    """
    L2 接口文档生成模块

    职责：
    1. 读取结构化需求
    2. 设计 API 接口
    3. 输出接口文档
    """

    def __init__(self):
        self.ai = AiBase()

    def generate_interface(self, prompt: str, requirement: str) -> str:
        """
        生成接口文档

        Args:
            prompt: L2 提示词
            requirement: 结构化需求

        Returns:
            接口文档
        """
        full_prompt = f"""{prompt}

## 需求文档
{requirement}

请根据需求文档设计接口契约，输出完整的接口文档。
"""
        return self.ai.call(full_prompt)


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>