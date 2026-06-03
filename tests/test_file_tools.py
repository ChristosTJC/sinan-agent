"""文件工具测试 — read_file / write_file / edit_file / grep / glob。"""

import os
import tempfile
from pathlib import Path


# ─── read_file 测试 ───────────────────────────────────────────

def test_read_file_text():
    """读取文本文件。"""
    from agent.tools.file_read import read_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "test.txt"
        fpath.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = read_file(str(fpath))
        assert result["type"] == "text"
        assert "line1" in result["content"]
        assert result["total_lines"] == 5


def test_read_file_with_offset_limit():
    """带 offset/limit 读取。"""
    from agent.tools.file_read import read_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "test.txt"
        fpath.write_text("a\nb\nc\nd\ne\nf\n")

        result = read_file(str(fpath), offset=2, limit=2)
        assert result["content"].strip() == "b\nc"


def test_read_file_directory():
    """读取目录列表。"""
    from agent.tools.file_read import read_file

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.txt").write_text("a")
        (Path(tmp) / "subdir").mkdir()

        result = read_file(str(tmp))
        assert result["type"] == "directory"
        names = [e["name"] for e in result["entries"]]
        assert "a.txt" in names
        assert "subdir/" in names


def test_read_file_nonexistent():
    """读取不存在的文件。"""
    from agent.tools.file_read import read_file

    result = read_file("/tmp/nonexistent_file_xyz_12345.txt")
    assert result["type"] == "error"
    assert "不存在" in result["error"]


def test_read_file_relative_path_rejected():
    """相对路径被拒绝。"""
    from agent.tools.file_read import read_file

    result = read_file("relative/path.txt")
    assert result["type"] == "error"


def test_read_file_truncation():
    """大文件截断提示。"""
    from agent.tools.file_read import read_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "big.txt"
        fpath.write_text("\n".join(f"line{i}" for i in range(100)))

        result = read_file(str(fpath), limit=10)
        assert result["truncated"] is True


# ─── write_file 测试 ──────────────────────────────────────────

def test_write_file_create():
    """写入新文件。"""
    from agent.tools.file_write import write_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "new.txt"
        result = write_file(str(fpath), "hello world")
        assert result["success"] is True
        assert result["type"] == "create"
        assert fpath.read_text() == "hello world"


def test_write_file_overwrite():
    """覆盖已有文件。"""
    from agent.tools.file_write import write_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "existing.txt"
        fpath.write_text("old content")

        result = write_file(str(fpath), "new content")
        assert result["success"] is True
        assert result["type"] == "update"
        assert fpath.read_text() == "new content"


def test_write_file_relative_path_rejected():
    """相对路径写入被拒绝。"""
    from agent.tools.file_write import write_file

    result = write_file("relative/path.txt", "content")
    assert result["success"] is False
    assert "绝对路径" in result["error"]


# ─── edit_file 测试 ───────────────────────────────────────────

def test_edit_file_single_replace():
    """单处精确替换。"""
    from agent.tools.file_edit import edit_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "edit.txt"
        fpath.write_text("hello world")

        result = edit_file(str(fpath), "hello", "hi")
        assert result["success"] is True
        assert result["replacements"] == 1
        assert fpath.read_text() == "hi world"


def test_edit_file_replace_all():
    """全部替换。"""
    from agent.tools.file_edit import edit_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "edit.txt"
        fpath.write_text("foo bar foo baz foo")

        result = edit_file(str(fpath), "foo", "qux", replace_all=True)
        assert result["success"] is True
        assert result["replacements"] == 3
        assert fpath.read_text() == "qux bar qux baz qux"


def test_edit_file_multiple_matches_no_replace_all():
    """多处匹配未设置 replace_all 被拒绝。"""
    from agent.tools.file_edit import edit_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "edit.txt"
        fpath.write_text("foo bar foo")

        result = edit_file(str(fpath), "foo", "bar")
        assert result["success"] is False
        assert "出现了" in result["error"]


def test_edit_file_nonexistent():
    """编辑不存在的文件。"""
    from agent.tools.file_edit import edit_file

    result = edit_file("/tmp/nonexistent_xyz_999.txt", "a", "b")
    assert result["success"] is False
    assert "不存在" in result["error"]


def test_edit_file_not_found():
    """old_string 不匹配。"""
    from agent.tools.file_edit import edit_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "edit.txt"
        fpath.write_text("hello world")

        result = edit_file(str(fpath), "not_there", "replacement")
        assert result["success"] is False
        assert "未找到" in result["error"]


def test_edit_file_same_string():
    """old_string == new_string 拒绝。"""
    from agent.tools.file_edit import edit_file

    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "edit.txt"
        fpath.write_text("hello")

        result = edit_file(str(fpath), "hello", "hello")
        assert result["success"] is False
        assert "相同" in result["error"]


# ─── grep 测试 ────────────────────────────────────────────────

def test_grep_basic():
    """基本正则搜索。"""
    from agent.tools.file_search import grep

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("import os\nimport sys\nprint('hello')\n")
        (Path(tmp) / "b.py").write_text("import re\n")
        (Path(tmp) / "c.txt").write_text("no match here\n")

        result = grep("import", path=tmp, glob="*.py")
        assert result["ok"] is True
        assert len(result["files"]) >= 1


def test_grep_files_with_matches():
    """files_with_matches 模式。"""
    from agent.tools.file_search import grep

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("hello")
        (Path(tmp) / "b.py").write_text("world")
        (Path(tmp) / "c.txt").write_text("hello")

        result = grep("hello", path=tmp, output_mode="files_with_matches")
        assert result["ok"] is True
        assert len(result["files"]) == 2  # a.py + c.txt


def test_grep_count():
    """count 输出模式。"""
    from agent.tools.file_search import grep

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("hello\nhello\nworld\n")

        result = grep("hello", path=tmp, output_mode="count")
        assert result["ok"] is True
        counts = result.get("counts", {})
        # ripgrep 返回绝对路径，需用文件名匹配
        assert any(k.endswith("a.py") and v == 2 for k, v in counts.items())


def test_grep_invalid_regex():
    """无效正则表达式。"""
    from agent.tools.file_search import grep

    result = grep("[invalid", path="/tmp")
    assert result["ok"] is False


def test_grep_nonexistent_path():
    """搜索不存在的目录。"""
    from agent.tools.file_search import grep

    result = grep("pattern", path="/nonexistent_dir_xyz_999")
    assert result["ok"] is False


# ─── glob 测试 ────────────────────────────────────────────────

def test_glob_py_files():
    """glob 匹配 .py 文件。"""
    from agent.tools.file_search import glob as glob_search

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("a")
        (Path(tmp) / "b.py").write_text("b")
        (Path(tmp) / "c.txt").write_text("c")
        (Path(tmp) / "sub").mkdir()
        (Path(tmp) / "sub" / "d.py").write_text("d")

        result = glob_search("**/*.py", path=tmp)
        assert result["ok"] is True
        py_files = [f for f in result["filenames"] if f.endswith(".py")]
        assert len(py_files) == 3  # a.py, b.py, sub/d.py


def test_glob_nonexistent_path():
    """搜索不存在的目录。"""
    from agent.tools.file_search import glob as glob_search

    result = glob_search("*.py", path="/nonexistent_xyz_999")
    assert result["ok"] is False


# ─── ToolRegistry 集成测试 ────────────────────────────────────

def test_registry_has_file_tools():
    """ToolRegistry 注册了 5 个文件工具。"""
    from agent.tools import get_registry

    registry = get_registry()
    tools = registry.list_tools()
    names = {t["name"] for t in tools}

    assert "read_file" in names
    assert "write_file" in names
    assert "edit_file" in names
    assert "grep" in names
    assert "glob" in names


def test_registry_dangerous_flags():
    """write_file 和 edit_file 标记为危险。"""
    from agent.tools import get_registry

    registry = get_registry()
    assert registry.is_dangerous("write_file")
    assert registry.is_dangerous("edit_file")
    assert not registry.is_dangerous("read_file")
    assert not registry.is_dangerous("grep")
    assert not registry.is_dangerous("glob")


# ─── path_rules 安全集成测试 ──────────────────────────────────


class TestFileReadSecurity:
    """文件读取安全校验测试."""

    def test_rejects_etc_passwd(self):
        from agent.tools.file_read import read_file

        result = read_file("/etc/passwd")
        assert result["type"] == "error"

    def test_rejects_ssh_private_key(self):
        from agent.tools.file_read import read_file

        result = read_file("/root/.ssh/id_rsa")
        assert result["type"] == "error"

    def test_allows_normal_file(self):
        from agent.tools.file_read import read_file

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "ok.txt"
            fpath.write_text("safe content")
            result = read_file(str(fpath))
            assert result["type"] == "text"
            assert "safe content" in result["content"]

    def test_rejects_relative_path_unchanged(self):
        from agent.tools.file_read import read_file

        result = read_file("relative/path.txt")
        assert result["type"] == "error"


class TestFileWriteSecurity:
    """文件写入安全校验测试."""

    def test_rejects_write_to_ssh_dir(self):
        from agent.tools.file_write import write_file

        result = write_file("/root/.ssh/authorized_keys", "evil key")
        assert result["success"] is False

    def test_rejects_write_to_etc(self):
        from agent.tools.file_write import write_file

        result = write_file("/etc/cron.d/backdoor", "* * * * * root evil")
        assert result["success"] is False


class TestFileEditSecurity:
    """文件编辑安全校验测试."""

    def test_rejects_edit_sensitive_file(self):
        from agent.tools.file_edit import edit_file

        result = edit_file("/etc/sudoers", "OLD", "NEW")
        assert result["success"] is False


class TestFileSearchSecurity:
    """文件搜索安全校验测试."""

    def test_grep_rejects_etc(self):
        from agent.tools.file_search import grep

        result = grep(".*", path="/etc")
        assert result.get("ok") is False

    def test_grep_rejects_proc(self):
        from agent.tools.file_search import grep

        result = grep(".*", path="/proc")
        assert result.get("ok") is False

    def test_grep_allows_normal_dir(self):
        from agent.tools.file_search import grep

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("hello")
            result = grep("hello", path=tmp)
            assert result.get("ok") is True

    def test_glob_rejects_etc(self):
        from agent.tools.file_search import glob as glob_search

        result = glob_search("*.conf", path="/etc")
        assert result.get("ok") is False
