"""
配置加载器。

提供配置文件的加载、保存和验证功能。
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .models import SinanSettings


class ConfigLoader:
    """配置加载器。"""

    DEFAULT_PATHS = [
        Path("~/.sinan/settings.json").expanduser(),
        Path("./settings.json"),
        Path("./config.json"),
    ]

    @staticmethod
    def load(path: Optional[Path] = None) -> SinanSettings:
        """
        加载并验证配置文件。

        Args:
            path: 配置文件路径，None 时自动查找

        Returns:
            验证后的配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValidationError: 配置验证失败
            json.JSONDecodeError: JSON 格式错误
        """
        if path is None:
            path = ConfigLoader._find_config()
            if path is None:
                raise FileNotFoundError(
                    f"未找到配置文件，已搜索: {[str(p) for p in ConfigLoader.DEFAULT_PATHS]}"
                )

        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return SinanSettings(**data)

    @staticmethod
    def save(settings: SinanSettings, path: Path) -> None:
        """
        保存配置到文件。

        Args:
            settings: 配置对象
            path: 目标文件路径
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False)

    @staticmethod
    def validate(path: Path) -> tuple[bool, Optional[str]]:
        """
        验证配置文件（不加载）。

        Args:
            path: 配置文件路径

        Returns:
            (是否有效, 错误信息)
        """
        try:
            ConfigLoader.load(path)
            return True, None
        except FileNotFoundError as e:
            return False, f"文件不存在: {e}"
        except json.JSONDecodeError as e:
            return False, f"JSON 格式错误: {e}"
        except ValidationError as e:
            return False, f"配置验证失败:\n{e}"

    @staticmethod
    def _find_config() -> Optional[Path]:
        """自动查找配置文件。"""
        for path in ConfigLoader.DEFAULT_PATHS:
            if path.exists():
                return path
        return None
