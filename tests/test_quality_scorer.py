# tests/test_quality_scorer.py
from agent.distill.quality_scorer import QualityScorer, SkillProposal, QualityReport

def test_quality_scorer_completeness():
    scorer = QualityScorer()

    proposal = SkillProposal(
        name="test_skill",
        description="测试技能",
        steps=["步骤1", "步骤2"],
        examples=["示例1"],
        metadata={}
    )

    report = scorer.score(proposal)

    assert report.completeness_score > 0
    assert report.total_score > 0

def test_quality_scorer_filter_low_quality():
    scorer = QualityScorer(threshold=0.6)

    low_quality = SkillProposal(
        name="bad",
        description="差",
        steps=[],
        examples=[],
        metadata={}
    )

    report = scorer.score(low_quality)
    assert report.total_score < 0.6
    assert not scorer.should_accept(low_quality)

def test_to_skill_proposal_extracts_steps_and_examples_from_distill_proposal():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import to_skill_proposal

    proposal = Proposal(
        type="new_skill",
        name="i2c-debug",
        description="用于 I2C 总线异常时复用的系统化排查流程，覆盖上拉、电平、地址扫描和验证。",
        content=(
            "## 触发条件\nI2C 设备无响应\n\n"
            "## 步骤\n"
            "1. 检查 SDA/SCL 是否有合适的上拉电阻\n"
            "2. 使用逻辑分析仪确认时钟和 ACK 波形\n"
            "3. 使用 i2cdetect 或等价工具扫描设备地址\n\n"
            "## 示例\n"
            "- i2cdetect -y 1\n"
        ),
        reason="排查流程可复用",
    )

    skill = to_skill_proposal(proposal)

    assert skill.name == "i2c-debug"
    assert skill.metadata["type"] == "new_skill"
    assert skill.steps == [
        "检查 SDA/SCL 是否有合适的上拉电阻",
        "使用逻辑分析仪确认时钟和 ACK 波形",
        "使用 i2cdetect 或等价工具扫描设备地址",
    ]
    assert skill.examples == ["i2cdetect -y 1"]


def test_quality_scorer_scores_distill_skill_proposal():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import QualityScorer

    proposal = Proposal(
        type="new_skill",
        name="uart-noise-debug",
        description="用于 UART 输出乱码或丢字节时的可复用排查流程，覆盖波特率、地线、采样和验证步骤。",
        content=(
            "## 步骤\n"
            "1. 检查双方波特率、数据位、停止位和校验位配置\n"
            "2. 使用示波器确认 TX/RX 电平幅值和边沿质量\n"
            "3. 降低波特率后重复监听并记录错误是否消失\n"
            "## 示例\n"
            "- python3 -m agent.cli monitor --port /dev/ttyUSB0 --duration 5\n"
        ),
        reason="串口问题常见且流程可复用",
    )

    scorer = QualityScorer()
    report = scorer.score_distill_proposal(proposal)

    assert report.total_score >= scorer.threshold
    assert report.issues == []


def test_non_skill_proposal_is_not_skill_proposal():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import is_skill_proposal

    proposal = Proposal(
        type="new_knowledge",
        category="tips",
        title="MPU6050 地址",
        content="AD0=0 时地址为 0x68",
        reason="知识条目",
    )

    assert not is_skill_proposal(proposal)


def test_example_only_section_does_not_fallback_to_steps():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import to_skill_proposal

    proposal = Proposal(
        type="new_skill",
        name="uart-monitor-command",
        description="用于 UART 监听命令复用的记录，当前只有命令示例，没有形成可执行排查步骤。",
        content="## 示例\n- python3 -m agent.cli monitor --port /dev/ttyUSB0 --duration 5\n",
        reason="记录命令示例",
    )

    skill = to_skill_proposal(proposal)

    assert skill.steps == []
    assert skill.examples == ["python3 -m agent.cli monitor --port /dev/ttyUSB0 --duration 5"]


def test_quality_scorer_rejects_example_only_distill_proposal():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import QualityScorer

    proposal = Proposal(
        type="new_skill",
        name="uart-monitor-command",
        description="用于 UART 监听命令复用的记录，当前只有命令示例，没有形成可执行排查步骤。",
        content="## 示例\n- python3 -m agent.cli monitor --port /dev/ttyUSB0 --duration 5\n",
        reason="记录命令示例",
    )

    scorer = QualityScorer()
    report = scorer.score_distill_proposal(proposal)

    assert report.total_score < scorer.threshold
    assert report.issues


def test_plain_list_without_headings_falls_back_to_steps():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import to_skill_proposal

    proposal = Proposal(
        type="new_skill",
        name="spi-debug",
        description="用于 SPI 总线异常时复用的系统化排查流程。",
        content=(
            "1. 确认 MOSI/MISO/SCLK/CS 引脚映射正确\n"
            "2. 使用逻辑分析仪检查 CPOL 和 CPHA 配置\n"
            "- 降低 SPI 时钟后重新读取设备 ID\n"
        ),
        reason="排查流程可复用",
    )

    skill = to_skill_proposal(proposal)

    assert skill.steps == [
        "确认 MOSI/MISO/SCLK/CS 引脚映射正确",
        "使用逻辑分析仪检查 CPOL 和 CPHA 配置",
        "降低 SPI 时钟后重新读取设备 ID",
    ]


def test_to_skill_proposal_accepts_tolerant_heading_forms():
    from agent.distill.distiller import Proposal
    from agent.distill.quality_scorer import to_skill_proposal

    proposal = Proposal(
        type="new_skill",
        name="can-bus-debug",
        description="用于 CAN 总线异常时复用的系统化排查流程，覆盖终端电阻、波特率和错误帧验证。",
        content=(
            "# Steps:\n"
            "1. 检查总线两端 120 欧姆终端电阻是否存在\n"
            "2. 确认节点波特率和采样点配置一致\n"
            "###### 示例：\n"
            "- candump can0\n"
        ),
        reason="排查流程可复用",
    )

    skill = to_skill_proposal(proposal)

    assert skill.steps == [
        "检查总线两端 120 欧姆终端电阻是否存在",
        "确认节点波特率和采样点配置一致",
    ]
    assert skill.examples == ["candump can0"]
