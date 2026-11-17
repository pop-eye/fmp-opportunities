"""Unit tests for Stage 4: logging, weekly summary, git publish, and SMTP alerts."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.ops import (
    has_failures,
    publish_docs,
    send_failure_email,
    setup_logging,
    write_weekly_summary,
)
from fmp_opportunities.core.pipeline import PipelineResult


def test_setup_logging_creates_rotating_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_file = setup_logging(log_dir=log_dir, verbose=True)
    logging.getLogger("test_stage4").info("Hello rotating log")
    assert log_file.exists()
    assert "Hello rotating log" in log_file.read_text(encoding="utf-8")


def test_write_weekly_summary_includes_counts_and_failures(tmp_path: Path) -> None:
    results = [
        PipelineResult(
            tool="jobs",
            listings=[Listing(title="Role A", organisation="Org A", location="Manchester")],
            added_count=1,
            removed_count=0,
        ),
        PipelineResult(
            tool="events",
            listings=[],
            failed_sources=["Broken Source"],
            kept_previous_due_to_drop=True,
        ),
    ]
    summary_path = tmp_path / "weekly_summary.txt"
    fixed_time = datetime(2026, 11, 17, 19, 0, tzinfo=timezone.utc)
    write_weekly_summary(results, summary_path=summary_path, run_time=fixed_time)

    text = summary_path.read_text(encoding="utf-8")
    assert "jobs: 1 total, 1 added, 0 removed" in text
    assert "FAILED SOURCES: Broken Source" in text
    assert "WARNING: suspicious drop detected for events" in text
    assert has_failures(results) is True


def test_publish_docs_skips_when_clean_and_pushes_when_changed(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run_clean(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run_clean)
    assert publish_docs(docs_dir="docs", repo_dir=tmp_path) is False
    assert len(calls) == 1

    calls.clear()

    def fake_run_dirty(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=" M docs/jobs.xml\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run_dirty)
    assert publish_docs(docs_dir="docs", repo_dir=tmp_path) is True
    assert [c[:2] for c in calls] == [
        ["git", "status"],
        ["git", "add"],
        ["git", "commit"],
        ["git", "push"],
    ]


def test_send_failure_email(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_TO", raising=False)
    assert send_failure_email("Subject", "Body") is False

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_TO", "lecturer@example.com")

    mock_client = MagicMock()
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_client
    monkeypatch.setattr("smtplib.SMTP", mock_smtp_cls)

    assert send_failure_email("Alert", "Details") is True
    mock_client.starttls.assert_called_once()
    mock_client.login.assert_called_once_with("bot@example.com", "secret")
    mock_client.send_message.assert_called_once()
