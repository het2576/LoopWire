"""Frozen copy of the v1 summarizer (git HEAD before this branch), used as the
A/B baseline in summary_eval.py. Same prompt, same schema, same 24k-char
head-only truncation, same temperature - only the HTTP plumbing goes through
app.llm so traces are comparable."""

from pydantic import BaseModel, Field

from app.llm import generate_structured

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


def summarize_item_v1(title: str, content: str, interest_profile: str, model: str | None = None) -> SummaryResult:
    prompt = (
        f"User's stated interests:\n{interest_profile}\n\n"
        f"Content title: {title}\n\n"
        f"Extracted content:\n{content[:MAX_CONTENT_CHARS]}"
    )
    return generate_structured(op="summarize_v1", system=SYSTEM_INSTRUCTION, prompt=prompt,
                               schema=SummaryResult, model=model, temperature=0.3,
                               thinking="low")  # same thinking as v2, so the A/B isolates prompt + truncation
