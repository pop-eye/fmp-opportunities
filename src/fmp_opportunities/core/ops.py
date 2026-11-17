"""Operational helpers: rotating logging, weekly summary, git publish, and SMTP alerts."""

from __future__ import annotations

import logging
import os
import smtplib
import subprocess
from datetime import datetime, timezone
from email.message import EmailMessage
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from fmp_opportunities.core.pipeline import PipelineResult

logger = logging.getLogger(__name__)


def setup_logging(log_dir: str | Path = "logs", verbose: bool = False) -> Path:
    """Configure console logging and a rotating log file."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "fmp_opportunities.log"

    level = logging.DEBUG if verbose else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicating handlers if called more than once in tests
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    rotating = RotatingFileHandler(
        log_file,
        maxBytes=1_048_576,
        backupCount=5,
        encoding="utf-8",
    )
    rotating.setLevel(level)
    rotating.setFormatter(formatter)
    root_logger.addHandler(rotating)

    return log_file


def format_weekly_summary(
    results: list[PipelineResult],
    run_time: Optional[datetime] = None,
    unexpected_error: Optional[str] = None,
) -> str:
    """Build a concise plain text weekly summary report."""
    now = run_time or datetime.now(timezone.utc)
    lines = [
        f"FMP Opportunities Weekly Summary ({now.strftime('%Y-%m-%d %H:%M UTC')})",
        "",
    ]

    for res in results:
        lines.append(
            f"- {res.tool}: {len(res.listings)} total, "
            f"{res.added_count} added, {res.removed_count} removed"
        )
        if res.kept_previous_due_to_drop:
            lines.append(
                f"  WARNING: suspicious drop detected for {res.tool}; kept previous outputs."
            )
        if res.failed_sources:
            lines.append(
                f"  FAILED SOURCES: {', '.join(res.failed_sources)}"
            )

    if unexpected_error:
        lines.append("")
        lines.append(f"UNEXPECTED ERROR: {unexpected_error}")

    return "\n".join(lines) + "\n"


def write_weekly_summary(
    results: list[PipelineResult],
    summary_path: str | Path = "logs/weekly_summary.txt",
    run_time: Optional[datetime] = None,
    unexpected_error: Optional[str] = None,
) -> Path:
    """Write the weekly summary text file."""
    path = Path(summary_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = format_weekly_summary(
        results=results,
        run_time=run_time,
        unexpected_error=unexpected_error,
    )
    path.write_text(content, encoding="utf-8")
    return path


def publish_docs(docs_dir: str | Path = "docs", repo_dir: str | Path = ".") -> bool:
    """Commit and push docs/ to GitHub if there are changes. Returns True if pushed."""
    docs_str = str(docs_dir)
    cwd = str(repo_dir)

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", docs_str],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    if not status.stdout.strip():
        logger.info("No changes in %s; skipping git commit and push.", docs_str)
        return False

    subprocess.run(
        ["git", "add", "--", docs_str],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subprocess.run(
        ["git", "commit", "-m", f"Update FMP opportunities feeds ({date_label})"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "push"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info("Published updated %s to GitHub.", docs_str)
    return True


def has_failures(results: list[PipelineResult], unexpected_error: Optional[str] = None) -> bool:
    """Return True if any tool had failed sources, a suspicious drop, or an error."""
    if unexpected_error:
        return True
    return any(res.failed_sources or res.kept_previous_due_to_drop for res in results)


def send_failure_email(subject: str, body: str) -> bool:
    """Send an email notification using SMTP environment variables when configured."""
    host = os.environ.get("SMTP_HOST", "").strip()
    to_raw = os.environ.get("SMTP_TO", "").strip()
    if not host or not to_raw:
        logger.debug("SMTP_HOST or SMTP_TO not set; skipping failure email notification.")
        return False

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "").strip() or user or "fmp-opportunities@localhost"
    use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes")
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as client:
        if use_tls:
            client.starttls()
        if user and password:
            client.login(user, password)
        client.send_message(msg)

    logger.info("Sent failure notification email to %s", ", ".join(recipients))
    return True
