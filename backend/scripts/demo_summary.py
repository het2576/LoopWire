"""Runs the real extraction + summarization pipeline against one URL and prints
a markdown snippet ready to paste into the README's example section.

Requires GEMINI_API_KEY to be set. Run with:
    uv run python scripts/demo_summary.py "https://www.paulgraham.com/greatwork.html"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import count_words, extract_article
from app.recall import quote_is_grounded
from app.summarize import summarize_item
from app.worker import compute_read_time_minutes

DEFAULT_INTEREST_PROFILE = (
    "Interested in software engineering (backend systems, AI/LLM applications, developer tools), "
    "startups and product building, and practical productivity/personal-systems ideas."
)


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.paulgraham.com/greatwork.html"
    extracted = extract_article(url)

    if not extracted["extraction_success"]:
        print(f"Extraction failed: {extracted['error']}")
        return

    result = summarize_item(
        title=extracted["title"] or url,
        content=extracted["clean_text"],
        interest_profile=DEFAULT_INTEREST_PROFILE,
    )

    words = count_words(extracted["clean_text"])
    print("### Example: generated summary vs. source\n")
    print(f"**Source:** [{extracted['title']}]({url}) ({words:,} words extracted)\n")
    print(f"**Summary:** {result.summary}\n")
    print(f"**Key takeaway:** {result.key_takeaway}\n")
    print(f"**Relevance note:** {result.relevance_note}\n")
    print(f"**Read time:** {compute_read_time_minutes(words, None)} min (computed from the word count)\n")
    for card in result.recall_cards:
        grounded = quote_is_grounded(card.evidence_quote, extracted["clean_text"])
        print(f"**Recall card{'' if grounded else ' (DROPPED: quote not found in source)'}:** {card.question} -> {card.answer}\n")


if __name__ == "__main__":
    main()
