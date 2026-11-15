import pytest

from app.url_utils import (
    UnsafeURLError,
    assert_public_url,
    canonicalize_url,
    classify_url,
    extract_youtube_video_id,
    find_first_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # v1 substring-matching regressions: these all contain "x.com" / "github.com"
        ("https://www.vox.com/technology/2024/ai-agents", "article"),
        ("https://blog.dropbox.com/topics/work-culture/remote", "article"),
        ("https://www.linux.com/news/kernel-6", "article"),
        ("https://netflixtechblog.com/some-post", "article"),
        ("https://notgithub.com/owner/repo", "article"),
        ("https://example.com/read?ref=youtube.com", "article"),
        # social
        ("https://x.com/someone/status/123", "unsupported"),
        ("https://twitter.com/someone/status/123", "unsupported"),
        ("https://www.linkedin.com/posts/abc", "unsupported"),
        ("https://m.facebook.com/story", "unsupported"),
        # youtube
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "youtube"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://www.youtube.com/playlist?list=PL123", "unsupported"),
        ("https://www.youtube.com/@channel", "unsupported"),
        # reddit
        ("https://www.reddit.com/r/python/comments/abc123/title/", "reddit"),
        ("https://old.reddit.com/r/python/comments/abc123/title/", "reddit"),
        ("https://www.reddit.com/r/python/", "unsupported"),
        # github
        ("https://github.com/anthropics/claude-code", "github"),
        ("https://github.com/anthropics/claude-code/tree/main", "github"),
        ("https://github.com/owner/repo/blob/main/docs/guide.md", "article"),
        ("https://github.com/owner/repo/blob/main/paper.pdf", "pdf"),
        ("https://github.com/owner", "unsupported"),
        # hn
        ("https://news.ycombinator.com/item?id=12345", "hn"),
        ("https://news.ycombinator.com/news", "unsupported"),
        # pdf
        ("https://arxiv.org/pdf/2401.00001", "pdf"),
        ("https://example.com/files/report.PDF", "pdf"),
        ("https://arxiv.org/abs/2401.00001", "article"),
        ("not a url", "unsupported"),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url) == expected


def test_youtube_id_rejects_lookalike_hosts():
    assert extract_youtube_video_id("https://evil.com/watch?v=dQw4w9WgXcQ") is None
    assert extract_youtube_video_id("https://youtube.com/watch?v=short") is None


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://example.com/post?utm_source=tw&utm_medium=social", "https://www.example.com/post/"),
        ("https://example.com/post?fbclid=xyz#comments", "http://example.com/post"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"),
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ],
)
def test_canonicalize_merges_same_document(a, b):
    assert canonicalize_url(a) == canonicalize_url(b)


def test_canonicalize_keeps_meaningful_params():
    assert canonicalize_url("https://example.com/p?id=1") != canonicalize_url("https://example.com/p?id=2")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("check this https://example.com/a.", "https://example.com/a"),
        ("(see https://example.com/a)", "https://example.com/a"),
        ("wiki https://en.wikipedia.org/wiki/Python_(language) cool",
         "https://en.wikipedia.org/wiki/Python_(language)"),
        ("<https://example.com/x>", "https://example.com/x"),
        ("no link here", None),
    ],
)
def test_find_first_url(text, expected):
    assert find_first_url(text) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/file",
    ],
)
def test_ssrf_guard_blocks_non_public(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)
