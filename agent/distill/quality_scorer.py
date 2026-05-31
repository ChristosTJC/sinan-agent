# agent/distill/quality_scorer.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SkillProposal:
    name: str
    description: str
    steps: List[str]
    examples: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

@dataclass
class QualityReport:
    completeness_score: float
    reusability_score: float
    clarity_score: float
    total_score: float
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

class QualityScorer:
    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    def score(self, proposal: SkillProposal) -> QualityReport:
        completeness = self._score_completeness(proposal)
        reusability = self._score_reusability(proposal)
        clarity = self._score_clarity(proposal)

        total = (completeness + reusability + clarity) / 3.0

        issues = []
        suggestions = []

        if completeness < 0.5:
            issues.append("缺少必需字段")
            suggestions.append("补充描述、步骤或示例")

        if reusability < 0.5:
            issues.append("可复用性低")
            suggestions.append("参数化步骤，避免硬编码")

        if clarity < 0.5:
            issues.append("清晰度不足")
            suggestions.append("增加描述长度，细化步骤")

        return QualityReport(
            completeness_score=completeness,
            reusability_score=reusability,
            clarity_score=clarity,
            total_score=total,
            issues=issues,
            suggestions=suggestions
        )

    def should_accept(self, proposal: SkillProposal) -> bool:
        report = self.score(proposal)
        return report.total_score >= self.threshold

    def _score_completeness(self, proposal: SkillProposal) -> float:
        score = 0.0

        if proposal.name:
            score += 0.2
        if proposal.description and len(proposal.description) >= 10:
            score += 0.3
        if proposal.steps and len(proposal.steps) >= 2:
            score += 0.3
        if proposal.examples:
            score += 0.2

        return min(score, 1.0)

    def _score_reusability(self, proposal: SkillProposal) -> float:
        score = 0.5  # 基础分

        # 检查是否有参数化步骤
        param_count = sum(1 for step in proposal.steps if "{" in step and "}" in step)
        if param_count > 0:
            score += 0.3

        # 检查是否有硬编码路径
        hardcoded = sum(1 for step in proposal.steps if "/home/" in step or "C:\\" in step)
        if hardcoded > 0:
            score -= 0.2

        return max(0.0, min(score, 1.0))

    def _score_clarity(self, proposal: SkillProposal) -> float:
        score = 0.0

        # 描述长度
        if len(proposal.description) >= 50:
            score += 0.4
        elif len(proposal.description) >= 20:
            score += 0.2

        # 步骤数量
        if 3 <= len(proposal.steps) <= 10:
            score += 0.3
        elif len(proposal.steps) > 0:
            score += 0.1

        # 步骤平均长度
        if proposal.steps:
            avg_len = sum(len(s) for s in proposal.steps) / len(proposal.steps)
            if avg_len >= 20:
                score += 0.3

        return min(score, 1.0)
