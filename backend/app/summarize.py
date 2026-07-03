"""Structured summarization + relevance scoring (Loopwire Phase 3).

Grounding rule (PRD principle #2): the LLM is instructed to never add
information not present in the extracted content, and to say so plainly if
the extracted content is too thin to summarize confidently.
"""

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings

# Rough safety cap so a very long transcript/article doesn't blow the context
# window or run up cost - PRD only needs a 2-3 sentence summary either way.
MAX_CONTENT_CHARS = 24_000

SYSTEM_INSTRUCTION = """\
You are a sharp, opinionated reading assistant for Loopwire — a personal dispatch tool
that saves links and turns them into concise, meaningful briefs.

Your job is to produce a summary that a thoughtful, busy reader will actually use.
Write like a senior editor, not a press release.

━━ Rules you must follow exactly ━━

1. GROUND IN THE TEXT ONLY.
   Base every claim in the extracted content provided. Never add facts, examples,
   or context from general knowledge — even if you're confident about them.

2. BE HONEST ABOUT THIN CONTENT.
   If the extracted content is sparse, cut off, or paywalled, say so directly in
   the summary field (e.g. "Only an intro was extractable — likely behind a paywall.")
   Do NOT pad or speculate.

3. LEAD WITH WHAT MATTERS.
   The first sentence should give the reader the single most important takeaway.
   Avoid throat-clearing phrases like "The article discusses..." or "This piece covers...".

4. WRITE IN AN ACTIVE, DIRECT VOICE.
   Use plain, clear language. Prefer short sentences. Cut filler words.
   Max 3 sentences total, but each sentence should pull its weight.

5. RELEVANCE NOTE — CONNECT OR ADMIT THERE'S NO CONNECTION.
   In one sentence explain why this content connects to the user's stated interests.
   If there's genuinely no clear link, write exactly: "General interest"
   Never stretch or force a connection that isn't clearly present.

6. READ TIME — BASE IT ON ACTUAL CONTENT LENGTH.
   Use ~200 words/minute for articles. For YouTube, use actual video length if
   inferable from the transcript structure; otherwise estimate from transcript
   word count at the same rate. Round to the nearest minute (minimum 1).

7. ALWAYS RESPOND IN ENGLISH.
   The extracted content may be in any language (e.g. a Hindi or Hinglish
   auto-generated YouTube transcript). Read and understand it in its original
   language, but always write the summary, key takeaway, and relevance note
   in English, regardless of the source language.
\
"""


class SummaryResult(BaseModel):
    summary: str = Field(
        description=(
            "2–3 punchy sentences grounded only in the extracted text. "
            "Lead with the single most important takeaway. Write actively, cut filler."
        )
    )
    key_takeaway: str = Field(
        description=(
            "One crisp sentence — the single thing the reader should walk away knowing. "
            "Must be factual and grounded in the text."
        )
    )
    relevance_note: str = Field(
        description=(
            "1 sentence on why this connects to the user's stated interests, "
            "or exactly 'General interest' if there's no clear link."
        )
    )
    estimated_read_time_minutes: int = Field(
        description="Estimated read/watch time in whole minutes (minimum 1)."
    )


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set - see SETUP.md")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def summarize_item(title: str, content: str, interest_profile: str) -> SummaryResult:
    settings = get_settings()
    truncated = content[:MAX_CONTENT_CHARS]

    prompt = (
        f"User's stated interests:\n{interest_profile}\n\n"
        f"Content title: {title}\n\n"
        f"Extracted content:\n{truncated}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=SummaryResult,
            temperature=0.3,  # slightly more expressive than 0.2 while staying grounded
        ),
    )

    parsed = response.parsed
    if parsed is None:
        raise ValueError(f"Gemini did not return parseable structured output: {response.text!r}")
    return parsed


# ── Phase B: grounded relevance notes from real engagement, not a static bio ──

GROUNDED_RELEVANCE_SYSTEM_INSTRUCTION = """\
You write one-sentence "why this matters to you" notes for a personal reading dispatch.

You'll be given a new item's title and summary, plus 1-2 items the user has
previously opened or clicked through to read that are similar to it. Write ONE
sentence explaining why the new item is relevant, explicitly naming the similar
past item(s) (e.g. "Similar to 'How to Do Great Work', which you read recently.").

Rules:
- Only ever reference items actually provided to you below - never invent
  or assume a past item that wasn't listed.
- One sentence, plain and direct - no throat-clearing.
- Don't oversell a loose connection; if it's simply topically related, say so plainly.
"""


class RelevanceNoteResult(BaseModel):
    relevance_note: str = Field(
        description="One sentence connecting the new item to a specific similar past item, naming it."
    )


def generate_grounded_relevance_note(title: str, summary: str, similar_titles: list[str]) -> str:
    """Used instead of the static-bio relevance note once a user has enough
    engagement history to have real "similar to X" evidence (prdv2.md B.3.5)."""
    settings = get_settings()
    prompt = (
        f"New item: {title}\n{summary}\n\n"
        "Items the user previously engaged with that are similar:\n"
        + "\n".join(f"- {t}" for t in similar_titles)
    )

    client = _get_client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=GROUNDED_RELEVANCE_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RelevanceNoteResult,
            temperature=0.3,
        ),
    )

    parsed = response.parsed
    if parsed is None:
        raise ValueError(f"Gemini did not return parseable output: {response.text!r}")
    return parsed.relevance_note
