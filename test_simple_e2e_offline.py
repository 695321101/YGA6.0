# -*- coding: utf-8 -*-
"""
Simple 主链离线端到端测试（mock AI，不调用真实 API）
验证 P0 验收清单关键产物路径。
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import MemRouter
from pipeline import PipelineRouter
from review import AiArtifactReviewResult

MOCK_INTERFACES = """## 接口列表

### 1. 加法 POST /api/add
- 输入: a, b
- 输出: result

### 2. 减法 POST /api/sub
- 输入: a, b
- 输出: result
"""

MOCK_L3 = '''```python filename:main.py
# -*- coding: utf-8 -*-
"""
<YGA_FILE_ANCHOR v1>
module: app
file: main.py
responsibility: 计算器入口
exports: app
authority: test
</YGA_FILE_ANCHOR>
"""
import logging
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log"),
        logging.FileHandler(LOG_DIR / "error.log"),
    ],
)
logger = logging.getLogger(__name__)


def add(a: float, b: float) -> float:
    return a + b


def sub(a: float, b: float) -> float:
    return a - b


if __name__ == "__main__":
    try:
        logger.info("calculator ready")
    except Exception as e:
        logger.error("startup failed", exc_info=True)
        raise

# === 模块结束 ===
# <YGA_END_ANCHOR v1>
# status: test
# contract: interfaces.md
# next: run
# </YGA_END_ANCHOR>
```
'''


def _prepare_session():
    session_id = MemRouter.create_session("e2e_offline", "Simple E2E 离线")
    req = """## 项目信息
- 项目名称：计算器
- 技术栈：Python

## 功能列表
1. 加法
2. 减法
"""
    MemRouter.write(session_id, "requirement", req, source="AI")
    MemRouter.write(session_id, "requirement_confirm", "", source="User")
    status = MemRouter.get_phase_status(session_id)
    assert status["current_phase"] == "phase_2"
    ctx = MemRouter.read(session_id, "context")
    assert ctx.get("requirement_ready") is True
    return session_id


def test_simple_orchestrator_offline():
    print("=" * 60)
    print("Simple 主链离线 E2E")
    print("=" * 60)

    session_id = _prepare_session()
    root = Path(__file__).parent

    def mock_l2(prompt, requirement):
        return MOCK_INTERFACES

    def mock_l3(prompt, interfaces):
        return MOCK_L3

    def mock_l2_review(requirement, interfaces):
        return AiArtifactReviewResult(passed=True, verdict="通过", reason="mock")

    with patch("pipeline.AiL2.AiL2.generate_interface", side_effect=mock_l2), patch(
        "pipeline.AiL3.AiL3.generate_code", side_effect=mock_l3
    ), patch(
        "review.AiArtifactReviewer.AiArtifactReviewer.review_l2_interface",
        side_effect=mock_l2_review,
    ):
        out = PipelineRouter.run(
            session_id,
            require_ai_review=True,
            skip_delivery_ai_review=True,
        )

    print(f"  success: {out.get('success')}")
    print(f"  message: {out.get('message')}")
    print(f"  orchestrator: {out.get('orchestrator')}")
    assert out.get("orchestrator") == "SimpleOrchestrator"
    assert out.get("success") is True, out

    # P0 产物检查
    sess = root / "memory" / "sessions" / session_id
    assert (sess / "logs" / "requirement.md").exists()
    assert (sess / "logs" / "interfaces.md").exists()
    assert (sess / "context" / "pmc" / "pmc_context.yaml").exists()
    assert (sess / "context" / "test" / "test_context.yaml").exists()
    assert (sess / "context" / "review" / "review_context.yaml").exists()

    code_dir = root / "output" / session_id / "modules"
    assert code_dir.exists()
    py_files = list(code_dir.rglob("*.py"))
    assert len(py_files) >= 1

    phase = MemRouter.get_phase_status(session_id)
    assert phase["current_phase"] == "phase_6"
    assert phase["phase_status"] == "completed"
    snap = MemRouter.latest_snapshot(session_id)
    assert snap is not None

    ctx = MemRouter.read(session_id, "context")
    assert ctx.get("interfaces_ready") is True

    print("  P0 产物与 phase_6 快照: PASS")
    print("=" * 60)


if __name__ == "__main__":
    test_simple_orchestrator_offline()
    print("全部通过")