"""Command line entry point for FMP Opportunities."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from fmp_opportunities.core.config import load_keywords, load_sources
from fmp_opportunities.core.llm import DEFAULT_LLAMA_ENDPOINT, create_llama_cpp_hook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.ops import (
    has_failures,
    publish_docs,
    send_failure_email,
    setup_logging,
    write_weekly_summary,
)
from fmp_opportunities.core.pipeline import PipelineResult
from fmp_opportunities.core.writers import write_combined_rss
from fmp_opportunities.tools.events import run_events
from fmp_opportunities.tools.jobs import run_jobs
from fmp_opportunities.tools.placements import run_placements


def load_dotenv_if_present(dotenv_path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs from .env when not already set in the environment."""
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate FMP Opportunities feeds for MMU students."
    )
    parser.add_argument(
        "--tool",
        choices=["all", "jobs", "placements", "events"],
        default="all",
        help="Which tool to run (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and filter without writing docs/ or updating state.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip git commit and push after generating outputs.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("sources.yaml"),
        help="Path to sources.yaml.",
    )
    parser.add_argument(
        "--keywords",
        type=Path,
        default=Path("keywords.yaml"),
        help="Path to keywords.yaml.",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=Path("docs"),
        help="Directory for generated GitHub Pages outputs.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("state/state.json"),
        help="Path to persisted JSON state file.",
    )
    parser.add_argument(
        "--site-url",
        default="https://example.github.io/fmp-opportunities/",
        help="Base URL of the published GitHub Pages site for RSS links.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="Directory for rotating logs and weekly summary.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable optional local llama.cpp server classification hook.",
    )
    parser.add_argument(
        "--llm-url",
        default=DEFAULT_LLAMA_ENDPOINT,
        help="OpenAI compatible llama.cpp server chat completions URL.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_if_present()
    args = parse_args(argv)
    setup_logging(log_dir=args.log_dir, verbose=args.verbose)
    logger = logging.getLogger("fmp_opportunities.run")

    base_url = args.site_url.rstrip("/")
    llm_hook = create_llama_cpp_hook(endpoint=args.llm_url) if args.use_llm else None
    results_by_tool: dict[str, list[Listing]] = {}
    pipeline_results: list[PipelineResult] = []
    unexpected_error: str | None = None

    try:
        sources_by_tool = load_sources(args.sources)

        if args.tool in ("all", "jobs"):
            kw_jobs = load_keywords(args.keywords, tool="jobs")
            res = run_jobs(
                sources=sources_by_tool.get("jobs", []),
                keywords=kw_jobs,
                docs_dir=args.docs_dir,
                state_path=args.state_file,
                channel_link=f"{base_url}/jobs.html",
                llm_hook=llm_hook,
                dry_run=args.dry_run,
            )
            results_by_tool["jobs"] = res.listings
            pipeline_results.append(res)
            logger.info(
                "Jobs complete: %d listings (%d added, %d removed, %d failed sources)",
                len(res.listings),
                res.added_count,
                res.removed_count,
                len(res.failed_sources),
            )

        if args.tool in ("all", "placements"):
            kw_placements = load_keywords(args.keywords, tool="placements")
            res = run_placements(
                sources=sources_by_tool.get("placements", []),
                keywords=kw_placements,
                docs_dir=args.docs_dir,
                state_path=args.state_file,
                channel_link=f"{base_url}/placements.html",
                llm_hook=llm_hook,
                dry_run=args.dry_run,
            )
            results_by_tool["placements"] = res.listings
            pipeline_results.append(res)
            logger.info(
                "Placements complete: %d listings (%d added, %d removed, %d failed sources)",
                len(res.listings),
                res.added_count,
                res.removed_count,
                len(res.failed_sources),
            )

        if args.tool in ("all", "events"):
            kw_events = load_keywords(args.keywords, tool="events")
            res = run_events(
                sources=sources_by_tool.get("events", []),
                keywords=kw_events,
                docs_dir=args.docs_dir,
                state_path=args.state_file,
                channel_link=f"{base_url}/events.html",
                llm_hook=llm_hook,
                dry_run=args.dry_run,
            )
            results_by_tool["events"] = res.listings
            pipeline_results.append(res)
            logger.info(
                "Events complete: %d listings (%d added, %d removed, %d failed sources)",
                len(res.listings),
                res.added_count,
                res.removed_count,
                len(res.failed_sources),
            )

        if not args.dry_run and results_by_tool:
            write_combined_rss(
                listings_by_tool=results_by_tool,
                output_path=args.docs_dir / "all.xml",
                channel_link=f"{base_url}/index.html",
            )

        if not args.dry_run and not args.no_push:
            publish_docs(docs_dir=args.docs_dir)

    except Exception as exc:
        unexpected_error = str(exc)
        logger.exception("Run failed with an unexpected error: %s", exc)

    summary_path = write_weekly_summary(
        results=pipeline_results,
        summary_path=args.log_dir / "weekly_summary.txt",
        unexpected_error=unexpected_error,
    )

    if has_failures(pipeline_results, unexpected_error=unexpected_error):
        summary_text = summary_path.read_text(encoding="utf-8")
        try:
            send_failure_email(
                subject="FMP Opportunities run reported warnings or failures",
                body=summary_text,
            )
        except Exception as mail_exc:
            logger.error("Failed to send failure notification email: %s", mail_exc)

    return 1 if unexpected_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
