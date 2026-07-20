"""Email sending — Resend API + template rendering + AI personalization."""
import os
import re
import logging

logger = logging.getLogger(__name__)

# Resend default sender
# Use onboarding@resend.dev for testing; swap to verified domain email in production.
DEFAULT_FROM = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
REPLY_TO = os.environ.get("RESEND_REPLY_TO", "ncpdealcrm@outlook.com")


def is_smtp_configured() -> bool:
    """Check if Resend API key is configured. Kept old name for compat."""
    return bool(os.environ.get("RESEND_API_KEY", "").strip())


def render_template(template: str, variables: dict) -> str:
    """Replace {variable_name} placeholders with values."""
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return re.sub(r"\{(\w+)\}", replacer, template)


async def send_email(to_email: str, to_name: str, subject: str, body: str) -> tuple[bool, str]:
    """Send a single email via Resend API. Returns (success, error_message)."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return False, "RESEND_API_KEY not configured"

    try:
        import resend
        resend.api_key = api_key

        response = resend.Emails.send({
            "from": DEFAULT_FROM,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "text": body,
        })

        if response and isinstance(response, dict) and response.get("id"):
            return True, ""
        else:
            return False, str(response)

    except Exception as e:
        logger.exception(f"Failed to send email to {to_email}")
        return False, str(e)


async def personalize_with_ai(contact_name: str, contact_firm: str, recent_context: str,
                               body_template: str) -> str:
    """Use AI to personalize a template body for a specific contact."""
    from app.ai import _call_llm, _is_configured
    if not _is_configured():
        return body_template

    prompt = (
        "You are an M&A advisor personalizing an outreach email. "
        "Given the template below, rewrite it naturally for this specific contact. "
        "Keep the same structure and intent, but make it feel personal and warm. "
        "Keep it under 150 words. Return ONLY the finalized email body, no preamble."
    )

    context = (
        f"Contact: {contact_name} at {contact_firm}\n"
        f"Recent context: {recent_context[:500] or 'No prior context'}\n\n"
        f"Template:\n{body_template}"
    )

    result = await _call_llm(prompt, context)
    return result.strip() if result else body_template
