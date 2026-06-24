"""
记忆区索引更新器

自动更新 memory/index.md 和 PROGRESS.md
在 PMC、流水线、组装完成后调用
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_ROOT / "memory" / "index.md"
PROGRESS_FILE = PROJECT_ROOT / "PROGRESS.md"


class MemIndexer:
    """记忆区索引更新器"""

    def __init__(self):
        self.index_file = INDEX_FILE
        self.progress_file = PROGRESS_FILE

    def update_session_index(
        self,
        session_id: str,
        requirement: str,
        modules: List[str],
        files: List[str],
        status: str = "completed",
        chain_type: str = "simple"
    ):
        """
        更新会话索引

        Args:
            session_id: 会话 ID
            requirement: 需求摘要
            modules: 模块列表
            files: 生成的文件列表
            status: 状态 (running/completed/failed)
            chain_type: 链路类型 (simple/medium/complex)
        """
        logger.info(f"更新会话索引: {session_id}")

        try:
            # 读取现有索引
            content = self._read_file(self.index_file)

            # 生成新的会话行
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            file_count = len(files)
            module_count = len(modules)

            new_row = f"| {session_id} | {now} | {requirement[:50]}... | {status} |\n"

            # 查找会话列表部分
            if "| - | - | - | - |" in content:
                # 替换空行
                content = content.replace(
                    "| - | - | - | - |\n\n> 暂无会话记录",
                    new_row + "\n> 暂无会话记录"
                )
            elif f"| {session_id} |" in content:
                # 更新已有行 - 简单替换整行
                content = self._update_session_row(content, session_id, now, requirement, status)
            else:
                # 添加新行
                content = self._insert_session_row(content, new_row)

            # 更新时间戳
            content = content.replace(
                "> 更新日期：",
                f"> 更新日期：{datetime.now().strftime('%Y-%m-%d')}"
            )

            self._write_file(self.index_file, content)
            logger.info(f"会话索引更新成功: {session_id}")

        except Exception as e:
            logger.error(f"更新会话索引失败: {e}", exc_info=True)

    def update_module_progress(
        self,
        module_name: str,
        status: str,
        detail: str = ""
    ):
        """
        更新模块开发进度

        Args:
            module_name: 模块名称
            status: 状态 (✅完成/📋开发中/📋待开发)
            detail: 详细说明
        """
        logger.info(f"更新模块进度: {module_name} -> {status}")

        try:
            content = self._read_file(self.progress_file)

            # 更新对应模块的状态
            # 匹配模式: | **记忆区** | 或 | **PMC** | 等
            patterns = {
                "记忆区": r"\| \*\*记忆区\*\* \(memory/\) \|",
                "审核": r"\| \*\*审核\*\* \(review/\) \|",
                "PMC": r"\| \*\*PMC\*\* \(pmc/\) \|",
                "流水线": r"\| \*\*流水线\*\* \(pipeline/\) \|",
                "端到端集成": r"\| \*\*端到端集成\*\* \|",
                "分模块生成": r"\| \*\*分模块生成\*\* \|",
                "组装器": r"\| \*\*组装器\*\* \|",
            }

            for name, pattern in patterns.items():
                if module_name == name:
                    # 替换状态列
                    content = re.sub(
                        rf'(\| \*\*{re.escape(name)}\*\*.*?\| )[\w%📋✅ ]+(\|)',
                        rf'\g<1>{status}\2',
                        content
                    )
                    # 替换说明列
                    if detail:
                        content = re.sub(
                            rf'(\| \*\*{re.escape(name)}\*\*.*?\| {re.escape(status)} \|)[^\n]+',
                            rf'\1 {detail}',
                            content
                    )
                    break

            # 更新时间戳
            content = content.replace(
                "> **最后更新：",
                f"> **最后更新：{datetime.now().strftime('%Y-%m-%d')}"
            )

            self._write_file(self.progress_file, content)
            logger.info(f"模块进度更新成功: {module_name}")

        except Exception as e:
            logger.error(f"更新模块进度失败: {e}", exc_info=True)

    def add_test_record(
        self,
        test_case: str,
        result: str,
        files: str = ""
    ):
        """
        添加测试记录

        Args:
            test_case: 测试用例
            result: 结果 (✅成功/❌失败)
            files: 生成文件数
        """
        logger.info(f"添加测试记录: {test_case}")

        try:
            content = self._read_file(self.progress_file)

            now = datetime.now().strftime("%Y-%m-%d")
            new_row = f"| {now} | {test_case} | {result} | {files} |\n"

            # 查找测试记录表格，添加行
            if "| 日期 | 测试用例 | 结果 | 生成文件 |" in content:
                content = content.replace(
                    "| 日期 | 测试用例 | 结果 | 生成文件 |\n|------|----------|------|----------|",
                    f"| 日期 | 测试用例 | 结果 | 生成文件 |\n|------|----------|------|----------|\n{new_row}"
                )

            self._write_file(self.progress_file, content)
            logger.info("测试记录添加成功")

        except Exception as e:
            logger.error(f"添加测试记录失败: {e}", exc_info=True)

    def _read_file(self, filepath: Path) -> str:
        """读取文件"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def _write_file(self, filepath: Path, content: str):
        """写入文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def _update_session_row(
        self, content: str, session_id: str, time: str, requirement: str, status: str
    ) -> str:
        """更新已有的会话行"""
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if f"| {session_id} |" in line:
                # 分割行并更新
                parts = line.split('|')
                if len(parts) >= 5:
                    parts[2] = f" {time} "
                    parts[3] = f" {requirement[:50]}... "
                    parts[4] = f" {status} "
                    lines[i] = '|'.join(parts)
                break
        return '\n'.join(lines)

    def _insert_session_row(self, content: str, new_row: str) -> str:
        """插入新的会话行"""
        # 在 "> 暂无会话记录" 之前插入
        if "> 暂无会话记录" in content:
            content = content.replace("> 暂无会话记录", new_row + "\n> 暂无会话记录")
        return content


# 模块级单例
_indexer: Optional[MemIndexer] = None


def get_indexer() -> MemIndexer:
    """获取索引更新器单例"""
    global _indexer
    if _indexer is None:
        _indexer = MemIndexer()
    return _indexer


# 便捷函数
def update_session(session_id: str, requirement: str, modules: List[str], files: List[str], **kwargs):
    """快捷函数：更新会话索引"""
    get_indexer().update_session_index(session_id, requirement, modules, files, **kwargs)


def update_progress(module_name: str, status: str, detail: str = ""):
    """快捷函数：更新模块进度"""
    get_indexer().update_module_progress(module_name, status, detail)


def add_test(test_case: str, result: str, files: str = ""):
    """快捷函数：添加测试记录"""
    get_indexer().add_test_record(test_case, result, files)
