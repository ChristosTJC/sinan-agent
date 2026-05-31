"""司南嵌入式智能体 —— 硬件自动化工作流模块。

提供端到端的硬件开发流水线：
- 板卡自动检测
- 固件编译
- 固件烧写
- 串口验证
"""

from agent.workflows.hardware_golden_path import HardwareGoldenPath

__all__ = ["HardwareGoldenPath"]
