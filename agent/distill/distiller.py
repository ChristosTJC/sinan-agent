# agent/distill/distiller.py — 技能蒸馏器：从对话中提炼可复用技能提案
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 技能名校验正则：小写字母/数字 + 连字符，至少一个字符
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Proposal:
    """蒸馏提案 —— 从对话中提炼的一条可复用知识/技能。

    Attributes:
        type: 提案类型（new_skill / new_knowledge / update_skill）。
        reason: 为何提出此提案（用于人工审核）。
        name: 技能名（new_skill/update_skill 时使用，小写连字符）。
        description: 简短描述。
        content: 正文内容（Markdown）。
        category: 知识分类（new_knowledge 时使用，如 tips/pitfalls/error_codes）。
        title: 知识标题（new_knowledge 时使用）。
    """

    type: str
    reason: str
    name: str = ""
    description: str = ""
    content: str = ""
    category: str = ""
    title: str = ""


# ---------------------------------------------------------------------------
# SkillDistiller
# ---------------------------------------------------------------------------


class SkillDistiller:
    """技能蒸馏器 —— 分析对话记录，生成可复用的技能/知识提案。

    典型用法::

        distiller = SkillDistiller(max_proposals=5)
        proposals = distiller.analyze(messages, client=llm_client)

    Attributes:
        max_proposals: 单次分析最多返回的提案数，防止提案爆炸。
    """

    def __init__(self, max_proposals: int = 8) -> None:
        self.max_proposals = max_proposals

    # ── 转录构建 ──────────────────────────────────────────────

    @staticmethod
    def _build_transcript(messages: List[Dict[str, Any]]) -> str:
        """从消息列表构建分析转录文本，过滤系统消息和临时知识注入。

        Args:
            messages: 对话消息列表，每项含 role/content。

        Returns:
            纯对话文本，每条消息以 ``[角色]`` 前缀。
        """
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            # 跳过系统消息
            if role == "system":
                continue
            # 跳过知识库临时注入（自动注入的上下文）
            if "知识库内容" in content and role == "system":
                continue
            label = {"user": "[用户]", "assistant": "[司南]"}.get(role, f"[{role}]")
            lines.append(f"{label} {content}")
        return "\n".join(lines)

    # ── 响应解析 ──────────────────────────────────────────────

    def _parse_response(self, raw: str) -> List[Proposal]:
        """解析 LLM 原始响应，提取提案列表。

        容错处理：`` ```json ``` 围栏、纯 JSON、坏 JSON 均能优雅降级。

        Args:
            raw: LLM 返回的原始文本。

        Returns:
            成功解析的 Proposal 列表；解析失败返回空列表。
        """
        # 尝试去除 ```json ... ``` 围栏
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # 找到第一个换行后的内容，去掉最后的三反引号
            first_nl = cleaned.find("\n")
            if first_nl != -1:
                cleaned = cleaned[first_nl + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[: -3].strip()

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("蒸馏响应解析失败，非有效 JSON")
            return []

        if not isinstance(data, dict) or "proposals" not in data:
            return []

        proposals: list[Proposal] = []
        items = data.get("proposals", [])
        if not isinstance(items, list):
            return []

        for item in items:
            if not isinstance(item, dict):
                continue
            validated = self._validate_proposal(item)
            if validated is not None:
                proposals.append(validated)

        return proposals

    # ── 提案校验 ──────────────────────────────────────────────

    def _validate_proposal(self, data: Dict[str, Any]) -> Optional[Proposal]:
        """校验单条提案数据，拒绝不合法或危险的提案。

        拒绝条件：
        - 技能名含路径穿越（``../``）
        - 技能名含大写字母或下划线（仅允许 ``a-z0-9-``）
        - 类型不在允许集合内

        Args:
            data: 原始提案字典。

        Returns:
            通过校验的 Proposal 实例，或 None。
        """
        ptype = data.get("type", "")
        # 拒绝未知类型
        if ptype not in ("new_skill", "update_skill", "new_knowledge"):
            return None
        reason = str(data.get("reason", ""))

        name = ""
        if ptype in ("new_skill", "update_skill"):
            name = str(data.get("name", ""))
            if not name or not _NAME_PATTERN.match(name):
                return None
            # 额外防御路径穿越
            if ".." in name or "/" in name:
                return None

        # new_knowledge 类型
        if ptype == "new_knowledge":
            title = str(data.get("title", ""))
            category = str(data.get("category", ""))
            content = str(data.get("content", ""))
            return Proposal(
                type=ptype,
                reason=reason,
                title=title,
                category=category,
                content=content,
            )

        # new_skill / update_skill 类型
        description = str(data.get("description", ""))
        content = str(data.get("content", ""))

        return Proposal(
            type=ptype,
            reason=reason,
            name=name,
            description=description,
            content=content,
        )

    # ── 主入口 ────────────────────────────────────────────────

    def analyze(
        self,
        messages: List[Dict[str, Any]],
        client: Any,
        existing_skills: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Proposal]:
        """分析对话并生成技能提案。

        Args:
            messages: 对话消息列表。
            client: LLM 客户端（需有 ``chat()`` 方法，返回对象含 ``content`` 属性）。
            existing_skills: 已有技能列表，用于去重和上下文。

        Returns:
            提案列表，数量不超过 ``max_proposals``。调用失败返回空列表。
        """
        transcript = self._build_transcript(messages)

        existing_text = ""
        if existing_skills:
            names = [s.get("name", "") for s in existing_skills]
            existing_text = "\n已有技能: " + ", ".join(names) if names else ""

        prompt = f"""你是一个嵌入式开发技能蒸馏器。分析以下会话，提炼可复用知识。

{existing_text}

请输出 JSON:
{{
  "proposals": [
    {{
      "type": "new_skill" | "update_skill" | "new_knowledge",
      "name": "技能名（小写连字符，如 i2c-debug）",
      "description": "简短描述",
      "content": "技能/知识正文（Markdown 格式）",
      "reason": "为何值得保存",
      ...  // new_knowledge 额外需要 category/title
    }}
  ]
}}

会话记录:
{transcript}
"""

        try:
            response = client.chat(prompt)
            all_proposals = self._parse_response(response.content)
        except Exception:
            logger.exception("蒸馏分析 LLM 调用失败")
            return []

        # 截断到最大提案数
        return all_proposals[: self.max_proposals]
