"""Live extraction smoke test against real URLs (per PRD Phase 2 acceptance bar).

Not a unit test (hits the network) - run manually with:
    uv run python tests/test_extraction_live.py

Prints pass/fail per case. Passes if extraction_success matches the expected
outcome for each case (some cases are *expected* to fail - a paywalled article
and a video with no captions - and correctly flagging that is the pass condition).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import extract_article, extract_youtube

ARTICLE_CASES = [
    ("https://www.paulgraham.com/greatwork.html", True, "normal blog post"),
    ("https://www.nytimes.com/2024/01/01/technology/ai-year-review.html", False, "paywalled article"),
    ("https://simonwillison.net/2024/Dec/31/llms-in-2024/", True, "long-form blog post"),
    ("https://www.theverge.com/2024/1/1/some-nonexistent-slug-xyz", False, "broken/dead link"),
    ("https://stratechery.com/2024/an-image-generation-business-model/", False, "paywalled newsletter"),
]

YOUTUBE_CASES = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True, "short video, has captions"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", True, "very old video (first YouTube video)"),
    ("https://www.youtube.com/watch?v=aircAruvnKk", True, "long educational video (3blue1brown)"),
    ("https://www.youtube.com/watch?v=00000000000", False, "invalid/nonexistent video id"),
    ("https://www.youtube.com/live/jfKfPfyJRdk", False, "live stream, likely no transcript"),
]


def run() -> None:
    print("=== Article extraction ===")
    article_pass = 0
    for url, expect_success, label in ARTICLE_CASES:
        result = extract_article(url)
        ok = result["extraction_success"] == expect_success
        article_pass += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}: success={result['extraction_success']} error={result['error']}")

    print(f"\nArticles: {article_pass}/{len(ARTICLE_CASES)} matched expectation\n")

    print("=== YouTube extraction ===")
    yt_pass = 0
    for url, expect_success, label in YOUTUBE_CASES:
        result = extract_youtube(url)
        ok = result["extraction_success"] == expect_success
        yt_pass += ok
        status = "PASS" if ok else "FAIL"
        print(
            f"[{status}] {label}: success={result['extraction_success']} "
            f"title={result['title']!r} error={result['error']}"
        )

    print(f"\nYouTube: {yt_pass}/{len(YOUTUBE_CASES)} matched expectation")


if __name__ == "__main__":
    run()
