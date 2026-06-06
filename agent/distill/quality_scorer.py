# agent/distill/quality_scorer.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

_SKILL_TYPES = {"new_skill", "update_skill"}
_STEP_HEADINGS = {"步骤", "操作步骤", "流程", "排查步骤"}
_EXAMPLE_HEADINGS = {"示例", "examples", "example"}
_ITEM_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s*)(.+?)\s*$")

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

def is_skill_proposal(proposal: Any) -> bool:
    return getattr(proposal, "type", "") in _SKILL_TYPES

def to_skill_proposal(proposal: Any) -> SkillProposal:
    if not is_skill_proposal(proposal):
        raise ValueError(f"非技能提案不能评分: {getattr(proposal, 'type', '')}")

    content = str(getattr(proposal, "content", "") or "")
    description = str(getattr(proposal, "description", "") or getattr(proposal, "reason", "") or "")

    return SkillProposal(
        name=str(getattr(proposal, "name", "") or ""),
        description=description,
        steps=_extract_items(content, _STEP_HEADINGS, fallback_to_all=True),
        examples=_extract_items(content, _EXAMPLE_HEADINGS, fallback_to_all=False),
        metadata={"type": str(getattr(proposal, "type", ""))},
    )

def _extract_items(content: str, headings: set[str], *, fallback_to_all: bool) -> List[str]:
    section_lines = _extract_section_lines(content, headings)
    items = _items_from_lines(section_lines)
    if items:
        return items
    if not fallback_to_all:
        return []
    return _items_from_lines(content.splitlines())

def _extract_section_lines(content: str, headings: set[str]) -> List[str]:
    lines: List[str] = []
    in_section = False
    normalized_headings = {h.lower() for h in headings}
    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith("## "):
            heading = stripped.lstrip("#").strip().lower()
            if in_section:
                break
            in_section = heading in normalized_headings
            continue
        if in_section:
            lines.append(raw)
    return lines

def _items_from_lines(lines: List[str]) -> List[str]:
    items: List[str] = []
    for line in lines:
        match = _ITEM_RE.match(line)
        if match:
            item = match.group(1).strip()
            if item:
                items.append(item)
    return items

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

    def score_distill_proposal(self, proposal: Any) -> QualityReport:
        return self.score(to_skill_proposal(proposal))

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
