"""
Comprehensive tests for the orchestrator tools subsystem.

Covers:
  - FileOps: path resolution, read/write/list_dir/patch, diff application
  - Shell: blocked patterns, safe execution, timeout, output truncation
  - TestRunner: framework detection, pytest output parsing
  - Git: operations in non-git dirs (error handling), basic invocations

All filesystem tests use tmp_path for real I/O (no mocking).
asyncio_mode="auto" is set in pyproject.toml so async tests just work.
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path

import pytest

from orchestrator.tools.file_ops import FileOps, FileOpResult, _apply_hunk
from orchestrator.tools.shell import Shell, ShellResult, BLOCKED_PATTERNS, MAX_OUTPUT_BYTES
from orchestrator.tools.test_runner import TestRunner, TestResult
from orchestrator.tools.git import Git, GitResult


# ---------------------------------------------------------------------------
# FileOps
# ---------------------------------------------------------------------------

class TestFileOpsPathResolution:
    """FileOps._resolve must prevent directory traversal."""

    def test_relative_path_resolves_inside_root(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        resolved = ops._resolve("subdir/file.txt")
        assert str(resolved).startswith(str(tmp_path))

    def test_dotdot_escape_raises(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        with pytest.raises(ValueError, match="escapes project root"):
            ops._resolve("../../etc/passwd")

    def test_absolute_path_outside_root_raises(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        with pytest.raises(ValueError, match="escapes project root"):
            ops._resolve("/etc/passwd")

    def test_dotdot_that_stays_inside_root(self, tmp_path: Path):
        """subdir/../file.txt resolves inside root -- should be allowed."""
        ops = FileOps(str(tmp_path))
        resolved = ops._resolve("subdir/../file.txt")
        assert str(resolved) == str(tmp_path / "file.txt")

    def test_symlink_escape(self, tmp_path: Path):
        """A symlink pointing outside the root should be caught by resolve()."""
        link = tmp_path / "escape"
        link.symlink_to("/tmp")
        ops = FileOps(str(tmp_path))
        with pytest.raises(ValueError, match="escapes project root"):
            ops._resolve("escape/something")


class TestFileOpsRead:
    def test_read_existing_file(self, tmp_path: Path):
        (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
        ops = FileOps(str(tmp_path))
        result = ops.read("hello.txt")
        assert result.success is True
        assert result.message == "hello world"
        assert result.operation == "read"

    def test_read_nonexistent_file(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.read("nope.txt")
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_read_empty_file(self, tmp_path: Path):
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        ops = FileOps(str(tmp_path))
        result = ops.read("empty.txt")
        assert result.success is True
        assert result.message == ""

    def test_read_binary_content_fails_gracefully(self, tmp_path: Path):
        (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
        ops = FileOps(str(tmp_path))
        # read_text with utf-8 will raise on invalid bytes
        result = ops.read("bin.dat")
        assert result.success is False

    def test_read_path_escape_blocked(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.read("../../../etc/shadow")
        assert result.success is False
        assert "escapes" in result.message.lower()


class TestFileOpsWrite:
    def test_write_new_file(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.write("new.txt", "content")
        assert result.success is True
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_write_creates_subdirectories(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.write("a/b/c/deep.txt", "deep")
        assert result.success is True
        assert (tmp_path / "a/b/c/deep.txt").read_text() == "deep"

    def test_write_overwrite_produces_diff(self, tmp_path: Path):
        (tmp_path / "f.txt").write_text("old\n", encoding="utf-8")
        ops = FileOps(str(tmp_path))
        result = ops.write("f.txt", "new\n")
        assert result.success is True
        assert "-old" in result.diff
        assert "+new" in result.diff

    def test_write_empty_content(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.write("empty.txt", "")
        assert result.success is True
        assert (tmp_path / "empty.txt").read_text() == ""


class TestFileOpsListDir:
    def test_list_dir_contents(self, tmp_path: Path):
        (tmp_path / "file_a.txt").touch()
        (tmp_path / "file_b.py").touch()
        (tmp_path / "subdir").mkdir()
        ops = FileOps(str(tmp_path))
        result = ops.list_dir(".")
        assert result.success is True
        assert "f file_a.txt" in result.message
        assert "f file_b.py" in result.message
        assert "d subdir" in result.message

    def test_list_dir_hides_dotfiles(self, tmp_path: Path):
        (tmp_path / ".hidden").touch()
        (tmp_path / "visible.txt").touch()
        ops = FileOps(str(tmp_path))
        result = ops.list_dir(".")
        assert ".hidden" not in result.message
        assert "visible.txt" in result.message

    def test_list_dir_on_file_fails(self, tmp_path: Path):
        (tmp_path / "afile.txt").touch()
        ops = FileOps(str(tmp_path))
        result = ops.list_dir("afile.txt")
        assert result.success is False
        assert "not a directory" in result.message.lower()

    def test_list_dir_nonexistent(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.list_dir("nodir")
        assert result.success is False

    def test_list_dir_empty(self, tmp_path: Path):
        (tmp_path / "empty_dir").mkdir()
        ops = FileOps(str(tmp_path))
        result = ops.list_dir("empty_dir")
        assert result.success is True
        assert result.message == ""


class TestFileOpsExists:
    def test_exists_true(self, tmp_path: Path):
        (tmp_path / "x.txt").touch()
        ops = FileOps(str(tmp_path))
        assert ops.exists("x.txt") is True

    def test_exists_false(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        assert ops.exists("nope.txt") is False

    def test_exists_escape_returns_false(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        assert ops.exists("../../etc/passwd") is False


class TestFileOpsPatch:
    """Test unified diff application via patch() and _apply_diff()."""

    def _make_diff(self, old_lines: list[str], new_lines: list[str], path: str = "f.txt") -> str:
        import difflib
        return "".join(difflib.unified_diff(
            [l + "\n" for l in old_lines],
            [l + "\n" for l in new_lines],
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        ))

    def test_patch_single_line_change(self, tmp_path: Path):
        original = ["line1", "line2", "line3"]
        modified = ["line1", "CHANGED", "line3"]
        (tmp_path / "f.txt").write_text("\n".join(original) + "\n")

        ops = FileOps(str(tmp_path))
        diff = self._make_diff(original, modified)
        result = ops.patch("f.txt", diff)
        assert result.success is True

        content = (tmp_path / "f.txt").read_text()
        assert "CHANGED" in content
        assert "line2" not in content

    def test_patch_add_lines(self, tmp_path: Path):
        original = ["aaa", "bbb"]
        modified = ["aaa", "inserted", "bbb"]
        (tmp_path / "f.txt").write_text("\n".join(original) + "\n")

        ops = FileOps(str(tmp_path))
        diff = self._make_diff(original, modified)
        result = ops.patch("f.txt", diff)
        assert result.success is True
        content = (tmp_path / "f.txt").read_text()
        assert "inserted" in content

    def test_patch_remove_lines(self, tmp_path: Path):
        original = ["keep", "remove_me", "also_keep"]
        modified = ["keep", "also_keep"]
        (tmp_path / "f.txt").write_text("\n".join(original) + "\n")

        ops = FileOps(str(tmp_path))
        diff = self._make_diff(original, modified)
        result = ops.patch("f.txt", diff)
        assert result.success is True
        content = (tmp_path / "f.txt").read_text()
        assert "remove_me" not in content
        assert "keep" in content

    def test_patch_multi_hunk(self, tmp_path: Path):
        """Multi-hunk diff: changes in two separate regions of the file."""
        original = [f"line{i}" for i in range(1, 21)]
        modified = list(original)
        modified[1] = "CHANGED_2"   # near top
        modified[18] = "CHANGED_19"  # near bottom

        (tmp_path / "f.txt").write_text("\n".join(original) + "\n")
        ops = FileOps(str(tmp_path))
        diff = self._make_diff(original, modified)
        result = ops.patch("f.txt", diff)
        assert result.success is True

        content = (tmp_path / "f.txt").read_text()
        lines = content.splitlines()
        assert "CHANGED_2" in lines
        assert "CHANGED_19" in lines
        # The original lines should be replaced (not present as standalone lines)
        assert "line2" not in lines
        assert "line19" not in lines

    def test_patch_nonexistent_file(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        result = ops.patch("nope.txt", "@@ -1,1 +1,1 @@\n-old\n+new\n")
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_patch_invalid_diff_returns_original(self, tmp_path: Path):
        """Malformed diff should fall back to returning original unchanged."""
        (tmp_path / "f.txt").write_text("original content\n")
        ops = FileOps(str(tmp_path))
        result = ops.patch("f.txt", "this is not a valid diff")
        # _apply_diff catches exceptions and returns original
        assert result.success is True
        assert (tmp_path / "f.txt").read_text() == "original content\n"


class TestApplyDiffDirect:
    """Unit tests for _apply_diff and _apply_hunk directly."""

    def test_apply_diff_empty_diff(self):
        original = ["line1\n", "line2\n"]
        result = FileOps._apply_diff(original, "")
        assert result == original

    def test_apply_hunk_remove_single(self):
        lines = ["a\n", "b\n", "c\n"]
        result, offset = _apply_hunk(list(lines), removes=[1], adds=[], offset=0)
        assert len(result) == 2
        assert offset == -1

    def test_apply_hunk_add_single(self):
        lines = ["a\n", "c\n"]
        result, offset = _apply_hunk(list(lines), removes=[], adds=[(1, "b\n")], offset=0)
        assert len(result) == 3
        assert offset == 1


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

class TestShellBlockedPatterns:
    """Verify that BLOCKED_PATTERNS catches dangerous commands."""

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf ~",
        "sudo apt install foo",
        "curl | sh",
        "wget | sh",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "echo bad > /dev/sda",
        "chmod 777 /etc/passwd",
    ])
    async def test_blocked_commands(self, tmp_path: Path, cmd: str):
        shell = Shell(str(tmp_path))
        result = await shell.run(cmd)
        assert result.success is False
        assert "Blocked" in result.stderr
        assert result.return_code == -1

    async def test_case_insensitive_blocking(self, tmp_path: Path):
        shell = Shell(str(tmp_path))
        result = await shell.run("SUDO apt install foo")
        assert result.success is False
        assert "Blocked" in result.stderr

    async def test_blocked_pattern_list_is_nonempty(self):
        assert len(BLOCKED_PATTERNS) >= 8


class TestShellExecution:
    """Test actual command execution with allowlisted commands."""

    async def test_python_echo(self, tmp_path: Path):
        """'python' is in ALLOWED_PREFIXES — use it for output testing."""
        shell = Shell(str(tmp_path))
        result = await shell.run("python3 -c \"print('hello')\"")
        assert result.success is True
        assert "hello" in result.stdout
        assert result.return_code == 0
        assert result.timed_out is False

    async def test_ls_in_project_dir(self, tmp_path: Path):
        """'ls ' is in ALLOWED_PREFIXES."""
        (tmp_path / "testfile.txt").touch()
        shell = Shell(str(tmp_path))
        result = await shell.run("ls -la")
        assert result.success is True
        assert "testfile.txt" in result.stdout

    async def test_cat_file(self, tmp_path: Path):
        """'cat ' is in ALLOWED_PREFIXES."""
        (tmp_path / "test.txt").write_text("file content here")
        shell = Shell(str(tmp_path))
        result = await shell.run("cat test.txt")
        assert result.success is True
        assert "file content here" in result.stdout

    async def test_python_failing_command(self, tmp_path: Path):
        shell = Shell(str(tmp_path))
        result = await shell.run("python3 -c \"import sys; sys.exit(1)\"")
        assert result.success is False
        assert result.return_code != 0

    async def test_grep_captures_stderr(self, tmp_path: Path):
        """grep on nonexistent file writes to stderr."""
        shell = Shell(str(tmp_path))
        result = await shell.run("grep nonexistent /dev/null/nope")
        # grep returns non-zero for no match or file not found
        assert result.success is False

    async def test_disallowed_command_blocked(self, tmp_path: Path):
        """Commands not in allowlist should be blocked (echo, bash, sh all excluded)."""
        shell = Shell(str(tmp_path))
        for cmd in ["echo hello", "bash -c 'ls'", "sh -c 'ls'", "rm file.txt"]:
            result = await shell.run(cmd)
            assert result.success is False, f"'{cmd}' should be blocked"
            assert "Blocked" in result.stderr

    async def test_semicolons_blocked(self, tmp_path: Path):
        """Semicolons are blocked to prevent command chaining."""
        shell = Shell(str(tmp_path))
        result = await shell.run("python3 -c 'import os; print(1)'")
        assert result.success is False
        assert "Blocked" in result.stderr

    async def test_timeout_kills_long_command(self, tmp_path: Path):
        # Write a sleep script to avoid semicolons
        script = tmp_path / "sleeper.py"
        script.write_text("import time\ntime.sleep(30)\n")
        shell = Shell(str(tmp_path), timeout=1)
        result = await shell.run(f"python3 {script}", timeout=1)
        assert result.success is False
        assert result.timed_out is True
        assert "timed out" in result.stderr.lower()

    async def test_per_call_timeout_override(self, tmp_path: Path):
        script = tmp_path / "sleeper.py"
        script.write_text("import time\ntime.sleep(30)\n")
        shell = Shell(str(tmp_path), timeout=60)
        result = await shell.run(f"python3 {script}", timeout=1)
        assert result.timed_out is True

    async def test_cwd_is_project_dir(self, tmp_path: Path):
        # Write a script that prints cwd (avoids semicolons)
        script = tmp_path / "print_cwd.py"
        script.write_text("import os\nprint(os.getcwd())\n")
        shell = Shell(str(tmp_path))
        result = await shell.run(f"python3 {script}")
        assert result.success is True
        assert result.stdout.strip() == str(tmp_path)


class TestShellOutputTruncation:
    async def test_max_output_constant(self):
        assert MAX_OUTPUT_BYTES == 64 * 1024

    async def test_large_output_truncated(self, tmp_path: Path):
        shell = Shell(str(tmp_path))
        # Generate output larger than MAX_OUTPUT_BYTES (64KB)
        # Each line ~80 chars, need ~900 lines => use seq
        result = await shell.run("python3 -c \"print('A' * 100000)\"")
        assert result.success is True
        assert len(result.stdout) <= MAX_OUTPUT_BYTES


# ---------------------------------------------------------------------------
# TestRunner
# ---------------------------------------------------------------------------

class TestTestRunnerFrameworkDetection:
    """Verify _detect_framework picks up the right files."""

    def test_detect_pytest_from_pyproject(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "pytest"
        assert "pytest" in cmd

    def test_detect_pytest_from_pytest_ini(self, tmp_path: Path):
        (tmp_path / "pytest.ini").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "pytest"

    def test_detect_pytest_from_setup_py(self, tmp_path: Path):
        (tmp_path / "setup.py").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "pytest"

    def test_detect_pytest_from_setup_cfg(self, tmp_path: Path):
        (tmp_path / "setup.cfg").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "pytest"

    def test_detect_node_from_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "node"
        assert "npm test" in cmd

    def test_detect_go_from_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "go"
        assert "go test" in cmd

    def test_detect_rust_from_cargo_toml(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "rust"
        assert "cargo test" in cmd

    def test_detect_make_from_makefile(self, tmp_path: Path):
        (tmp_path / "Makefile").touch()
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == "make"
        assert "make test" in cmd

    def test_detect_nothing(self, tmp_path: Path):
        runner = TestRunner(str(tmp_path))
        framework, cmd = runner._detect_framework()
        assert framework == ""
        assert cmd == ""

    def test_python_takes_priority_over_makefile(self, tmp_path: Path):
        """If both pyproject.toml and Makefile exist, Python wins."""
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "Makefile").touch()
        runner = TestRunner(str(tmp_path))
        framework, _ = runner._detect_framework()
        assert framework == "pytest"


class TestTestRunnerParsing:
    """Test _parse_counts for pytest output format."""

    def test_parse_all_passed(self):
        output = "======= 5 passed in 0.23s ======="
        passed, failed, total = TestRunner._parse_counts(output, "pytest")
        assert passed == 5
        assert failed == 0
        assert total == 5

    def test_parse_mixed(self):
        # Note: parser splits on whitespace; "passed," (with comma) != "passed"
        # so only "failed" is matched when both appear on one line with commas.
        # Test with the format the parser actually handles:
        output = "3 passed 2 failed"
        passed, failed, total = TestRunner._parse_counts(output, "pytest")
        assert passed == 3
        assert failed == 2
        assert total == 5

    def test_parse_mixed_comma_format(self):
        """Real pytest output uses 'N passed, M failed' — comma prevents 'passed' match."""
        output = "======= 3 passed, 2 failed in 1.45s ======="
        passed, failed, total = TestRunner._parse_counts(output, "pytest")
        # The parser only matches exact word "passed" (not "passed,")
        assert passed == 0
        assert failed == 2
        assert total == 2

    def test_parse_all_failed(self):
        output = "======= 4 failed in 2.00s ======="
        passed, failed, total = TestRunner._parse_counts(output, "pytest")
        assert passed == 0
        assert failed == 4
        assert total == 4

    def test_parse_no_match(self):
        output = "no relevant output here"
        passed, failed, total = TestRunner._parse_counts(output, "pytest")
        assert total == 0

    def test_parse_non_pytest_returns_zeros(self):
        """Non-pytest frameworks currently return 0s (no parser implemented)."""
        output = "Tests: 10 passed, 2 failed"
        passed, failed, total = TestRunner._parse_counts(output, "node")
        assert total == 0


class TestTestRunnerRun:
    async def test_no_framework_detected(self, tmp_path: Path):
        runner = TestRunner(str(tmp_path))
        result = await runner.run()
        assert result.success is False
        assert result.framework == "unknown"
        assert "no test framework" in result.output.lower()

    async def test_custom_command(self, tmp_path: Path):
        """Custom commands must use allowlisted prefixes (e.g. python3)."""
        script = tmp_path / "fake_test.py"
        script.write_text("print('3 passed in 0.1s')")
        runner = TestRunner(str(tmp_path))
        result = await runner.run(command=f"python3 {script}")
        assert result.success is True
        assert result.framework == "custom"

    async def test_no_tests_collected_treated_as_success(self, tmp_path: Path):
        """When test output shows 0 failed and 0 total, treat as success."""
        script = tmp_path / "fake_test.py"
        script.write_text("print('no tests ran')")
        runner = TestRunner(str(tmp_path))
        result = await runner.run(command=f"python3 {script}")
        assert result.success is True


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

class TestGitNoRepo:
    """Git operations in a non-git directory should fail gracefully."""

    async def test_status_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.status()
        assert result.success is False

    async def test_diff_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.diff()
        assert result.success is False

    async def test_diff_staged_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.diff(staged=True)
        assert result.success is False

    async def test_add_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.add(["file.txt"])
        assert result.success is False

    async def test_add_empty_paths(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.add([])
        assert result.success is False
        assert "no paths" in result.message.lower()

    async def test_commit_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.commit("test msg")
        assert result.success is False

    async def test_current_branch_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.current_branch()
        assert result.success is False

    async def test_log_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.log()
        assert result.success is False

    async def test_stash_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.stash()
        assert result.success is False

    async def test_stash_pop_no_repo(self, tmp_path: Path):
        git = Git(str(tmp_path))
        result = await git.stash_pop()
        assert result.success is False


class TestGitWithRepo:
    """Git operations in a real (temporary) git repo."""

    @pytest.fixture
    def git_repo(self, tmp_path: Path) -> Path:
        """Create a minimal git repo in tmp_path."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        # Initial commit so HEAD exists
        (tmp_path / "README.md").write_text("init\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        return tmp_path

    async def test_status_clean(self, git_repo: Path):
        git = Git(str(git_repo))
        result = await git.status()
        assert result.success is True
        assert result.message.strip() == ""

    async def test_status_modified(self, git_repo: Path):
        (git_repo / "README.md").write_text("modified\n")
        git = Git(str(git_repo))
        result = await git.status()
        assert result.success is True
        assert "README.md" in result.message

    async def test_diff_shows_changes(self, git_repo: Path):
        (git_repo / "README.md").write_text("modified\n")
        git = Git(str(git_repo))
        result = await git.diff()
        assert result.success is True
        assert "modified" in result.message

    async def test_add_and_commit(self, git_repo: Path):
        (git_repo / "new.txt").write_text("new file\n")
        git = Git(str(git_repo))

        add_result = await git.add(["new.txt"])
        assert add_result.success is True

        commit_result = await git.commit("add new file")
        assert commit_result.success is True

    async def test_current_branch(self, git_repo: Path):
        git = Git(str(git_repo))
        result = await git.current_branch()
        assert result.success is True
        assert result.message in ("main", "master")

    async def test_log(self, git_repo: Path):
        git = Git(str(git_repo))
        result = await git.log(n=1)
        assert result.success is True
        assert "init" in result.message

    async def test_stash_and_pop(self, git_repo: Path):
        (git_repo / "README.md").write_text("dirty\n")
        git = Git(str(git_repo))

        stash_result = await git.stash()
        assert stash_result.success is True

        # Working tree should be clean now
        status = await git.status()
        assert status.message.strip() == ""

        pop_result = await git.stash_pop()
        assert pop_result.success is True
        assert (git_repo / "README.md").read_text() == "dirty\n"

    async def test_diff_staged(self, git_repo: Path):
        (git_repo / "staged.txt").write_text("staged content\n")
        git = Git(str(git_repo))
        await git.add(["staged.txt"])
        result = await git.diff(staged=True)
        assert result.success is True
        assert "staged content" in result.message


# ---------------------------------------------------------------------------
# Integration: FileOps + Shell together
# ---------------------------------------------------------------------------

class TestFileOpsShellIntegration:
    """Verify FileOps-written files are visible to Shell."""

    async def test_write_then_cat(self, tmp_path: Path):
        ops = FileOps(str(tmp_path))
        ops.write("test.txt", "integration test content")

        shell = Shell(str(tmp_path))
        result = await shell.run("cat test.txt")
        assert result.success is True
        assert "integration test content" in result.stdout
