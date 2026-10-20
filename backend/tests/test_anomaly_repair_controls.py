"""Focused guards: tolerate progress, reject extra starts, retain safe sockets."""
import errno
import sys
from pathlib import Path

import pytest

from demopilot import quotation_browser as browser

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sales_anomaly_runtime_cases import _cli_starts


def test_recovery_progress_is_not_an_automatic_cli_start():
    stopped = [dict(type="process.started", pid=11, mode="workspace-write")]
    advanced = stopped + [dict(type="thread.started"), dict(type="turn.started")]
    assert advanced != stopped  # Historical all-events comparison rejected this.
    assert _cli_starts(advanced) == _cli_starts(stopped)


@pytest.mark.parametrize("extra", [
    [dict(type="process.started", pid=12, mode="workspace-write")],
    [dict(type="process.started", pid=11, mode="workspace-write")],
])
def test_recovery_rejects_extra_start_even_with_same_pid(extra):
    stopped = [dict(type="process.started", pid=11, mode="workspace-write")]
    assert _cli_starts(stopped + extra) != _cli_starts(stopped)


def test_safe_port_conflict_is_retried_without_releasing_chosen_socket(tmp_path, monkeypatch):
    busy = browser.browser_http_server(tmp_path)
    second = browser.browser_http_server(tmp_path)
    busy_port, free_port = busy.server_port, second.server_port
    second.server_close()
    choices = iter((busy_port - 49152, free_port - 49152))
    monkeypatch.setattr(browser.secrets, "randbelow", lambda _limit: next(choices))
    chosen = None
    try:
        chosen = browser.browser_http_server(tmp_path)
        assert chosen.server_port == free_port
        assert 49152 <= chosen.server_port <= 65535
        assert chosen.socket.fileno() != -1
        with pytest.raises(OSError):
            browser.ThreadingHTTPServer(("127.0.0.1", free_port), browser.QuietHandler)
    finally:
        busy.server_close()
        if chosen:
            chosen.server_close()


def test_safe_port_selection_has_a_finite_failure_budget(tmp_path, monkeypatch):
    busy = browser.browser_http_server(tmp_path)
    attempts = []
    def occupied(_limit):
        attempts.append(True)
        return busy.server_port - 49152
    monkeypatch.setattr(browser.secrets, "randbelow", occupied)
    try:
        with pytest.raises(OSError, match="after32 bind attempts"):
            browser.browser_http_server(tmp_path)
        assert len(attempts) == 32
    finally:
        busy.server_close()


def test_unexpected_bind_failure_is_not_masked(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError(errno.EIO, "unexpected socket failure")
    monkeypatch.setattr(browser, "BrowserHTTPServer", broken)
    with pytest.raises(OSError, match="unexpected socket failure"):
        browser.browser_http_server(tmp_path)
