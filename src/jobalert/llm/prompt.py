"""The extraction prompt.

Kept in one place because it is the highest-leverage text in the project — the
quality of every downstream field depends on it, and it is the thing you will
tune most often.
"""

from __future__ import annotations

from ..settings import load_profile
from ..util import truncate

# Job descriptions run long. This bounds cost and keeps us inside free-tier
# context limits; the first ~6k characters carry the role, requirements and
# location in virtually every posting.
MAX_DESCRIPTION_CHARS = 6000


def build_system_prompt() -> str:
    profile = load_profile()
    families = ", ".join(profile.get("families", []))
    levels = ", ".join(profile.get("seniority_levels", []))

    return f"""You extract structured facts from job postings. Reply with JSON only.

Return an object with exactly these keys:
  family                 one of: {families}
  seniority              one of: {levels}
  skills                 array of strings, max 12, the skills actually required
  tech_stack             array of strings, max 12, named technologies only
  years_experience_min   integer, or null if unstated
  salary_min             number, or null if unstated
  salary_max             number, or null if unstated
  salary_currency        ISO code such as INR, USD, EUR, or null
  remote_policy          one of: remote, hybrid, onsite, unclear
  summary                one sentence, max 200 characters, what the role is

Rules:
- Extract only what the posting states. Never infer a salary that is not written.
- Do not convert currencies; report the number and currency as given.
- If the posting does not fit any family cleanly, use "other".
- Prefer the specific over the generic: "PySpark" not "big data".
"""


def build_user_prompt(
    company: str, title: str, location: str | None, description: str | None
) -> str:
    body = truncate(description, MAX_DESCRIPTION_CHARS) or "(no description provided)"
    return (
        f"Company: {company}\n"
        f"Title: {title}\n"
        f"Location: {location or 'not stated'}\n\n"
        f"Description:\n{body}"
    )
