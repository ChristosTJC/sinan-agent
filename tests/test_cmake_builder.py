# tests/test_cmake_builder.py
import pytest
import tempfile
from pathlib import Path
from agent.tools.cmake_builder import CMakeBuilder, CMakeProject, detect_cmake_project

def test_detect_cmake_project():
    """测试 CMake 项目检测"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # 创建 CMakeLists.txt
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(test_project C)

add_executable(firmware main.c)
""")

        project = detect_cmake_project(str(project_dir))

        assert project is not None
        assert project.project_dir == project_dir
        assert project.has_cmakelists

def test_detect_non_cmake_project():
    """测试非 CMake 项目检测"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = detect_cmake_project(tmpdir)
        assert project is None

def test_cmake_builder_configure():
    """测试 CMake 配置命令生成"""
    builder = CMakeBuilder()

    cmd = builder.generate_configure_command(
        source_dir="/path/to/src",
        build_dir="/path/to/build",
        build_type="Release",
        toolchain_file="/path/to/toolchain.cmake"
    )

    assert "cmake" in cmd
    assert "-S /path/to/src" in cmd
    assert "-B /path/to/build" in cmd
    assert "-DCMAKE_BUILD_TYPE=Release" in cmd
    assert "-DCMAKE_TOOLCHAIN_FILE=/path/to/toolchain.cmake" in cmd

def test_cmake_builder_build():
    """测试 CMake 构建命令生成"""
    builder = CMakeBuilder()

    cmd = builder.generate_build_command(
        build_dir="/path/to/build",
        target="firmware",
        parallel_jobs=4
    )

    assert "cmake --build /path/to/build" in cmd
    assert "--target firmware" in cmd
    assert "-j 4" in cmd or "--parallel 4" in cmd

def test_cmake_builder_clean():
    """测试 CMake 清理命令生成"""
    builder = CMakeBuilder()

    cmd = builder.generate_clean_command(build_dir="/path/to/build")

    assert "cmake --build /path/to/build" in cmd
    assert "--target clean" in cmd

def test_cmake_project_parse():
    """测试 CMakeLists.txt 解析"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(my_firmware C CXX ASM)

set(MCU_FAMILY STM32F4)
set(MCU_MODEL STM32F405RGT6)

add_executable(firmware.elf
    src/main.c
    src/startup.s
)
""")

        project = detect_cmake_project(str(project_dir))
        info = project.parse_project_info()

        assert info["project_name"] == "my_firmware"
        assert "C" in info["languages"]
        assert "CXX" in info["languages"]

def test_cmake_builder_with_definitions():
    """测试带自定义定义的 CMake 配置"""
    builder = CMakeBuilder()

    cmd = builder.generate_configure_command(
        source_dir="/src",
        build_dir="/build",
        definitions={
            "BOARD": "nrf52840dk",
            "USE_BLE": "ON",
            "LOG_LEVEL": "DEBUG"
        }
    )

    assert "-DBOARD=nrf52840dk" in cmd
    assert "-DUSE_BLE=ON" in cmd
    assert "-DLOG_LEVEL=DEBUG" in cmd
