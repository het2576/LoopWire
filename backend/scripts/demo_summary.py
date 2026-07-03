"""Runs the real extraction + summarization pipeline against one URL and prints
a markdown snippet ready to paste into the README's example section.

Requires GEMINI_API_KEY to be set. Run with:
    uv run python scripts/demo_summary.py "https://www.paulgraham.com/greatwork.html"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import extract_article
from app.summarize import summarize_item

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

    print("### Example: generated summary vs. source\n")
    print(f"**Source:** [{extracted['title']}]({url})\n")
    print(f"**Generated summary:** {result.summary}\n")
    print(f"**Relevance note:** {result.relevance_note}\n")
    print(f"**Estimated read time:** {result.estimated_read_time_minutes} min\n")
    print(f"**Source word count:** {len(extracted['clean_text'].split())} words\n")


if __name__ == "__main__":
    main()
