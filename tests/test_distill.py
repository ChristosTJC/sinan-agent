"""技能蒸馏模块测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock


# ─── distiller 测试 ───────────────────────────────────────────

def test_proposal_defaults():
    """Proposal 默认值。"""
    from agent.distill.distiller import Proposal
    p = Proposal(type="new_skill", reason="测试")
    assert p.type == "new_skill"
    assert p.reason == "测试"
    assert p.name == ""
    assert p.description == ""
    assert p.content == ""
    assert p.section == ""

    positional = Proposal("new_knowledge", "测试", "", "", "正文", "tips", "标题")
    assert positional.category == "tips"
    assert positional.title == "标题"
    assert positional.section == ""


def test_build_transcript_filters_system():
    """_build_transcript 过滤 system 消息。"""
    from agent.distill.distiller import SkillDistiller
    msgs = [
        {"role": "system", "content": "你是司南"},
        {"role": "user", "content": "帮我查 I2C 地址"},
        {"role": "assistant", "content": "MPU6050 地址是 0x68"},
    ]
    transcript = SkillDistiller._build_transcript(msgs)
    assert "你是司南" not in transcript
    assert "帮我查 I2C 地址" in transcript
    assert "MPU6050" in transcript


def test_build_transcript_filters_knowledge_context():
    """_build_transcript 过滤临时知识注入。"""
    from agent.distill.distiller import SkillDistiller
    msgs = [
        {"role": "system", "content": "以下是与用户问题相关的知识库内容: MPU6050"},
        {"role": "user", "content": "hello"},
    ]
    transcript = SkillDistiller._build_transcript(msgs)
    assert "知识库内容" not in transcript
    assert "hello" in transcript


def test_parse_response_valid():
    """解析有效 JSON 响应。"""
    from agent.distill.distiller import SkillDistiller
    d = SkillDistiller()
    raw = json.dumps({
        "proposals": [
            {
                "type": "new_skill",
                "name": "i2c-debug",
                "description": "I2C 调试方法",
                "content": "## 触发条件\n...\n## 步骤\n...\n## 验证\n...",
                "reason": "通用 I2C 调试",
            }
        ]
    })
    proposals = d._parse_response(raw)
    assert len(proposals) == 1
    assert proposals[0].type == "new_skill"
    assert proposals[0].name == "i2c-debug"


def test_parse_response_code_fence():
    """解析带 ```json 围栏的响应。"""
    from agent.distill.distiller import SkillDistiller
    d = SkillDistiller()
    raw = '```json\n{"proposals": []}\n```'
    proposals = d._parse_response(raw)
    assert proposals == []


def test_parse_response_bad_json():
    """坏 JSON 返回空列表。"""
    from agent.distill.distiller import SkillDistiller
    d = SkillDistiller()
    proposals = d._parse_response("not json at all")
    assert proposals == []


def test_parse_response_bad_items_skipped():
    """坏提案项被跳过，好项保留。"""
    from agent.distill.distiller import SkillDistiller
    d = SkillDistiller()
    raw = json.dumps({
        "proposals": [
            {"type": "bad_type", "reason": "no"},
            {
                "type": "new_knowledge",
                "category": "pitfalls",
                "title": "MPU6050 地址",
                "content": "AD0=0 → 0x68",
                "reason": "有用",
            },
            "not_a_dict",
        ]
    })
    proposals = d._parse_response(raw)
    assert len(proposals) == 1
    assert proposals[0].type == "new_knowledge"
    assert proposals[0].category == "pitfalls"


def test_validate_proposal_name_rejects_invalid():
    """技能名校验拒绝非法名称。"""
    from agent.distill.distiller import SkillDistiller
    d = SkillDistiller()
    # '../' 路径穿越
    p = d._validate_proposal({"type": "new_skill", "name": "../etc", "reason": "bad"})
    assert p is None
    # 大写
    p = d._validate_proposal({"type": "new_skill", "name": "BadName", "reason": "bad"})
    assert p is None
    # 下划线
    p = d._validate_proposal({"type": "new_skill", "name": "bad_name", "reason": "bad"})
    assert p is None
    # 有效
    p = d._validate_proposal({"type": "new_skill", "name": "good-name", "reason": "ok"})
    assert p is not None
    assert p.name == "good-name"
    # 带数字
    p = d._validate_proposal({"type": "new_skill", "name": "i2c-scl-recovery-2", "reason": "ok"})
    assert p is not None


def test_validate_update_skill_reads_section_with_default():
    """update_skill 提案携带章节名，缺省使用补充。"""
    from agent.distill.distiller import SkillDistiller

    d = SkillDistiller()

    explicit = d._validate_proposal({
        "type": "update_skill",
        "name": "i2c-debug",
        "section": "注意事项",
        "content": "补充 I2C 上拉阻值排查方法",
        "reason": "已有技能可增强",
    })
    assert explicit is not None
    assert explicit.type == "update_skill"
    assert explicit.name == "i2c-debug"
    assert explicit.section == "注意事项"
    assert explicit.content == "补充 I2C 上拉阻值排查方法"

    defaulted = d._validate_proposal({
        "type": "update_skill",
        "name": "i2c-debug",
        "content": "补充内容",
        "reason": "已有技能可增强",
    })
    assert defaulted is not None
    assert defaulted.section == "补充"


def test_validate_non_update_proposals_ignore_section():
    """非 update_skill 提案忽略章节名。"""
    from agent.distill.distiller import SkillDistiller

    d = SkillDistiller()

    new_skill = d._validate_proposal({
        "type": "new_skill",
        "name": "i2c-debug",
        "section": "注意事项",
        "content": "I2C 调试方法",
        "reason": "通用调试方法",
    })
    assert new_skill is not None
    assert new_skill.section == ""

    new_knowledge = d._validate_proposal({
        "type": "new_knowledge",
        "category": "tips",
        "title": "I2C 上拉",
        "section": "注意事项",
        "content": "上拉阻值需按总线电容估算",
        "reason": "可复用知识",
    })
    assert new_knowledge is not None
    assert new_knowledge.section == ""


def test_max_proposals_cap():
    """提案数封顶 — 在 analyze() 层面做截断。"""
    from agent.distill.distiller import SkillDistiller

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "proposals": [
            {"type": "new_knowledge", "category": "tips", "title": f"tip{i}", "content": "x", "reason": "x"}
            for i in range(10)
        ]
    })
    mock_client.chat.return_value = mock_response

    d = SkillDistiller(max_proposals=3)
    proposals = d.analyze(
        messages=[{"role": "user", "content": "test"}],
        client=mock_client,
    )
    assert len(proposals) == 3


def test_analyze_with_mock_client():
    """用 mock client 测试完整 analyze 流程。"""
    from agent.distill.distiller import SkillDistiller

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "proposals": [
            {
                "type": "new_skill",
                "name": "test-skill",
                "description": "测试技能",
                "content": "## 触发条件\n测试\n## 步骤\n1. 步骤\n## 验证\nOK",
                "reason": "测试",
            }
        ]
    })
    mock_client.chat.return_value = mock_response

    d = SkillDistiller()
    proposals = d.analyze(
        messages=[{"role": "user", "content": "测试"}],
        client=mock_client,
        existing_skills=[{"name": "existing", "description": "已有技能"}],
    )
    assert len(proposals) == 1
    assert proposals[0].name == "test-skill"
    mock_client.chat.assert_called_once()
    prompt = mock_client.chat.call_args.args[0]
    assert "update_skill" in prompt
    assert "section" in prompt


def test_analyze_client_error_returns_empty():
    """LLM 调用失败返回空列表，不抛异常。"""
    from agent.distill.distiller import SkillDistiller

    mock_client = MagicMock()
    mock_client.chat.side_effect = RuntimeError("网络超时")

    d = SkillDistiller()
    proposals = d.analyze(
        messages=[{"role": "user", "content": "测试"}],
        client=mock_client,
    )
    assert proposals == []


# ─── writer 测试 ──────────────────────────────────────────────

def test_write_skill_roundtrip():
    """写技能文件 + round-trip 校验。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        path = writer.write_skill(
            "test-skill", "测试技能",
            "## 触发条件\n测试\n## 步骤\n1. 步骤\n## 验证\nOK",
        )
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "name: test-skill" in content
        assert "source: distilled" in content
        assert "## 验证" in content


def test_write_skill_duplicate_skipped():
    """重复写同名技能被跳过。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        path1 = writer.write_skill("dup-skill", "测试", "# Test")
        assert path1 is not None
        path2 = writer.write_skill("dup-skill", "测试2", "# Test2")
        assert path2 is None  # 冲突跳过


def test_write_skill_name_rejected():
    """非法技能名被拒绝（路径穿越、空名）。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        assert writer.write_skill("../escape", "bad", "# x") is None
        assert writer.write_skill("", "bad", "# x") is None
        assert writer.write_skill("/etc/passwd", "bad", "# x") is None


def test_update_skill_append():
    """update_skill 追加章节。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        writer.write_skill(
            "update-test", "测试",
            "## 触发条件\n测试触发\n\n## 步骤\n1. 步骤",
        )
        path = writer.update_skill("update-test", "注意事项", "新的注意事项内容")
        assert path is not None
        content = path.read_text()
        assert "## 注意事项" in content
        assert "新的注意事项内容" in content


def test_update_skill_existing_section_appends():
    """update_skill 在已有章节末尾追加。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        writer.write_skill("append-test", "测试", "## 步骤\n1. 步骤一\n")
        writer.update_skill("append-test", "步骤", "2. 步骤二")
        content = (Path(tmp) / "append-test" / "SKILL.md").read_text()
        assert "1. 步骤一" in content
        assert "2. 步骤二" in content


def test_update_skill_from_curated():
    """update_skill 对策展技能生成覆盖副本，不改原文件。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        curated_dir = Path(tmp) / "curated" / "curated-skill"
        curated_dir.mkdir(parents=True)
        original_content = (
            "---\nname: curated-skill\ndescription: 策展技能\n---\n\n"
            "## 正文\n原始内容\n"
        )
        (curated_dir / "SKILL.md").write_text(original_content)

        user_dir = Path(tmp) / "user"
        writer = SkillWriter(user_skills_dir=user_dir)
        path = writer.update_skill(
            "curated-skill", "补充", "补充内容",
            project_skills_dir=Path(tmp) / "curated",
        )
        assert path is not None
        # 验证项目原文件未动
        assert (curated_dir / "SKILL.md").read_text() == original_content
        # 验证用户副本包含新内容
        user_content = path.read_text()
        assert "补充内容" in user_content
        assert "原始内容" in user_content


def test_update_skill_nonexistent():
    """update_skill 目标不存在返回 None。"""
    from agent.distill.writer import SkillWriter

    with tempfile.TemporaryDirectory() as tmp:
        writer = SkillWriter(user_skills_dir=Path(tmp))
        result = writer.update_skill("nonexistent", "section", "content")
        assert result is None


# ─── report 测试 ──────────────────────────────────────────────

def test_report_empty():
    """空提案报告。"""
    from agent.distill.report import DistillReport
    r = DistillReport([])
    assert "无可提炼" in r.render()


def test_report_with_proposals():
    """有提案的报告。"""
    from agent.distill.distiller import Proposal
    from agent.distill.report import DistillReport

    proposals = [
        Proposal(type="new_skill", name="test-skill", reason="测试", description="测试技能"),
        Proposal(type="new_knowledge", category="tips", title="测试知识", reason="测试2", content="知识内容"),
    ]
    r = DistillReport(proposals)
    rendered = r.render()
    assert "P1 新技能: 1" in rendered
    assert "P2 新知识: 1" in rendered


def test_report_confirm_skip():
    """逐项确认/跳过。"""
    from agent.distill.distiller import Proposal
    from agent.distill.report import DistillReport

    proposals = [
        Proposal(type="new_skill", name="a", reason="1"),
        Proposal(type="new_skill", name="b", reason="2"),
    ]
    r = DistillReport(proposals)
    r.confirm(0)
    r.skip(1)
    assert len(r.confirmed) == 1
    assert r.confirmed[0].name == "a"
    assert len(r.skipped) == 1


def test_report_confirm_all():
    """全部确认。"""
    from agent.distill.distiller import Proposal
    from agent.distill.report import DistillReport

    proposals = [Proposal(type="new_skill", name=f"s{i}", reason="x") for i in range(3)]
    r = DistillReport(proposals)
    r.confirm_all()
    assert len(r.confirmed) == 3
    assert len(r.skipped) == 0


def test_report_skip_all():
    """全部跳过。"""
    from agent.distill.distiller import Proposal
    from agent.distill.report import DistillReport

    proposals = [Proposal(type="new_skill", name=f"s{i}", reason="x") for i in range(3)]
    r = DistillReport(proposals)
    r.skip_all()
    assert len(r.confirmed) == 0
    assert len(r.skipped) == 3


def test_render_proposal_includes_details():
    """提案预览包含内容和理由。"""
    from agent.distill.distiller import Proposal
    from agent.distill.report import DistillReport

    p = Proposal(
        type="new_skill",
        name="test",
        reason="值得存",
        description="测试技能描述",
        content="## 触发条件\n测试触发\n## 步骤\n1. 做某事",
    )
    r = DistillReport([p])
    rendered = r.render_proposal(0, p)
    assert "测试技能描述" in rendered
    assert "值得存" in rendered


# ─── SkillLoader 双目录测试 ────────────────────────────────────

def test_skill_loader_dual_dir_user_priority():
    """用户技能覆盖策展同名技能。"""
    from agent.skills import SkillLoader

    with tempfile.TemporaryDirectory() as tmp:
        curated = Path(tmp) / "curated"
        user = Path(tmp) / "user"

        curated_skill = curated / "test-skill"
        curated_skill.mkdir(parents=True)
        (curated_skill / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: 策展版本\n---\n\n策展内容"
        )

        user_skill = user / "test-skill"
        user_skill.mkdir(parents=True)
        (user_skill / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: 用户版本\n---\n\n用户内容"
        )

        loader = SkillLoader(skills_dir=curated, user_skills_dir=user)
        skills = loader.load_all()
        skill = loader.get("test-skill")
        assert skill is not None
        assert skill.description == "用户版本"  # 用户优先
        assert len(skills) >= 1


def test_skill_loader_dual_dir_separate_skills():
    """双目录各自独立加载。"""
    from agent.skills import SkillLoader

    with tempfile.TemporaryDirectory() as tmp:
        curated = Path(tmp) / "curated"
        user = Path(tmp) / "user"

        (curated / "skill-a").mkdir(parents=True)
        (curated / "skill-a" / "SKILL.md").write_text(
            "---\nname: skill-a\ndescription: 策展A\n---\nA"
        )
        (user / "skill-b").mkdir(parents=True)
        (user / "skill-b" / "SKILL.md").write_text(
            "---\nname: skill-b\ndescription: 用户B\n---\nB"
        )

        loader = SkillLoader(skills_dir=curated, user_skills_dir=user)
        skills = loader.load_all()
        names = {s.name for s in skills}
        assert "skill-a" in names
        assert "skill-b" in names
