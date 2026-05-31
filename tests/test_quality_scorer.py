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
