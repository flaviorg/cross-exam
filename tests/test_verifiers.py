import asyncio
import http.server
import socketserver
import threading

import pytest

from cross_exam import fixture
from cross_exam.models import Check
from cross_exam.verifiers import Sandbox


@pytest.fixture
def box(demo_files):
    with Sandbox(demo_files["repo"], diff=fixture.diff(), timeout=20.0) as sandbox:
        yield sandbox


def run(box, tool, target="", expect=""):
    return asyncio.run(box.run(Check(tool=tool, target=target, expect=expect)))


def test_sandbox_is_a_copy_without_git(demo_files):
    (demo_files["repo"] / ".git").mkdir()
    with Sandbox(demo_files["repo"]) as sandbox:
        assert (sandbox.root / "slugkit" / "slug.py").exists()
        assert not (sandbox.root / ".git").exists()
        root = sandbox.root
    assert not root.exists()


def test_env_is_scrubbed(box, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-not-a-key")
    monkeypatch.setenv("GITHUB_TOKEN", "placeholder")
    env = box.env()
    assert "ANTHROPIC_API_KEY" not in env and "GITHUB_TOKEN" not in env
    assert env["CROSS_EXAM"] == "1"


@pytest.mark.parametrize(
    ("target", "expect", "verdict"),
    [
        ("tests/test_slug.py::test_slugify_lowercases_and_hyphenates", "pass", "VERIFIED"),
        ("", "pass", "CONTRADICTED"),
        ("tests/test_slug.py::test_truncate_keeps_whole_words", "fail", "VERIFIED"),
        ("tests/test_slug.py::test_truncate_keeps_whole_words", "pass", "CONTRADICTED"),
        ("tests/test_slug.py::test_does_not_exist", "pass", "UNVERIFIABLE"),
        ("tests/test_missing.py", "pass", "UNVERIFIABLE"),
        ("../outside.py", "pass", "UNVERIFIABLE"),
        ("--collect-only", "pass", "UNVERIFIABLE"),
        ("", "green", "UNVERIFIABLE"),
    ],
)
def test_run_test(box, target, expect, verdict):
    out = run(box, "run_test", target, expect)
    assert out.verdict == verdict, out.evidence


def test_run_test_summary_reads_pytest(box):
    out = run(box, "run_test", "", "pass")
    assert out.evidence.summary.endswith("1 failed, 3 passed")
    assert out.evidence.exit_code == 1


@pytest.mark.parametrize(
    ("pattern", "expect", "verdict"),
    [
        (r"def slugify", "present", "VERIFIED"),
        (r"README", "present", "CONTRADICTED"),
        (r"README", "absent", "VERIFIED"),
        (r"rsplit", "present", "CONTRADICTED"),  # removed lines do not count
        (r"([", "present", "UNVERIFIABLE"),
        ("", "present", "UNVERIFIABLE"),
        ("x", "maybe", "UNVERIFIABLE"),
    ],
)
def test_grep_diff(box, pattern, expect, verdict):
    assert run(box, "grep_diff", pattern, expect).verdict == verdict


def test_grep_diff_without_a_diff(demo_files):
    with Sandbox(demo_files["repo"]) as sandbox:
        assert asyncio.run(sandbox.run(Check(tool="grep_diff", target="x"))).verdict == "UNVERIFIABLE"


@pytest.mark.parametrize(
    ("path", "expect", "verdict"),
    [
        ("slugkit/slug.py", "present", "VERIFIED"),
        ("CHANGELOG.md", "present", "CONTRADICTED"),
        ("CHANGELOG.md", "absent", "VERIFIED"),
        ("../../etc/passwd", "present", "UNVERIFIABLE"),
        ("/etc/passwd", "present", "UNVERIFIABLE"),
    ],
)
def test_file_exists(box, path, expect, verdict):
    assert run(box, "file_exists", path, expect).verdict == verdict


@pytest.mark.parametrize(
    ("command", "expect", "verdict"),
    [
        ("ls slugkit", "pass", "VERIFIED"),
        ("ls no-such-dir", "pass", "CONTRADICTED"),
        ("ls no-such-dir", "fail", "VERIFIED"),
        ("python -c 'print(1)'", "pass", "UNVERIFIABLE"),  # not on the allowlist
        ("/bin/ls", "pass", "UNVERIFIABLE"),  # paths are never allowed
        ("rm -rf .", "pass", "UNVERIFIABLE"),
        ("ls 'unterminated", "pass", "UNVERIFIABLE"),
        ("", "pass", "UNVERIFIABLE"),
    ],
)
def test_run_command(box, command, expect, verdict):
    assert run(box, "run_command", command, expect).verdict == verdict


def test_run_command_times_out(demo_files):
    with Sandbox(demo_files["repo"], allowlist=("sleep",), timeout=0.3) as sandbox:
        out = asyncio.run(sandbox.run(Check(tool="run_command", target="sleep 5", expect="pass")))
    assert out.verdict == "UNVERIFIABLE"
    assert "timed out" in out.evidence.summary


def test_run_command_missing_program(demo_files):
    with Sandbox(demo_files["repo"], allowlist=("definitely-not-installed-xyz",)) as sandbox:
        out = asyncio.run(sandbox.run(Check(tool="run_command", target="definitely-not-installed-xyz")))
    assert out.verdict == "UNVERIFIABLE"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class QuickServer(http.server.HTTPServer):
    def server_bind(self):  # skip HTTPServer's reverse-DNS lookup (slow on some machines)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


@pytest.fixture
def server():
    httpd = QuickServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_http_check(box, server):
    assert run(box, "http_check", f"{server}/health", "200").verdict == "VERIFIED"
    assert run(box, "http_check", f"{server}/nope", "200").verdict == "CONTRADICTED"
    assert run(box, "http_check", f"{server}/nope", "404").verdict == "VERIFIED"
    assert run(box, "http_check", f"{server}/health", "ok").verdict == "UNVERIFIABLE"


def test_http_check_only_localhost(box):
    for url in ("https://example.com/", "http://169.254.169.254/", "file:///etc/passwd", "http://localhost.evil.test/"):
        assert run(box, "http_check", url, "200").verdict == "UNVERIFIABLE", url


def test_http_check_nothing_listening(box):
    out = run(box, "http_check", "http://127.0.0.1:9/", "200")
    assert out.verdict == "UNVERIFIABLE"


def test_none_is_unverifiable(box):
    out = asyncio.run(box.run(Check(tool="none", reason="manual testing")))
    assert out.verdict == "UNVERIFIABLE"
    assert "manual testing" in out.evidence.summary


def test_missing_interpreter_is_unverifiable(demo_files):
    with Sandbox(demo_files["repo"], python="/no/such/python") as sandbox:
        out = asyncio.run(sandbox.run(Check(tool="run_test", target="", expect="pass")))
    assert out.verdict == "UNVERIFIABLE"
    assert "could not run" in out.evidence.summary
