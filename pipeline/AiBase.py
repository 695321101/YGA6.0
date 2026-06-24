# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: ai
file: pipeline/AiBase.py
responsibility: AI 调用基础模块
authority: .claude/planning/12_接手文档.md
</YGA_FILE_ANCHOR>
"""
import json
import time
from typing import Dict, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class AiBase:
    """
    AI 调用基础模块

    封装 AI API 调用，统一处理配置、超时、重试
    """

    def __init__(self):
        self.config = self._load_config()
        self.api_base = self.config.get("api_base", "")
        self.api_key = self.config.get("api_key", "")
        self.model = self.config.get("model", "gpt-3.5-turbo")
        self.proxy = self.config.get("proxy_url", "")

    def _load_config(self) -> Dict:
        """加载 AI 配置"""
        config_path = Path(__file__).parent.parent / "config" / "ai_config.json"
        if not config_path.exists():
            return {}

        with open(config_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)

    def call(self, prompt: str, system: str = "", temperature: float = 0.7, max_tokens: int = 4096) -> str:
        """
        调用 AI 接口

        Args:
            prompt: 用户提示词
            system: 系统提示词（可选）
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            AI 响应内容
        """
        import requests
        import time

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # 配置
        config = {
            "headers": headers,
            "json": data,
            "timeout": 120,
            "verify": False  # 禁用 SSL 验证（兼容性问题）
        }

        proxies = None
        if self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}

        # 重试 5 次，带延迟
        last_error = None
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                if proxies:
                    response = requests.post(url, proxies=proxies, **config)
                else:
                    response = requests.post(url, **config)

                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content']
                else:
                    last_error = RuntimeError(f"API 返回错误: {response.status_code}")
            except Exception as e:
                last_error = e
                # SSL 错误，增加等待时间后重试
                if attempt < max_attempts - 1:
                    wait_time = (attempt + 1) * 2  # 2s, 4s, 6s, 8s
                    time.sleep(wait_time)
                continue

        raise RuntimeError(f"AI 调用失败（重试{max_attempts}次）: {last_error}")


# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: 开发中
# contract: 12_接手文档.md
# </YGA_END_ANCHOR>