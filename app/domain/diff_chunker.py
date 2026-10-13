"""Pure functions that turn a unified diff into LLM-sized chunks. No I/O, no LangGraph."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schemas.review import SkippedFile

MAX_LINE_CHARS = 2_000

REASON_NOISE = "generated or non-code file"
REASON_NO_TEXT = "no textual changes (binary, rename or mode change)"
REASON_LIMIT_PARTIAL = "partially reviewed: chunk limit reached"
REASON_LIMIT_FULL = "not reviewed: chunk limit reached"
LIMIT_REASONS = frozenset({REASON_LIMIT_PARTIAL, REASON_LIMIT_FULL})

_FILE_BOUNDARY = re.compile(r"(?m)^(?=diff --git )")
_DIFF_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_HUNK_HEADER = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@(?P<tail>.*)$")


@dataclass(frozen=True)
class Chunk:
    index: int  # 1-based
    total: int
    text: str
    file_paths: tuple[str, ...]


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[Chunk]
    skipped: list[SkippedFile]


@dataclass
class _FileDiff:
    path: str
    header: list[str]
    hunks: list[list[str]]  # each hunk: [@@ line, body lines...]


@dataclass(frozen=True)
class _Piece:
    path: str
    text: str


# ----------------------------------------------------------------------------- parsing


def split_file_sections(diff: str) -> list[str]:
    return [s for s in _FILE_BOUNDARY.split(diff) if s.startswith("diff --git ")]


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + " ...[line truncated]"


def _extract_path(header: Sequence[str]) -> str:
    match = _DIFF_HEADER.match(header[0])
    if match:
        return match.group("b").strip('"')
    for line in header:  # fallback for quoted paths: "+++ b/<path>"
        if line.startswith("+++ ") and "/dev/null" not in line:
            return line[4:].removeprefix("b/").strip('"')
    return header[0].removeprefix("diff --git").strip()


def parse_file(section: str) -> _FileDiff:
    header: list[str] = []
    hunks: list[list[str]] = []
    for line in (_clip(raw) for raw in section.splitlines()):
        if line.startswith("@@"):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
        else:
            header.append(line)
    return _FileDiff(path=_extract_path(header), header=header, hunks=hunks)


# ----------------------------------------------------------------------------- noise


def is_noise(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/").lower()
    segments = normalized.split("/")
    file_name = segments[-1]
    directories = segments[:-1]
    for raw in patterns:
        pattern = raw.lower().strip()
        if pattern.endswith("/") or pattern.startswith("/"):
            if pattern.strip("/") in directories:
                return True
        elif pattern.startswith("."):
            if file_name.endswith(pattern):
                return True
        elif file_name == pattern:
            return True
    return False


# ----------------------------------------------------------------------------- splitting


def _size(lines: Iterable[str]) -> int:
    return sum(len(line) + 1 for line in lines)


def _split_hunk(hunk: list[str], budget: int) -> list[list[str]]:
    """Split one oversized hunk at line boundaries, rewriting each part's @@ header."""
    if _size(hunk) <= budget:
        return [hunk]
    match = _HUNK_HEADER.match(hunk[0])
    if match is None:  # malformed header: cannot rewrite safely, keep whole
        return [hunk]

    tail = match.group("tail")
    start_old, start_new = int(match.group("old")), int(match.group("new"))
    limit = budget - len(hunk[0]) - 20  # room for the rewritten header
    parts: list[list[str]] = []
    body: list[str] = []
    old_count = new_count = size = 0

    def flush() -> None:
        nonlocal body, old_count, new_count, size, start_old, start_new
        header = f"@@ -{start_old},{old_count} +{start_new},{new_count} @@{tail}"
        parts.append([header, *body])
        start_old += old_count
        start_new += new_count
        body, old_count, new_count, size = [], 0, 0, 0

    for line in hunk[1:]:
        cost = len(line) + 1
        if body and size + cost > limit:
            flush()
        body.append(line)
        size += cost
        if line.startswith("+"):
            new_count += 1
        elif line.startswith("-"):
            old_count += 1
        elif not line.startswith("\\"):  # context line (or empty context line)
            old_count += 1
            new_count += 1
    if body:
        flush()
    return parts


def _file_to_pieces(file: _FileDiff, max_chars: int) -> list[_Piece]:
    header_size = _size(file.header)
    budget = max(max_chars - header_size, max_chars // 2)
    hunks = [part for hunk in file.hunks for part in _split_hunk(hunk, budget)]

    pieces: list[_Piece] = []
    current: list[list[str]] = []
    size = 0

    def emit() -> None:
        lines = [*file.header, *(line for hunk in current for line in hunk)]
        pieces.append(_Piece(path=file.path, text="\n".join(lines)))

    for hunk in hunks:
        hunk_size = _size(hunk)
        if current and size + hunk_size > budget:
            emit()
            current, size = [], 0
        current.append(hunk)
        size += hunk_size
    if current:
        emit()
    return pieces


# ----------------------------------------------------------------------------- packing


def _pack(pieces: Sequence[_Piece], max_chars: int) -> list[list[_Piece]]:
    groups: list[list[_Piece]] = []
    current: list[_Piece] = []
    size = 0
    for piece in pieces:
        piece_size = len(piece.text) + 1
        if current and size + piece_size > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(piece)
        size += piece_size
    if current:
        groups.append(current)
    return groups


def _dropped_files(kept: list[list[_Piece]], dropped: list[list[_Piece]]) -> list[SkippedFile]:
    kept_paths = {piece.path for group in kept for piece in group}
    result: dict[str, SkippedFile] = {}
    for group in dropped:
        for piece in group:
            if piece.path not in result:
                reason = REASON_LIMIT_PARTIAL if piece.path in kept_paths else REASON_LIMIT_FULL
                result[piece.path] = SkippedFile(path=piece.path, reason=reason)
    return list(result.values())


# ----------------------------------------------------------------------------- public API


def build_chunks(
    diff: str,
    *,
    noise_patterns: Sequence[str],
    max_chunk_chars: int,
    max_total_chunks: int,
) -> ChunkingResult:
    skipped: list[SkippedFile] = []
    pieces: list[_Piece] = []

    for section in split_file_sections(diff):
        file = parse_file(section)
        if is_noise(file.path, noise_patterns):
            skipped.append(SkippedFile(path=file.path, reason=REASON_NOISE))
        elif not file.hunks:
            skipped.append(SkippedFile(path=file.path, reason=REASON_NO_TEXT))
        else:
            pieces.extend(_file_to_pieces(file, max_chunk_chars))

    groups = _pack(pieces, max_chunk_chars)
    kept, dropped = groups[:max_total_chunks], groups[max_total_chunks:]
    skipped.extend(_dropped_files(kept, dropped))

    chunks = [
        Chunk(
            index=number,
            total=len(kept),
            text="\n".join(piece.text for piece in group) + "\n",
            file_paths=tuple(dict.fromkeys(piece.path for piece in group)),
        )
        for number, group in enumerate(kept, start=1)
    ]
    return ChunkingResult(chunks=chunks, skipped=skipped)
