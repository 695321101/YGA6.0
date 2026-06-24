# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: test
file: pipeline/LocalTester.py
responsibility: 本地测试模块 - 调用通用薄门禁
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
from pathlib import Path
from typing import Dict, Optional

from pipeline.LocalGate import LocalGate


class LocalTester:
    """
    本地测试模块

    职责：按契约调用 LocalGate 做确定性检测。
    """

    def __init__(self):
        self.gate = LocalGate()
        self.results = {}

    def run_tests(
        self,
        code_dir: Path,
        contract: Optional[Dict] = None,
        interfaces: str = "",
    ) -> Dict:
        """
        运行所有本地测试

        Args:
            code_dir: 代码目录
            contract: 薄门禁契约；为空时可从 interfaces 解析
            interfaces: 接口文档文本，用于提取 required_files

        Returns:
            测试结果字典
        """
        if contract is None and interfaces:
            contract = LocalGate.parse_contract_from_interfaces(interfaces)

        self.results = self.gate.run(code_dir, contract)
        return self.results


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>
