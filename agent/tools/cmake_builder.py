"""CMake 构建系统支持 — 检测、配置、构建 CMake 项目。"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any
import re


@dataclass
class CMakeProject:
    """CMake 项目描述"""
    project_dir: Path
    has_cmakelists: bool
    build_dir: Optional[Path] = None
    toolchain_file: Optional[Path] = None

    def parse_project_info(self) -> Dict[str, Any]:
        """解析 CMakeLists.txt 获取项目信息。"""
        cmakelists = self.project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            return {}

        content = cmakelists.read_text(encoding="utf-8", errors="ignore")
        info: Dict[str, Any] = {
            "project_name": None,
            "languages": [],
            "targets": [],
            "variables": {},
        }

        project_match = re.search(
            r"project\s*\(\s*([\w.-]+)\s+([^)]*)\)",
            content,
            re.IGNORECASE,
        )
        if project_match:
            info["project_name"] = project_match.group(1)
            languages_str = project_match.group(2)
            for lang in ["C", "CXX", "ASM", "Fortran"]:
                if lang in languages_str:
                    info["languages"].append(lang)

        target_pattern = r"add_(executable|library)\s*\(\s*([\w.-]+)"
        for match in re.finditer(target_pattern, content, re.IGNORECASE):
            info["targets"].append({
                "name": match.group(2),
                "type": match.group(1),
            })

        set_pattern = r"set\s*\(\s*(\w+)\s+([^)]+)\)"
        for match in re.finditer(set_pattern, content):
            info["variables"][match.group(1)] = match.group(2).strip().strip('"')

        return info


def detect_cmake_project(project_dir: str) -> Optional[CMakeProject]:
    """检测目录是否为 CMake 项目。"""
    project_path = Path(project_dir)
    if not (project_path / "CMakeLists.txt").exists():
        return None

    build_dir = project_path / "build"
    if not build_dir.exists():
        build_dir = None

    toolchain_file = None
    for candidate in [
        project_path / "cmake" / "toolchain.cmake",
        project_path / "toolchain.cmake",
    ]:
        if candidate.exists():
            toolchain_file = candidate
            break

    return CMakeProject(
        project_dir=project_path,
        has_cmakelists=True,
        build_dir=build_dir,
        toolchain_file=toolchain_file,
    )


class CMakeBuilder:
    """CMake 构建器 — 生成 CMake 命令。"""

    def __init__(self, cmake_executable: str = "cmake"):
        self.cmake_executable = cmake_executable

    def generate_configure_command(
        self,
        source_dir: str,
        build_dir: str,
        build_type: str = "Release",
        toolchain_file: Optional[str] = None,
        definitions: Optional[Dict[str, str]] = None,
        generator: Optional[str] = None,
    ) -> str:
        """生成 CMake 配置命令。"""
        cmd_parts = [
            self.cmake_executable,
            f"-S {source_dir}",
            f"-B {build_dir}",
            f"-DCMAKE_BUILD_TYPE={build_type}",
        ]

        if toolchain_file:
            cmd_parts.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}")
        if generator:
            cmd_parts.append(f'-G "{generator}"')
        if definitions:
            for key, value in definitions.items():
                cmd_parts.append(f"-D{key}={value}")

        return " ".join(cmd_parts)

    def generate_build_command(
        self,
        build_dir: str,
        target: Optional[str] = None,
        parallel_jobs: Optional[int] = None,
        verbose: bool = False,
    ) -> str:
        """生成 CMake 构建命令。"""
        cmd_parts = [self.cmake_executable, "--build", build_dir]

        if target:
            cmd_parts.extend(["--target", target])
        if parallel_jobs:
            cmd_parts.extend(["--parallel", str(parallel_jobs)])
        if verbose:
            cmd_parts.append("--verbose")

        return " ".join(cmd_parts)

    def generate_clean_command(self, build_dir: str) -> str:
        """生成 CMake 清理命令。"""
        return f"{self.cmake_executable} --build {build_dir} --target clean"

    def generate_install_command(
        self,
        build_dir: str,
        install_prefix: Optional[str] = None,
    ) -> str:
        """生成 CMake 安装命令。"""
        cmd = f"{self.cmake_executable} --install {build_dir}"
        if install_prefix:
            cmd += f" --prefix {install_prefix}"
        return cmd

    def detect_toolchain(self, platform: str) -> Optional[str]:
        """检测平台对应的工具链文件。"""
        for path_str in [
            f"/usr/share/cmake/toolchains/{platform}.cmake",
            f"~/.local/share/cmake/toolchains/{platform}.cmake",
            f"cmake/{platform}-toolchain.cmake",
        ]:
            path = Path(path_str).expanduser()
            if path.exists():
                return str(path)
        return None


def register_cmake_tool():
    """注册 CMake 构建工具到工具注册表"""
    from agent.tools import ToolRegistry

    registry = ToolRegistry()

    def cmake_build(project_dir: str, build_type: str = "Release", **kwargs):
        """CMake 构建工具函数"""
        project = detect_cmake_project(project_dir)
        if not project:
            return {"success": False, "error": "未找到 CMakeLists.txt"}

        builder = CMakeBuilder()
        build_dir = str(project.project_dir / "build")
        configure_cmd = builder.generate_configure_command(
            source_dir=str(project.project_dir),
            build_dir=build_dir,
            build_type=build_type,
            toolchain_file=str(project.toolchain_file) if project.toolchain_file else None,
        )
        build_cmd = builder.generate_build_command(build_dir=build_dir)

        return {
            "success": True,
            "configure_command": configure_cmd,
            "build_command": build_cmd,
            "full_command": f"{configure_cmd} && {build_cmd}",
        }

    registry.register(
        name="cmake_build",
        func=cmake_build,
        description="使用 CMake 构建嵌入式项目",
        parameters={
            "project_dir": {"type": "string", "description": "项目目录路径"},
            "build_type": {"type": "string", "description": "构建类型（Release/Debug）", "default": "Release"},
        },
    )
