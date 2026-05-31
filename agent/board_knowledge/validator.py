"""板卡配置文件 JSON Schema 校验器。

支持严格模式（raise）与宽松模式（返回错误列表），
在 jsonschema 库未安装时优雅降级。

使用示例:
    >>> from agent.board_knowledge import BoardValidator
    >>> v = BoardValidator()
    >>> errors = v.validate(profile_dict)
    >>> if errors:
    ...     for e in errors:
    ...         print(e)
    >>> v.validate_or_raise(profile_dict)  # 失败时抛出 ValueError
"""

import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 可选依赖：jsonschema
# ---------------------------------------------------------------------------
try:
    import jsonschema  # type: ignore[import-untyped]
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


def _repo_root() -> Path:
    """推断仓库根目录。"""
    return Path(__file__).resolve().parent.parent.parent


def _default_schema_path() -> Path:
    """获取默认 JSON Schema 文件路径。"""
    return _repo_root() / "board_knowledge" / "schemas" / "board_profile.schema.json"


# ---------------------------------------------------------------------------
# BoardValidator
# ---------------------------------------------------------------------------


class BoardValidator:
    """板卡配置文件校验器。

    加载 JSON Schema Draft 2020-12 规范文件，对板卡配置字典进行校验。
    若 ``jsonschema`` 未安装，则以宽松模式运行：仅做基本的必填字段检查。
    """

    def __init__(self, schema_path: str | Path | None = None) -> None:
        """初始化校验器。

        Args:
            schema_path: JSON Schema 文件路径。为 None 时使用默认路径。
        """
        if schema_path is None:
            schema_path = _default_schema_path()
        self._schema_path: Path = Path(schema_path)
        self._schema: dict[str, Any] = {}
        self._loaded: bool = False

        if _HAS_JSONSCHEMA:
            self._load_schema()

    # ------------------------------------------------------------------
    # Schema 加载
    # ------------------------------------------------------------------

    def _load_schema(self) -> None:
        """从磁盘加载 JSON Schema 文件。"""
        if self._loaded or not _HAS_JSONSCHEMA:
            return

        if not self._schema_path.is_file():
            print(
                f"[BoardValidator] 警告：Schema 文件不存在: {self._schema_path}",
                file=sys.stderr,
            )
            return

        try:
            self._schema = json.loads(
                self._schema_path.read_text(encoding="utf-8")
            )
            self._loaded = True
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"[BoardValidator] 警告：无法加载 Schema 文件: {exc}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # 校验 — 严格模式
    # ------------------------------------------------------------------

    def validate_or_raise(self, profile: dict[str, Any]) -> None:
        """校验板卡配置字典，不合法时抛出 ValueError。

        Args:
            profile: 板卡配置字典。

        Raises:
            ValueError: 配置不符合 Schema 规范。
        """
        errors = self.validate(profile)
        if errors:
            raise ValueError(
                "板卡配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
            )

    # ------------------------------------------------------------------
    # 校验 — 宽松模式
    # ------------------------------------------------------------------

    def validate(self, profile: dict[str, Any]) -> list[str]:
        """校验板卡配置字典，返回错误信息列表。

        空列表表示校验通过。在 ``jsonschema`` 未安装时，
        仅检查必填字段是否存在。

        Args:
            profile: 板卡配置字典。

        Returns:
            错误信息字符串列表。每个元素描述一项校验失败。
        """
        errors: list[str] = []

        # ---- 基础类型检查 ------------------------------------------------
        if not isinstance(profile, dict):
            return ["板卡配置必须是一个 JSON 对象 (dict)"]

        # ---- jsonschema 完整校验 -----------------------------------------
        if _HAS_JSONSCHEMA and self._loaded:
            try:
                validator_cls = jsonschema.validators.validator_for(self._schema)
                validator_instance = validator_cls(self._schema)
                for err in validator_instance.iter_errors(profile):
                    # 构建人类可读的错误路径
                    path = " -> ".join(str(p) for p in err.absolute_path) or "(根)"
                    errors.append(f"{path}: {err.message}")
                return errors
            except jsonschema.exceptions.SchemaError as exc:
                return [f"Schema 文件本身有误: {exc}"]
            except Exception as exc:
                return [f"校验过程中发生意外错误: {exc}"]

        # ---- 降级模式：手动检查必填字段 ----------------------------------
        if not _HAS_JSONSCHEMA:
            errors.append(
                "提示: jsonschema 库未安装，仅进行基础的必填字段检查。"
                "安装方式: pip install jsonschema"
            )

        required_fields: list[str] = [
            "schema_version",
            "board_id",
            "display_name",
            "mcu",
            "ports",
            "peripherals",
        ]

        for field in required_fields:
            if field not in profile:
                errors.append(f"缺少必填字段: '{field}'")
            elif profile[field] is None:
                errors.append(f"必填字段 '{field}' 不能为 null")

        # mcu 必填子字段
        mcu = profile.get("mcu", {})
        if isinstance(mcu, dict):
            for sub in ["arch", "clock", "flash", "ram", "voltage"]:
                if sub not in mcu:
                    errors.append(f"mcu. 缺少必填子字段: '{sub}'")

        # ports 类型检查
        ports = profile.get("ports", [])
        if not isinstance(ports, list):
            errors.append("'ports' 必须是一个数组 (list)")
        else:
            for i, port in enumerate(ports):
                if not isinstance(port, dict):
                    errors.append(f"ports[{i}] 必须是对象 (dict)")
                    continue
                if "name" not in port:
                    errors.append(f"ports[{i}] 缺少必填字段: 'name'")
                if "type" not in port:
                    errors.append(f"ports[{i}] 缺少必填字段: 'type'")
                if "pins" not in port:
                    errors.append(f"ports[{i}] 缺少必填字段: 'pins'")

        # peripherals 类型检查
        periphs = profile.get("peripherals", [])
        if not isinstance(periphs, list):
            errors.append("'peripherals' 必须是一个数组 (list)")
        else:
            for i, ph in enumerate(periphs):
                if not isinstance(ph, dict):
                    errors.append(f"peripherals[{i}] 必须是对象 (dict)")
                    continue
                if "name" not in ph:
                    errors.append(f"peripherals[{i}] 缺少必填字段: 'name'")
                if "kind" not in ph:
                    errors.append(f"peripherals[{i}] 缺少必填字段: 'kind'")

        return errors
