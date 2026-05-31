"""板卡知识库管理器。

负责板卡配置文件的加载、存储、查询以及为 LLM 构建上下文注入字符串。

目录约定:
    board_knowledge/boards/*.json  —— 所有板卡配置文件存放于此
    board_knowledge/schemas/board_profile.schema.json —— JSON Schema 校验文件

使用示例:
    >>> from agent.board_knowledge import BoardKnowledgeBase
    >>> bkb = BoardKnowledgeBase()
    >>> boards = bkb.list_boards()
    >>> profile = bkb.get_profile("example_stm32f407")
    >>> ctx = bkb.build_context(["example_stm32f407"])
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .validator import BoardValidator


def _repo_root() -> Path:
    """推断仓库根目录：从当前文件向上三级 (agent/board_knowledge/ -> agent/ -> repo-root)。"""
    return Path(__file__).resolve().parent.parent.parent


class BoardKnowledgeBase:
    """板卡知识库。

    管理 board_knowledge/boards/ 下的所有 JSON 配置文件，
    提供加载、查询、创建、更新和 LLM 上下文构建接口。
    """

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def __init__(self, boards_dir: str | Path | None = None) -> None:
        """初始化板卡知识库。

        Args:
            boards_dir: 板卡配置文件所在目录。为 None 时自动推导为
                        ``<repo_root>/board_knowledge/boards/``。
        """
        if boards_dir is None:
            boards_dir = _repo_root() / "board_knowledge" / "boards"
        self._boards_dir: Path = Path(boards_dir)
        self._cache: dict[str, dict[str, Any]] = {}
        self._validator: BoardValidator = BoardValidator()
        self._schema_path: Path = (
            _repo_root() / "board_knowledge" / "schemas" / "board_profile.schema.json"
        )

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def list_boards(self) -> list[str]:
        """列出所有已知板卡的 board_id 列表。

        Returns:
            板卡 ID 字符串列表（例如 ``["example_stm32f407", "example_esp32s3"]``）。
        """
        if not self._boards_dir.is_dir():
            return []

        board_ids: list[str] = []
        for fpath in sorted(self._boards_dir.glob("*.json")):
            # 跳过以 . 或 _ 开头的非配置文件
            if fpath.name.startswith(".") or fpath.name.startswith("_"):
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                bid = data.get("board_id")
                if isinstance(bid, str) and bid.strip():
                    board_ids.append(bid.strip())
            except (json.JSONDecodeError, OSError):
                continue
        return board_ids

    def get_profile(self, board_id: str) -> dict[str, Any] | None:
        """获取指定板卡的完整配置。

        Args:
            board_id: 板卡唯一标识符（如 ``"example_stm32f407"``）。

        Returns:
            板卡配置字典；若未找到则返回 None。
        """
        self.validate_board_id(board_id)

        # 命中缓存直接返回
        if board_id in self._cache:
            return self._cache[board_id]

        fpath = self._boards_dir / f"{board_id}.json"
        if not fpath.is_file():
            return None

        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            self._cache[board_id] = data
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def get_ports(self, board_id: str) -> list[dict[str, Any]]:
        """获取指定板卡的对外接口列表。

        Args:
            board_id: 板卡唯一标识符。

        Returns:
            接口字典列表（``ports`` 字段），若板卡不存在则返回空列表。
        """
        profile = self.get_profile(board_id)
        if profile is None:
            return []
        return profile.get("ports", [])

    def get_peripherals(self, board_id: str) -> list[dict[str, Any]]:
        """获取指定板卡的板载外设列表。

        Args:
            board_id: 板卡唯一标识符。

        Returns:
            外设字典列表（``peripherals`` 字段），若板卡不存在则返回空列表。
        """
        profile = self.get_profile(board_id)
        if profile is None:
            return []
        return profile.get("peripherals", [])

    # ------------------------------------------------------------------
    # 写入接口
    # ------------------------------------------------------------------

    def create_board(self, board_id: str, profile_dict: dict[str, Any]) -> bool:
        """创建新的板卡配置文件。

        Args:
            board_id:   板卡唯一标识符。会自动写入 profile_dict['board_id']。
            profile_dict: 符合 board_profile.schema.json 的完整配置字典。

        Returns:
            True 表示创建成功；False 表示 board_id 已存在或校验失败。

        Raises:
            ValueError: 配置不符合 JSON Schema 校验规则。
        """
        self.validate_board_id(board_id)
        fpath = self._boards_dir / f"{board_id}.json"
        if fpath.exists():
            return False

        profile_dict["board_id"] = board_id
        self._validator.validate_or_raise(profile_dict)

        fpath.write_text(
            json.dumps(profile_dict, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._cache[board_id] = profile_dict
        return True

    def update_board(self, board_id: str, updates: dict[str, Any]) -> bool:
        """更新已有板卡配置中的字段。

        采用浅合并策略：updates 中的顶层键会覆盖原有值，未提及的键保持不变。

        Args:
            board_id: 板卡唯一标识符。
            updates:  需要更新的字段字典（顶层键）。

        Returns:
            True 表示更新成功；False 表示板卡不存在。
        """
        profile = self.get_profile(board_id)
        if profile is None:
            return False

        profile.update(updates)
        # board_id 不能被覆盖
        profile["board_id"] = board_id

        self._validator.validate_or_raise(profile)

        fpath = self._boards_dir / f"{board_id}.json"
        fpath.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._cache[board_id] = profile
        return True

    # ------------------------------------------------------------------
    # LLM 上下文注入
    # ------------------------------------------------------------------

    def build_context(self, board_ids: list[str]) -> str:
        """为 LLM 构建可供注入的板卡上下文文本。

        生成的文本包含每个板卡的 MCU 信息、接口列表、外设列表和常见陷阱，
        适合直接追加到 System Prompt 或 User Message 中。

        Args:
            board_ids: 需要包含的板卡 ID 列表。

        Returns:
            格式化的板卡上下文字符串。若所有 board_id 均无效则返回空字符串。
        """
        parts: list[str] = []
        header: str = "## 当前可用板卡\n"

        for bid in board_ids:
            profile = self.get_profile(bid)
            if profile is None:
                parts.append(f"- **{bid}**: ⚠ 未找到配置文件\n")
                continue

            display = profile.get("display_name", bid)
            mcu = profile.get("mcu", {})

            block: list[str] = []
            block.append(f"### {display} (`{bid}`)")
            block.append("")

            # MCU
            if mcu:
                mcu_lines: list[str] = ["**MCU 信息:**"]
                if mcu.get("model"):
                    mcu_lines.append(f"- 型号: {mcu['model']}")
                if mcu.get("arch"):
                    mcu_lines.append(f"- 架构: {mcu['arch']}")
                if mcu.get("clock"):
                    mcu_lines.append(f"- 主频: {mcu['clock']}")
                if mcu.get("flash"):
                    mcu_lines.append(f"- Flash: {mcu['flash']}")
                if mcu.get("ram"):
                    mcu_lines.append(f"- RAM: {mcu['ram']}")
                if mcu.get("voltage"):
                    mcu_lines.append(f"- 工作电压: {mcu['voltage']}")
                block.extend(mcu_lines)
                block.append("")

            # 接口
            ports = profile.get("ports", [])
            if ports:
                block.append("**对外接口:**")
                for p in ports:
                    ptype = p.get("type", "")
                    pname = p.get("name", "")
                    ppins = p.get("pins", {})
                    pin_str = ", ".join(f"{k}={v}" for k, v in ppins.items())
                    block.append(f"- {pname} ({ptype}): {pin_str}")
                    if p.get("notes"):
                        block.append(f"  - 备注: {p['notes']}")
                block.append("")

            # 外设
            periphs = profile.get("peripherals", [])
            if periphs:
                block.append("**板载外设:**")
                for ph in periphs:
                    phn = ph.get("name", "")
                    phk = ph.get("kind", "")
                    addr = ph.get("address", "")
                    addr_str = f", 地址={addr}" if addr else ""
                    block.append(f"- {phn} ({phk}{addr_str})")
                    if ph.get("notes"):
                        block.append(f"  - 备注: {ph['notes']}")
                block.append("")

            # 常见陷阱
            pitfalls = profile.get("common_pitfalls", [])
            if pitfalls:
                block.append("**常见陷阱:**")
                for pit in pitfalls:
                    block.append(f"- ⚠ {pit}")
                block.append("")

            parts.append("\n".join(block))

        if not any("未找到配置文件" not in p for p in parts) and len(parts) > 0:
            # 全部都是 "未找到"，返回空
            return ""
        return header + "\n---\n".join(parts)

    # ------------------------------------------------------------------
    # 输入校验
    # ------------------------------------------------------------------

    @staticmethod
    def validate_board_id(board_id: str) -> None:
        """校验 board_id 格式合法性。

        仅允许小写字母、数字和下划线，长度 1-63。

        Args:
            board_id: 待校验的板卡 ID。

        Raises:
            ValueError: 格式不合法时抛出。
        """
        if not board_id:
            raise ValueError("board_id 不能为空")
        if not re.fullmatch(r"[a-z0-9_]{1,63}", board_id):
            raise ValueError(
                f"board_id 格式不合法: '{board_id}'，"
                "仅允许小写字母、数字和下划线，长度 1-63"
            )
