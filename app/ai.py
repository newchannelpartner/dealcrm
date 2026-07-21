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


WHATSAPP_PROMPT = (
    "You are an assistant to an M&A and private credit professional. "
    "The following is a WhatsApp group chat export. Extract business-relevant intelligence. "
    "Ignore casual banter, greetings, and non-business messages. Focus on:\n"
    "- Deal discussions, company names, valuation hints\n"
    "- Action items or commitments made by specific people\n"
    "- New contacts mentioned with their roles\n"
    "- Market intelligence, competitor moves, deal rumors\n\n"
    "Return ONLY valid JSON, no markdown, with this shape:\n"
    "{\n"
    '  "summary": "2-3 sentence summary of the business-relevant chat",\n'
    '  "takeaways": ["key business point", "..."],\n'
    '  "deal_hint": {"name": "deal or company name mentioned, or empty", '
    '"keywords": ["terms to match existing deals"]},\n'
    '  "contacts": [{"name": "Full Name", "firm": "", "title": "", '
    '"role": "context from conversation"}],\n'
    '  "todos": [{"title": "action item", "priority": "high|medium|low", '
    '"due_date_suggestion": "tomorrow|next week|in 3 days|YYYY-MM-DD|empty"}]\n'
    "}"
)


async def analyze_whatsapp_chat(text: str) -> dict:
    """Parse WhatsApp group chat export for business intelligence.

    Handles the standard WhatsApp export format:
    [DD/MM/YY, HH:MM] Sender: Message
    Also handles forwarded messages with header boilerplate.
    """
    empty = {"summary": "", "takeaways": [], "deal_hint": {}, "contacts": [], "todos": []}
    if not _is_configured() or not text or not text.strip():
        return empty

    # Strip WhatsApp forwarding headers
    text = re.sub(r"^.*Forwarded.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"( WhatsApp Chat with |Messages and calls are end-to-end encrypted).*", "", text)

    response_text = await _call_llm(WHATSAPP_PROMPT, text[:3000])
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


CONTACT_ENRICH_PROMPT = (
    "You are an M&A and private equity research analyst. "
    "Given a contact's name, firm, and email domain, generate a professional enrichment profile. "
    "Use your knowledge of the firm's industry, recent deals, and market position. "
    "Be factual — if unsure, leave the field blank. "
    "Return ONLY valid JSON, no markdown:\n{\n"
    '  "firm_description": "1-2 sentence description of what the firm does",\n'
    '  "industry": "primary industry sector (e.g. Personal Injury Law, Commercial Litigation)",\n'
    '  "firm_size": "approximate attorney count or revenue range if known, or empty",\n'
    '  "recent_news": "any notable recent M&A, expansion, or leadership news about this firm",\n'
    '  "relevance": "why this contact/firm is relevant for M&A in the PI law space",\n'
    '  "suggested_tags": ["tag1", "tag2"]\n}'
)


async def enrich_contact(name: str, firm: str, email: str = "") -> dict:
    """Enrich a contact with AI-generated firm and industry intelligence."""
    empty = {"firm_description": "", "industry": "", "firm_size": "",
             "recent_news": "", "relevance": "", "suggested_tags": []}
    if not _is_configured() or not name.strip():
        return empty

    context = f"Contact: {name}\nFirm: {firm or 'unknown'}\nEmail domain: {email.split('@')[-1] if '@' in email else 'unknown'}"
    response_text = await _call_llm(CONTACT_ENRICH_PROMPT, context)
    if not response_text:
        return empty

    parsed = _parse_json_defensively(response_text)
    if not parsed:
        return empty

    return {
        "firm_description": str(parsed.get("firm_description", "")),
        "industry": str(parsed.get("industry", "")),
        "firm_size": str(parsed.get("firm_size", "")),
        "recent_news": str(parsed.get("recent_news", "")),
        "relevance": str(parsed.get("relevance", "")),
        "suggested_tags": _ensure_list(parsed.get("suggested_tags")),
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


# ──────────────────────────────────────────────
#  Proactive AI — pitch, briefing, follow-ups
# ──────────────────────────────────────────────

PITCH_PROMPT = (
    "You are an M&A advisor writing for an internal team meeting. "
    "Given the deal details below, write a **3-sentence elevator pitch** that a team member "
    "can use to quickly brief others. Include: what the deal is, why it matters, and current status. "
    "Return ONLY the pitch text, no preamble, no markdown."
)

BRIEFING_PROMPT = (
    "You are an M&A analyst preparing a morning briefing for your team. "
    "Analyze the deal information below and return ONLY valid JSON (no markdown) with this shape:\n"
    "{\n"
    '  "summary": "2-3 sentence executive summary",\n'
    '  "key_points": ["bullet 1", "bullet 2", "bullet 3"],\n'
    '  "next_actions": "what to do next — one sentence",\n'
    '  "risk_flag": "one-sentence risk or concern, or empty string if none"\n'
    "}"
)

FOLLOWUP_PROMPT = (
    "You are an M&A professional maintaining a client relationship. "
    "Draft a **brief, warm follow-up email** to the contact described below. "
    "They haven't been contacted in a while. Reference past context naturally. "
    "Keep it 3-5 sentences, professional but not stiff. "
    "Return ONLY the email body, no subject line, no preamble."
)


async def generate_deal_pitch(name: str, deal_type: str, stage: str,
                               size_mm: float | None, notes: str,
                               milestones: list) -> str | None:
    """Generate a 3-sentence elevator pitch for a deal."""
    if not _is_configured():
        return None

    type_labels = {
        "sell-side": "Sell-Side M&A", "buy-side": "Buy-Side M&A",
        "credit": "Private Credit", "independent-sponsor": "Independent Sponsor",
    }
    type_str = type_labels.get(deal_type, deal_type)
    size_str = f"${size_mm}M" if size_mm else "undisclosed"
    done = [m.get("name", "") for m in (milestones or []) if m.get("done")]
    ms_str = ", ".join(done) if done else "none yet"

    context = (
        f"Deal: {name}\n"
        f"Type: {type_str}\n"
        f"Stage: {stage}\n"
        f"Size: {size_str}\n"
        f"Milestones completed: {ms_str}\n"
        f"Notes: {notes[:800] if notes else 'No notes yet'}"
    )

    result = await _call_llm(PITCH_PROMPT, context)
    return result.strip() if result else None


async def generate_deal_briefing(
    deal_name: str, deal_type: str, deal_stage: str,
    size_mm: float | None, expected_fee: float | None,
    fee_type: str, milestones: list,
    contact_names: str, notes_summary: str,
    open_todos: list, notes_text: str,
) -> dict | None:
    """Generate a structured morning briefing for a deal."""
    if not _is_configured():
        return None

    type_labels = {
        "sell-side": "Sell-Side M&A", "buy-side": "Buy-Side M&A",
        "credit": "Private Credit", "independent-sponsor": "Independent Sponsor",
    }

    todo_str = "; ".join(
        f"[{t.get('priority', '')}] {t.get('title', '')}" for t in (open_todos or [])[:5]
    ) or "none"

    done = [m.get("name", "") for m in (milestones or []) if m.get("done")]
    pending = [m.get("name", "") for m in (milestones or []) if not m.get("done")]

    context = (
        f"Deal: {deal_name}\n"
        f"Type: {type_labels.get(deal_type, deal_type)}\n"
        f"Stage: {deal_stage}\n"
    )
    context += f"Size: ${size_mm}M\n" if size_mm else "Size: undisclosed\n"
    context += f"Expected Fee: ${expected_fee}K ({fee_type})\n" if expected_fee else ""
    context += f"Key Contacts: {contact_names or 'none'}\n"
    context += f"Milestones done: {', '.join(done) or 'none'}\n"
    context += f"Milestones pending: {', '.join(pending) or 'none'}\n"
    context += f"Open Todos: {todo_str}\n"
    if notes_summary:
        context += f"Recent Notes Summary: {notes_summary[:600]}\n"
    context += f"Full Notes: {(notes_text or '')[:1200]}"

    result = await _call_llm(BRIEFING_PROMPT, context)
    if not result:
        return None

    parsed = _parse_json_defensively(result)
    if not parsed:
        return None

    return {
        "summary": str(parsed.get("summary", "")),
        "key_points": _ensure_list(parsed.get("key_points")),
        "next_actions": str(parsed.get("next_actions", "")),
        "risk_flag": str(parsed.get("risk_flag", "")),
    }


async def generate_followup_email(
    contact_name: str, firm: str, tier: str,
    recent_context: str,
) -> str | None:
    """Draft a follow-up email for a contact who hasn't been contacted recently."""
    if not _is_configured():
        return None

    tier_label = {"A": "core (most important)", "B": "regular", "C": "occasional"}.get(tier, "")

    context = (
        f"Contact: {contact_name}\n"
        f"Firm: {firm or 'unknown'}\n"
        f"They are a {tier_label} contact.\n"
        f"Last conversation context: {recent_context[:1000] or 'No recent notes'}"
    )

    result = await _call_llm(FOLLOWUP_PROMPT, context)
    return result.strip() if result else None
