"""Optional local LLM classification hook using llama.cpp (OpenAI compatible server)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing

logger = logging.getLogger(__name__)

DEFAULT_LLAMA_ENDPOINT = "http://localhost:8080/v1/chat/completions"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                cleaned = candidate
                break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def create_llama_cpp_hook(
    endpoint: str = DEFAULT_LLAMA_ENDPOINT,
    timeout_seconds: int = 30,
) -> LLMClassifierHook:
    """Return an LLMClassifierHook backed by a local llama.cpp server."""

    def _classify(listing: Listing, tool: str) -> dict[str, Any]:
        placement_instruction = ""
        if tool == "placements":
            placement_instruction = (
                'Also set "type" to one of: "sandwich year", '
                '"graduate scheme or internship (after study)", '
                'or "short term placement (weeks to months)". '
            )

        prompt = (
            "You are filtering opportunities for BA Future Media Production students at "
            "Manchester Metropolitan University (video, audio, motion graphics, creative "
            "technology, UX, games, broadcast, community media).\n"
            f"Tool: {tool}\n"
            f"Title: {listing.title}\n"
            f"Organisation: {listing.organisation}\n"
            f"Location: {listing.location}\n"
            f"Summary: {listing.summary[:300]}\n\n"
            f"{placement_instruction}"
            'Reply ONLY with JSON: {"relevant": true/false, "reason": "short reason"'
            + (', "type": "..."' if tool == "placements" else "")
            + "}"
        )

        resp = requests.post(
            endpoint,
            json={
                "model": "local",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 120,
            },
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        return {
            "relevant": bool(parsed.get("relevant", True)),
            "reason": str(parsed.get("reason", "")),
            "type": parsed.get("type"),
        }

    return _classify
