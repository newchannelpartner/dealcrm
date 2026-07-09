"""AI integration — any OpenAI-compatible chat endpoint (local Ollama, DeepSeek, ...)."""
import json
import os
import re
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)


def _llm_config() -> dict | None:
    """Resolve the active LLM endpoint from the environment.

    Precedence:
      1. LLM_BASE_URL (e.g. http://localhost:11434/v1 for a local Ollama server)
      2. DEEPSEEK_API_KEY (hosted fallback, kept for the deployed instance)
    Returns None if nothing is configured.
    """
    base = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    if base:
        return {
            "url": base + "/chat/completions",
            "model": os.environ.get("LLM_MODEL", "gemma4:31b"),
            "api_key": os.environ.get("LLM_API_KEY", ""),
        }
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return {
            "url": "https://api.deepseek.com/v1/chat/completions",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            "api_key": key,
        }
    return None


def _is_configured() -> bool:
    return _llm_config() is not None

SYSTEM_PROMPT = (
    "You are an assistant to an M&A and private credit professional. "
    "Extract structured intelligence from their notes. "
    "Respond with ONLY valid JSON, no markdown, no preamble."
)


async def analyze_text(text: str) -> dict:
    """Reusable, input-agnostic analysis function.

    Calls the configured LLM to extract structured intelligence from any text.
    Future email scan, meeting notes, or call transcripts can reuse this.
    """
    if not _is_configured():
        return _empty_result()

    if not text or not text.strip():
        return _empty_result()

    response_text = await _call_llm(SYSTEM_PROMPT, text)
    if not response_text:
        return _empty_result()

    parsed = _parse_json_defensively(response_text)
    if not parsed:
        return _empty_result()

    return {
        "summary": str(parsed.get("summary", "")),
        "takeaways": _ensure_list(parsed.get("takeaways")),
        "todos": _ensure_list(parsed.get("todos")),
        "contacts_mentioned": _ensure_list(parsed.get("contacts_mentioned")),
    }


CALL_NOTES_PROMPT = (
    "You are an assistant to an M&A and private credit professional. "
    "The following text is an auto-generated call/meeting transcript summary "
    "(e.g. from Gemini), possibly forwarded as an email with headers. "
    "Ignore email/forwarding boilerplate and extract the substance. "
    "Return ONLY valid JSON, no markdown, with this exact shape:\n"
    "{\n"
    '  "summary": "2-3 sentence summary of the call",\n'
    '  "takeaways": ["key point", "..."],\n'
    '  "deal_hint": {"name": "the deal/project/company this call is about or empty", '
    '"keywords": ["company or project terms to match an existing deal"]},\n'
    '  "contacts": [{"name": "Full Name", "email": "", "firm": "", "title": "", '
    '"role": "who they are / why they matter"}],\n'
    '  "todos": [{"title": "action item", "priority": "high|medium|low", '
    '"due_date_suggestion": "tomorrow|next week|in 3 days|YYYY-MM-DD|empty"}]\n'
    "}\n"
    "Only include people who are actual participants or named stakeholders, not the note-taker. "
    "Only include todos that are genuine action items for the user."
)


async def analyze_call_notes(text: str) -> dict:
    """Extract contacts, todos, and a deal hint from a call-note transcript.

    Richer than analyze_text: also returns participant contacts and a deal_hint
    so the ingestion layer can match/create the right records.
    """
    empty = {"summary": "", "takeaways": [], "deal_hint": {}, "contacts": [], "todos": []}
    if not _is_configured() or not text or not text.strip():
        return empty

    response_text = await _call_llm(CALL_NOTES_PROMPT, text)
    if not response_text:
        return empty

    parsed = _parse_json_defensively(response_text)
    if not parsed:
        return empty

    deal_hint = parsed.get("deal_hint")
    if not isinstance(deal_hint, dict):
        deal_hint = {}

    return {
        "summary": str(parsed.get("summary", "")),
        "takeaways": _ensure_list(parsed.get("takeaways")),
        "deal_hint": {
            "name": str(deal_hint.get("name", "")),
            "keywords": _ensure_list(deal_hint.get("keywords")),
        },
        "contacts": _ensure_list(parsed.get("contacts")),
        "todos": _ensure_list(parsed.get("todos")),
    }


async def _call_llm(system_prompt: str, user_content: str) -> str | None:
    """Make a single call to the configured OpenAI-compatible chat endpoint."""
    cfg = _llm_config()
    if not cfg:
        return None

    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload = {
        "model": cfg["model"],
        # Local "thinking" models (e.g. gemma4) need headroom for reasoning + JSON.
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        "temperature": 0,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    timeout = float(os.environ.get("LLM_TIMEOUT", "180"))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(cfg["url"], headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"LLM API error: {resp.status_code} {resp.text[:500]}")
                return None
    except Exception:
        logger.exception("LLM API call failed")
        return None


def _parse_json_defensively(text: str) -> dict | None:
    """Parse JSON from the LLM response, handling markdown fences and malformed output."""
    # Thinking models (e.g. gemma4) may prepend a <think>...</think> reasoning block.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    logger.warning(f"Failed to parse LLM JSON response: {text[:300]}")
    return None


def _ensure_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def _empty_result() -> dict:
    return {"summary": "", "takeaways": [], "todos": [], "contacts_mentioned": []}


def parse_priority(val: str | None) -> str:
    if val and str(val).lower() in ("high", "urgent"):
        return "high"
    if val and str(val).lower() == "low":
        return "low"
    return "medium"


def parse_due_date(suggestion: str | None) -> datetime | None:
    if not suggestion:
        return None
    now = datetime.now(timezone.utc)
    s = str(suggestion).lower().strip()
    if "tomorrow" in s:
        return now + timedelta(days=1)
    if "next week" in s:
        return now + timedelta(weeks=1)
    if "today" in s:
        return now
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    match = re.search(r"in\s+(\d+)\s+days?", s)
    if match:
        return now + timedelta(days=int(match.group(1)))
    match = re.search(r"in\s+(\d+)\s+weeks?", s)
    if match:
        return now + timedelta(weeks=int(match.group(1)))
    return None
