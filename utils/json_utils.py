"""
Gold Bot v2 – JSON Utilities
==============================
Safe extraction of a JSON object from raw AI model output.

Models occasionally wrap JSON in markdown code fences or add stray text
even when explicitly instructed to return pure JSON. This module makes
parsing tolerant of that without ever silently accepting garbage —
callers must still validate the result with a Pydantic model afterward.
"""

import json
import re


def extract_json_block(text: str) -> dict:
    """
    Extract the first valid {...} JSON object from arbitrary text.

    Handles:
        - Pure JSON (fast path)
        - ```json ... ``` or ``` ... ``` fenced blocks
        - Leading/trailing prose around a JSON object

    Args:
        text: Raw text returned by the AI provider.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON object could be found or parsed.
    """
    if not text or not text.strip():
        raise ValueError("Empty text — cannot extract JSON.")

    cleaned = text.strip()

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # Fast path — the whole cleaned text is valid JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback — find the first {...} block (greedy, handles nested braces
    # reasonably well for the flat schemas used in this project)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in text: {text[:200]!r}")

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Found a {{...}} block but it is not valid JSON: {exc}") from exc
