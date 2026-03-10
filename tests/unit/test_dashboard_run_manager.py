"""Tests for the dashboard run manager."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from agentos.dashboard.run_manager import RunManager


class TestRunManager:
    """Tests for RunManager."""

    def test_init(self):
        rm = RunManager()
        assert rm._runs == {}

    def test_list_active_empty(self):
        rm = RunManager()
        assert rm.list_active() == []

    @patch("agentos.dashboard.run_manager.subprocess.Popen")
    def test_start(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        rm = RunManager()
        run_id = rm.start("name: test\nversion: '1.0'")

        assert run_id.startswith("run-")
        assert len(run_id) == 12  # "run-" + 8 hex chars
        assert run_id in rm._runs
        mock_popen.assert_called_once()
        # Verify --workflow-id is passed to the subprocess
        cmd = mock_popen.call_args[0][0]
        assert "--workflow-id" in cmd
        assert run_id in cmd

    @patch("agentos.dashboard.run_manager.subprocess.Popen")
    def test_cancel(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        rm = RunManager()
        run_id = rm.start("name: test\nversion: '1.0'")

        assert rm.cancel(run_id) is True
        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_cancel_nonexistent(self):
        rm = RunManager()
        assert rm.cancel("no-such-run") is False

    @patch("agentos.dashboard.run_manager.subprocess.Popen")
    def test_list_active(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        rm = RunManager()
        run_id = rm.start("name: test\nversion: '1.0'")

        active = rm.list_active()
        assert len(active) == 1
        assert active[0]["run_id"] == run_id
        assert active[0]["pid"] == 42

    @patch("agentos.dashboard.run_manager.subprocess.Popen")
    def test_reap_finished(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 50
        mock_proc.poll.return_value = 0  # Finished
        mock_popen.return_value = mock_proc

        rm = RunManager()
        rm.start("name: test\nversion: '1.0'")

        # After reap, should be empty
        active = rm.list_active()
        assert len(active) == 0

    @patch("agentos.dashboard.run_manager.subprocess.Popen")
    def test_start_with_options(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 77
        mock_popen.return_value = mock_proc

        rm = RunManager()
        rm.start("name: test", live=True, interactive=True, db_path="/tmp/test.db")

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--live" in cmd
        assert "--interactive" in cmd
        assert "--db" in cmd
        assert "/tmp/test.db" in cmd
