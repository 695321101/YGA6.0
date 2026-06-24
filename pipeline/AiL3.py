# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: ai
file: pipeline/AiL3.py
responsibility: L3 AI 模块 - 代码生成
authority: .claude/planning/06_Simple链路.md
</YGA_FILE_ANCHOR>
"""
from typing import Dict, List, Tuple
import re
from pathlib import Path
from pipeline.AiBase import AiBase


class AiL3:
    """
    L3 代码生成模块

    职责：
    1. 读取接口文档
    2. 生成代码文件
    3. 确保代码包含日志
    """

    def __init__(self):
        self.ai = AiBase()

    def generate_code(self, prompt: str, interfaces: str) -> str:
        """
        生成代码

        Args:
            prompt: L3 提示词
            interfaces: 接口文档

        Returns:
            生成的代码内容（包含多个代码块）
        """
        full_prompt = f"""{prompt}

## 接口文档
{interfaces}

请根据接口文档生成完整的、可运行的代码。
请为每个文件使用代码块标签标注文件名，例如：
```python filename:main.py
代码内容
```

```python filename:models.py
代码内容
```

确保生成的代码：
1. 包含完整的 YGA 锚点
2. 主文件配置日志
3. 其他模块获取 logger
4. 包含异常处理
"""
        return self.ai.call(full_prompt, temperature=0.3)

    def parse_code_files(self, content: str) -> List[Tuple[str, str]]:
        """
        解析代码文件

        Args:
            content: AI 生成的代码内容

        Returns:
            [(filename, content), ...]
        """
        files = []

        # 匹配 ```python filename:xxx.py 或 ```python:xxx.py
        pattern = r'```python\s*(?::(\S+?)|filename:(\S+?))?\s*\n([\s\S]*?)```'

        for match in re.finditer(pattern, content):
            filename = match.group(1) or match.group(2) or "generated.py"
            code = match.group(3).strip()

            # 清理可能的前缀
            code = re.sub(r'^# -\*- coding: utf-8 -\*-\n?', '', code)

            files.append((filename, code))

        return files


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>