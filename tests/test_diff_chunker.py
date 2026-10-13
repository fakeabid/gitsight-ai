import re
from pathlib import Path

import pytest

from app.core.config import DEFAULT_NOISE_PATTERNS
from app.domain.diff_chunker import (
    REASON_LIMIT_FULL,
    REASON_LIMIT_PARTIAL,
    REASON_NO_TEXT,
    REASON_NOISE,
    build_chunks,
    is_noise,
)
from tests.helpers import make_new_file_diff

NOISE = list(DEFAULT_NOISE_PATTERNS)
SAMPLE = Path(__file__).parent / "fixtures" / "sample_pr.diff"


@pytest.mark.parametrize(
    "path",
    [
        "package-lock.json",
        "web/yarn.lock",
        "dist/app.js",
        "src/Migrations/001_init.cs",
        "wwwroot/app.min.js",
        "assets/logo.png",
        "server/bin/Debug/x.dll",
        "static/app.js.map",
        "Models/Foo.Designer.cs",
        "icons/a.SVG",
    ],
)
def test_noise_files_are_skipped(path):
    assert is_noise(path, NOISE)


@pytest.mark.parametrize(
    "path",
    [
        "src/rebuild/app.js",
        "cabin/main.py",
        "Standup/src/index.css",
        "src/building.py",
        "docs/map.md",
    ],
)
def test_real_code_is_not_noise(path):
    assert not is_noise(path, NOISE)


def test_noise_and_binary_files_are_reported_not_reviewed():
    binary_diff = (
        "diff --git a/img.bin b/img.bin\nindex 1..2 100644\n"
        "Binary files a/img.bin and b/img.bin differ\n"
    )
    diff = (
        make_new_file_diff("src/app.py", ["print('x')"])
        + make_new_file_diff("package-lock.json", ["{}"])
        + binary_diff
    )
    result = build_chunks(diff, noise_patterns=NOISE, max_chunk_chars=15_000, max_total_chunks=5)
    assert [c.file_paths for c in result.chunks] == [("src/app.py",)]
    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons == {"package-lock.json": REASON_NOISE, "img.bin": REASON_NO_TEXT}


def test_empty_or_noise_only_diff_yields_no_chunks():
    assert (
        build_chunks("", noise_patterns=NOISE, max_chunk_chars=15_000, max_total_chunks=5).chunks
        == []
    )
    only_noise = make_new_file_diff("yarn.lock", ["a"])
    assert (
        build_chunks(
            only_noise, noise_patterns=NOISE, max_chunk_chars=15_000, max_total_chunks=5
        ).chunks
        == []
    )


def test_small_files_are_packed_together_and_never_exceed_the_limit():
    diff = "".join(make_new_file_diff(f"src/f{i}.py", ["x" * 100] * 3) for i in range(6))
    result = build_chunks(diff, noise_patterns=[], max_chunk_chars=1_000, max_total_chunks=50)
    assert len(result.chunks) >= 2
    assert all(len(c.text) <= 1_000 + 1 for c in result.chunks)
    assert {p for c in result.chunks for p in c.file_paths} == {f"src/f{i}.py" for i in range(6)}
    assert [c.index for c in result.chunks] == list(range(1, len(result.chunks) + 1))
    assert all(c.total == len(result.chunks) for c in result.chunks)


def test_oversized_new_file_is_split_with_contiguous_rewritten_hunk_headers():
    lines = [f"line {i:03d} " + "x" * 30 for i in range(1, 501)]
    result = build_chunks(
        make_new_file_diff("src/big.py", lines),
        noise_patterns=[],
        max_chunk_chars=3_000,
        max_total_chunks=50,
    )
    text = "\n".join(c.text for c in result.chunks)
    headers = [(int(s), int(n)) for s, n in re.findall(r"^@@ -0,0 \+(\d+),(\d+) @@", text, re.M)]
    assert len(headers) > 1 and headers[0][0] == 1
    expected = 1
    for start, count in headers:
        assert start == expected
        expected += count
    assert expected == 501  # all 500 lines accounted for, none lost
    assert all(len(c.text) <= 3_000 + 1 for c in result.chunks)


def test_split_keeps_old_and_new_counters_in_sync_for_context_lines():
    body = "\n".join(f" ctx {i:03d} " + "y" * 30 for i in range(200))
    diff = (
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        f"@@ -10,200 +20,200 @@ def f():\n{body}\n"
    )
    result = build_chunks(diff, noise_patterns=[], max_chunk_chars=2_000, max_total_chunks=50)
    text = "\n".join(c.text for c in result.chunks)
    hunks = [
        tuple(map(int, m))
        for m in re.findall(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@ def f\(\):", text, re.M)
    ]
    assert hunks[0][0] == 10 and hunks[0][2] == 20
    for (old, old_n, new, new_n), (next_old, _, next_new, _) in zip(hunks, hunks[1:], strict=False):
        assert next_old == old + old_n and next_new == new + new_n
    assert sum(h[1] for h in hunks) == 200 and sum(h[3] for h in hunks) == 200


def test_chunk_limit_reports_dropped_files():
    diff = "".join(make_new_file_diff(f"src/f{i}.py", ["x" * 45] * 50) for i in range(6))
    result = build_chunks(diff, noise_patterns=[], max_chunk_chars=3_000, max_total_chunks=2)
    assert len(result.chunks) == 2
    assert {s.reason for s in result.skipped} == {REASON_LIMIT_FULL}
    assert len(result.skipped) == 6 - sum(len(c.file_paths) for c in result.chunks)


def test_file_cut_by_the_chunk_limit_is_reported_as_partial():
    big = make_new_file_diff("src/big.py", ["x" * 45] * 400)
    result = build_chunks(big, noise_patterns=[], max_chunk_chars=3_000, max_total_chunks=2)
    assert [(s.path, s.reason) for s in result.skipped] == [("src/big.py", REASON_LIMIT_PARTIAL)]


def test_very_long_lines_are_clipped():
    diff = make_new_file_diff("src/min.py", ["a" * 5_000])
    text = build_chunks(
        diff, noise_patterns=[], max_chunk_chars=15_000, max_total_chunks=5
    ).chunks[0].text
    assert "a" * 5_000 not in text and "[line truncated]" in text


def test_text_inside_a_line_that_mentions_diff_git_does_not_split_a_file():
    diff = make_new_file_diff("src/doc.py", ["# run: diff --git a/x b/x"])
    assert (
        len(
            build_chunks(
                diff, noise_patterns=[], max_chunk_chars=15_000, max_total_chunks=5
            ).chunks
        )
        == 1
    )


@pytest.mark.skipif(
    not SAMPLE.exists(), reason="copy PR-8-AI-Review.txt to tests/fixtures/sample_pr.diff"
)
def test_real_sample_diff_loses_no_added_line():
    diff = SAMPLE.read_text(encoding="utf-8")
    result = build_chunks(diff, noise_patterns=NOISE, max_chunk_chars=15_000, max_total_chunks=5)
    assert {p for c in result.chunks for p in c.file_paths} == {
        "Standup/server.gs",
        "Standup/src/index.css",
        "Standup/src/pages/TaskList.jsx",
        "Standup/src/services/api.js",
    }
    assert not result.skipped and len(result.chunks) >= 2  # 25 KB does not fit one 15 KB chunk

    def added(text: str) -> int:
        return sum(
            1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")
        )

    assert added("\n".join(c.text for c in result.chunks)) == added(diff)
