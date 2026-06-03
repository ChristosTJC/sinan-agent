"""path_rules 路径校验测试."""

import tempfile
from pathlib import Path


class TestValidatePath:
    """validate_path() 单元测试."""

    def test_allows_normal_file_in_tmp(self):
        from agent.tools.path_rules import validate_path

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "normal.txt"
            fpath.write_text("hello")
            allowed, reason = validate_path(str(fpath), workspace=tmp, mode="read")
            assert allowed is True, reason

    def test_blocks_hardcoded_sensitive_path(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("/etc/passwd", mode="read")
        assert allowed is False, f"Should block /etc/passwd, got: {reason}"
        assert "敏感" in reason or "deny" in reason.lower() or "拒绝" in reason

    def test_blocks_ssh_key(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("/home/user/.ssh/id_rsa", mode="read")
        assert allowed is False, f"Should block SSH key, got: {reason}"

    def test_blocks_workspace_escape(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("/etc/hosts", workspace="/tmp", mode="read")
        assert allowed is False, f"Should block out-of-workspace access, got: {reason}"

    def test_allows_path_inside_workspace(self):
        from agent.tools.path_rules import validate_path

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "project" / "src" / "main.py"
            fpath.parent.mkdir(parents=True)
            fpath.write_text("code")
            allowed, reason = validate_path(str(fpath), workspace=tmp, mode="read")
            assert allowed is True, reason

    def test_nonexistent_path_still_checks_pattern(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("/etc/shadow", mode="read")
        assert allowed is False, f"Should block /etc/shadow even if nonexistent, got: {reason}"

    def test_blocks_soft_deny_env_file(self):
        from agent.tools.path_rules import validate_path

        # .env 在软阻止名单中
        allowed, reason = validate_path("/home/user/project/.env", mode="read")
        assert allowed is False, f"Should block .env (soft deny), got: {reason}"

    def test_allows_soft_deny_when_flag_set(self):
        from agent.tools.path_rules import validate_path

        # allow_soft=True 时放行
        allowed, reason = validate_path(
            "/home/user/project/.env", mode="read", allow_soft=True
        )
        assert allowed is True, reason

    def test_allows_normal_py_file(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("/home/user/project/main.py", mode="read")
        assert allowed is True, reason

    def test_rejects_relative_path(self):
        from agent.tools.path_rules import validate_path

        allowed, reason = validate_path("relative/path.txt", mode="read")
        assert allowed is False, "Should reject relative path"


class TestValidateSearchRoot:
    """validate_search_root() 测试."""

    def test_rejects_etc(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/etc")
        assert allowed is False, reason

    def test_rejects_proc(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/proc")
        assert allowed is False, reason

    def test_rejects_root(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/")
        assert allowed is False, reason

    def test_rejects_sys(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/sys")
        assert allowed is False, reason

    def test_rejects_var_log(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/var/log")
        assert allowed is False, reason

    def test_allows_tmp(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/tmp")
        assert allowed is True, reason

    def test_allows_home(self):
        from agent.tools.path_rules import validate_search_root

        allowed, reason = validate_search_root("/home/user/project")
        assert allowed is True, reason


class TestIsSensitive:
    """_is_sensitive() 内部函数测试."""

    def test_dot_env_is_sensitive(self):
        from agent.tools.path_rules import _is_sensitive

        assert _is_sensitive("/home/user/project/.env") is True

    def test_ssh_id_rsa_is_sensitive(self):
        from agent.tools.path_rules import _is_sensitive

        assert _is_sensitive("/root/.ssh/id_rsa") is True

    def test_normal_file_not_sensitive(self):
        from agent.tools.path_rules import _is_sensitive

        assert _is_sensitive("/home/user/project/main.py") is False

    def test_aws_credentials_is_sensitive(self):
        from agent.tools.path_rules import _is_sensitive

        assert _is_sensitive("/root/.aws/credentials") is True

    def test_kube_config_is_sensitive(self):
        from agent.tools.path_rules import _is_sensitive

        assert _is_sensitive("/root/.kube/config") is True
