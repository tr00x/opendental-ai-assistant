"""
briefing.py — AI briefing generator using Claude.

Formats today's appointment data into a structured prompt, streams the
response from Claude, and returns the complete briefing text.
"""
import logging
from datetime import date
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt configuration
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a helpful AI morning briefing assistant for a dental practice's front desk team.
Your job is to analyse today's appointment schedule and deliver a warm, professional,
and well-organised briefing that helps staff start the day prepared and confident.

Structure your briefing in this exact order:

1. GOOD MORNING  — Warm opening with today's date, total appointment count, which
   providers are working, and any headline items worth calling out immediately.

2. SCHEDULE  — Every appointment listed chronologically.  For each one include:
   time | patient name | procedure | room | provider | best contact number.

3. NOTES & FLAGS  — Actionable intelligence for the team:
   • 🎂  Patients with a birthday today — suggest a warm acknowledgement at check-in.
   • ⚠️  Patients with 2 or more broken/missed appointments — recommend a same-day
         confirmation call before the appointment.
   • 🆕  New patients (first visit) — remind staff to have intake forms ready and give
         an especially warm welcome experience.
   • ⏱️  Tight back-to-back gaps (< 10 min) for the same provider — flag as potential
         scheduling pressure points.
   • 📋  Schedule gaps longer than 30 min — note as potential fill-in opportunities.
   • 📅  Double-booked rooms or providers — flag immediately for resolution.

4. CLOSING  — A brief, encouraging sign-off for the team.

Tone rules:
- Address staff directly ("you", "your team") — warm but professional.
- Use clear headings and bullet points so staff can scan in under 2 minutes.
- If there are NO appointments today, deliver a brief upbeat message about the quiet day.
- Do NOT invent information that was not provided.
"""

# ---------------------------------------------------------------------------
# Data formatting
# ---------------------------------------------------------------------------

_INVALID_BIRTHDATE_YEAR = 1900  # Open Dental stores unknown DOBs as 0001-01-01


def _phone_for_patient(apt: dict[str, Any]) -> str:
    """Return the best available phone number for a patient."""
    return (
        apt.get("WirelessPhone")
        or apt.get("HmPhone")
        or "no phone on file"
    )


def _is_valid_birthdate(bd: Any) -> bool:
    """Return True if the birthdate looks like a real date (not OD's 0001-01-01 sentinel)."""
    if bd is None:
        return False
    try:
        return bd.year >= _INVALID_BIRTHDATE_YEAR
    except AttributeError:
        return False


def _format_data_for_prompt(data: dict[str, Any]) -> str:
    """
    Convert the appointment data dict into a structured plain-text block
    that Claude can easily reason over.
    """
    appointments: list[dict[str, Any]] = data["appointments"]
    broken_history: dict[int, int] = data["broken_history"]

    today = date.today()
    lines: list[str] = [
        f"DATE: {today.strftime('%A, %B %d, %Y')}",
        f"TOTAL SCHEDULED APPOINTMENTS: {len(appointments)}",
        "",
    ]

    if not appointments:
        lines.append("No appointments are scheduled for today.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Appointment list
    # ------------------------------------------------------------------
    lines.append("APPOINTMENTS (chronological):")
    lines.append("")

    birthday_patients: list[dict[str, Any]] = []

    for idx, apt in enumerate(appointments, start=1):
        dt = apt["AptDateTime"]
        time_str = dt.strftime("%I:%M %p").lstrip("0")

        pat_name = f"{apt.get('PatFName', '')} {apt.get('PatLName', '')}".strip()
        prov_abbr = apt.get("ProvAbbr") or f"{apt.get('ProvFName', '')} {apt.get('ProvLName', '')}".strip()
        prov_full = f"Dr. {apt.get('ProvFName', '')} {apt.get('ProvLName', '')} ({prov_abbr})".strip()
        room = apt.get("OperatoryName") or f"Op {apt.get('OperatoryNum', '?')}"
        procedure = apt.get("ProcDescript") or "Not specified"
        phone = _phone_for_patient(apt)

        flags: list[str] = []

        # New patient — OpenDental's own IsNewPatient flag
        if apt.get("IsNewPatient"):
            flags.append("🆕 NEW PATIENT")

        # Broken history
        missed = broken_history.get(apt["PatNum"], 0)
        if missed >= 2:
            flags.append(f"⚠️ {missed} broken appointments on record")

        # Birthday
        bd = apt.get("Birthdate")
        if _is_valid_birthdate(bd) and bd.month == today.month and bd.day == today.day:
            flags.append("🎂 BIRTHDAY TODAY")
            birthday_patients.append(apt)

        lines.append(f"{idx}. {time_str} | {prov_full} | {room}")
        lines.append(f"   Patient  : {pat_name}")
        lines.append(f"   Procedure: {procedure}")
        lines.append(f"   Phone    : {phone}")
        if flags:
            lines.append(f"   Flags    : {' | '.join(flags)}")
        lines.append("")

    # ------------------------------------------------------------------
    # Summary sections (provide extra context for Claude's analysis)
    # ------------------------------------------------------------------
    if birthday_patients:
        lines.append("BIRTHDAY PATIENTS TODAY:")
        for apt in birthday_patients:
            bd = apt["Birthdate"]
            age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
            lines.append(f"  - {apt.get('PatFName', '')} {apt.get('PatLName', '')} (turning {age})")
        lines.append("")

    high_risk = [(pn, cnt) for pn, cnt in broken_history.items() if cnt >= 2]
    if high_risk:
        pat_name_map = {
            apt["PatNum"]: f"{apt.get('PatFName', '')} {apt.get('PatLName', '')}".strip()
            for apt in appointments
        }
        lines.append("PATIENTS WITH BROKEN APPOINTMENT HISTORY (2+ missed):")
        for pat_num, cnt in sorted(high_risk, key=lambda x: -x[1]):
            name = pat_name_map.get(pat_num, f"PatNum {pat_num}")
            lines.append(f"  - {name}: {cnt} broken/missed appointments")
        lines.append("")

    new_patient_apts = [apt for apt in appointments if apt.get("IsNewPatient")]
    if new_patient_apts:
        lines.append("NEW PATIENTS TODAY (first visit — IsNewPatient flag):")
        for apt in new_patient_apts:
            name = f"{apt.get('PatFName', '')} {apt.get('PatLName', '')}".strip()
            t = apt["AptDateTime"].strftime("%I:%M %p").lstrip("0")
            lines.append(f"  - {name} at {t}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_briefing(data: dict[str, Any]) -> str:
    """
    Send appointment data to Claude and stream the briefing to the terminal.

    Returns the complete briefing text as a string so the caller can save it.
    """
    user_content = _format_data_for_prompt(data)
    logger.info("Sending appointment data to Claude (model: claude-opus-4-6)")

    client = anthropic.Anthropic()
    text_chunks: list[str] = []

    print()  # blank line before briefing
    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    # Adaptive thinking produces thinking_delta blocks — skip those;
                    # only stream the text_delta blocks to the terminal.
                    if event.delta.type == "text_delta":
                        print(event.delta.text, end="", flush=True)
                        text_chunks.append(event.delta.text)

            final = stream.get_final_message()
            logger.info(
                "Claude response complete. Input tokens: %d, Output tokens: %d",
                final.usage.input_tokens,
                final.usage.output_tokens,
            )

    except anthropic.AuthenticationError:
        raise RuntimeError("Invalid ANTHROPIC_API_KEY — check your .env file.")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic rate limit reached. Try again shortly.")
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(f"Could not reach Anthropic API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc

    print()  # newline after streamed content
    return "".join(text_chunks)
