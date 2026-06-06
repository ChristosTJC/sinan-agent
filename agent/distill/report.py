# agent/distill/report.py — 蒸馏报告：展示提案并支持逐项确认/跳过
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .distiller import Proposal
from .quality_scorer import QualityReport

# 提案类型 → 中文标签映射
_TYPE_LABELS: Dict[str, str] = {
    "new_skill": "P1 新技能",
    "update_skill": "P1 更新技能",
    "new_knowledge": "P2 新知识",
}


class DistillReport:
    """蒸馏报告 —— 汇总所有提案，支持交互式确认/跳过。

    典型用法::

        report = DistillReport(proposals)
        print(report.render())
        report.confirm(0)
        report.skip(1)
        report.confirm_all()
        # report.confirmed   → 已确认的提案
        # report.skipped     → 已跳过的提案

    Attributes:
        proposals: 原始提案列表。
        confirmed: 已确认的提案列表（按确认顺序）。
        skipped: 已跳过的提案列表（按跳过顺序）。
    """

    def __init__(
        self,
        proposals: List[Proposal],
        quality_reports: Optional[Dict[int, QualityReport]] = None,
        quality_threshold: float = 0.6,
    ) -> None:
        self.proposals = list(proposals)
        self.quality_reports = quality_reports or {}
        self.quality_threshold = quality_threshold
        self._confirmed: List[Proposal] = []
        self._skipped: List[Proposal] = []
        self._decision: Dict[int, str] = {}  # index → "confirmed" | "skipped"

    @property
    def confirmed(self) -> List[Proposal]:
        return list(self._confirmed)

    @property
    def skipped(self) -> List[Proposal]:
        return list(self._skipped)

    def iter_proposals(self) -> Iterable[tuple[int, Proposal]]:
        """按索引顺序迭代提案，供 REPL 逐项确认使用。"""
        return enumerate(self.proposals)

    # ── 决策方法 ──────────────────────────────────────────────

    def confirm(self, idx: int) -> None:
        """确认索引为 ``idx`` 的提案。"""
        if 0 <= idx < len(self.proposals):
            self._decision[idx] = "confirmed"
            p = self.proposals[idx]
            if p not in self._confirmed:
                self._confirmed.append(p)
            if p in self._skipped:
                self._skipped.remove(p)

    def skip(self, idx: int) -> None:
        """跳过索引为 ``idx`` 的提案。"""
        if 0 <= idx < len(self.proposals):
            self._decision[idx] = "skipped"
            p = self.proposals[idx]
            if p not in self._skipped:
                self._skipped.append(p)
            if p in self._confirmed:
                self._confirmed.remove(p)

    def confirm_all(self) -> None:
        """确认所有推荐提案；低质量提案默认跳过。"""
        self._skipped.clear()
        self._confirmed.clear()
        for i, p in enumerate(self.proposals):
            if self._is_low_quality(i):
                self._decision[i] = "skipped"
                self._skipped.append(p)
            else:
                self._decision[i] = "confirmed"
                self._confirmed.append(p)

    def skip_all(self) -> None:
        """跳过所有提案。"""
        self._confirmed.clear()
        self._skipped.clear()
        for i, p in enumerate(self.proposals):
            self._decision[i] = "skipped"
            self._skipped.append(p)

    def _is_low_quality(self, idx: int) -> bool:
        quality = self.quality_reports.get(idx)
        return quality is not None and quality.total_score < self.quality_threshold

    # ── 渲染方法 ──────────────────────────────────────────────

    def render(self) -> str:
        """渲染完整报告文本，包含提案分类汇总和逐个详情。

        Returns:
            格式化的中文报告字符串。
        """
        if not self.proposals:
            return "🎯 本次会话无可提炼的复用知识。\n"

        # 按类型统计
        counts: Dict[str, int] = {}
        for p in self.proposals:
            label = _TYPE_LABELS.get(p.type, p.type)
            counts[label] = counts.get(label, 0) + 1

        lines: list[str] = ["=" * 40, "📋 司南蒸馏报告", "=" * 40, ""]
        lines.append("提案汇总:")
        for label, count in sorted(counts.items()):
            lines.append(f"  {label}: {count}")
        lines.append("")
        lines.append("-" * 40)

        for i, p in enumerate(self.proposals):
            lines.append(self.render_proposal(i, p))
            lines.append("-" * 40)

        lines.append("")
        lines.append(f"共 {len(self.proposals)} 条提案。输入 'y' 逐项确认，'a' 应用所有推荐项，'n' 跳过。")
        return "\n".join(lines)

    def render_proposal(self, idx: int, proposal: Proposal) -> str:
        """渲染单条提案的预览文本。

        Args:
            idx: 提案序号（从 0 开始）。
            proposal: 提案对象。

        Returns:
            格式化的提案预览文本。
        """
        label = _TYPE_LABELS.get(proposal.type, proposal.type)
        parts: list[str] = [f"[{idx}] {label}"]
        if proposal.name:
            parts.append(f"  名称: {proposal.name}")
        if proposal.title:
            parts.append(f"  标题: {proposal.title}")
        if proposal.category:
            parts.append(f"  分类: {proposal.category}")
        if proposal.description:
            parts.append(f"  描述: {proposal.description}")
        if proposal.reason:
            parts.append(f"  理由: {proposal.reason}")
        if proposal.content:
            preview = proposal.content[:200]
            if len(proposal.content) > 200:
                preview += "..."
            parts.append(f"  内容: {preview}")
        quality = self.quality_reports.get(idx)
        if quality is not None:
            status = "建议应用" if quality.total_score >= self.quality_threshold else "不建议应用"
            parts.append(f"  质量: {quality.total_score:.2f}/1.00 ({status})")
            if quality.issues:
                parts.append(f"  问题: {'；'.join(quality.issues)}")
            if quality.suggestions:
                parts.append(f"  建议: {'；'.join(quality.suggestions)}")
        return "\n".join(parts)

    def summary(self, applied: Optional[int] = None) -> str:
        """渲染确认流程摘要。"""
        applied_count = len(self._confirmed) if applied is None else applied
        text = (
            f"\n  蒸馏完成：已应用 {applied_count} 条，"
            f"跳过 {len(self._skipped)} 条，共 {len(self.proposals)} 条\n"
        )
        low_quality_skipped = sum(
            1 for idx, proposal in enumerate(self.proposals)
            if self._decision.get(idx) == "skipped" and self._is_low_quality(idx)
        )
        if low_quality_skipped:
            text += f"  其中 {low_quality_skipped} 条低质量技能提案未自动应用，可逐项 y 手动覆盖。\n"
        return text
