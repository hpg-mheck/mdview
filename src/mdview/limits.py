"""Shared resource limits for mdview input and rendering guardrails."""

from __future__ import annotations

BYTES_PER_KILOBYTE = 1024
BYTES_PER_MEGABYTE = BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE
BYTES_PER_GIGABYTE = BYTES_PER_KILOBYTE * BYTES_PER_MEGABYTE

DEFAULT_BOUNDED_INPUT_MEGABYTES = 16
HUGE_BOUNDED_INPUT_GIGABYTES = 4
DEFAULT_BOUNDED_INPUT_LIMIT_BYTES = DEFAULT_BOUNDED_INPUT_MEGABYTES * BYTES_PER_MEGABYTE
HUGE_BOUNDED_INPUT_LIMIT_BYTES = HUGE_BOUNDED_INPUT_GIGABYTES * BYTES_PER_GIGABYTE

TEXT_READ_CHUNK_KILOBYTES = 64
STDIN_READ_CHUNK_KILOBYTES = 4
TEXT_READ_CHUNK_BYTES = TEXT_READ_CHUNK_KILOBYTES * BYTES_PER_KILOBYTE
STDIN_READ_CHUNK_BYTES = STDIN_READ_CHUNK_KILOBYTES * BYTES_PER_KILOBYTE

GEOMETRY_DEFAULT_RENDER_LIMIT = 512
GEOMETRY_DEFAULT_ABSOLUTE_LIMIT = 16_384
GEOMETRY_INSANE_ABSOLUTE_LIMIT = 65_535


def bounded_input_limit_bytes(*, allow_huge: bool) -> int:
    """Return the active byte limit for bounded text-like inputs."""

    if allow_huge:
        return HUGE_BOUNDED_INPUT_LIMIT_BYTES
    return DEFAULT_BOUNDED_INPUT_LIMIT_BYTES


def geometry_absolute_limit(*, allow_insane_geometry: bool) -> int:
    """Return the largest accepted viewport dimension under active policy."""

    if allow_insane_geometry:
        return GEOMETRY_INSANE_ABSOLUTE_LIMIT
    return GEOMETRY_DEFAULT_ABSOLUTE_LIMIT


def geometry_render_limit(*, allow_insane_geometry: bool) -> int:
    """Return the largest viewport dimension mdview will render into."""

    if allow_insane_geometry:
        return GEOMETRY_INSANE_ABSOLUTE_LIMIT
    return GEOMETRY_DEFAULT_RENDER_LIMIT


def clamp_geometry_for_render(value: int, *, allow_insane_geometry: bool) -> int:
    """Clamp a positive viewport dimension to the active render ceiling."""

    normalized = max(int(value), 1)
    return min(
        normalized,
        geometry_render_limit(allow_insane_geometry=allow_insane_geometry),
    )


def format_byte_limit(byte_count: int) -> str:
    """Return a compact binary-size label for user-facing limit messages."""

    if byte_count % BYTES_PER_GIGABYTE == 0:
        return f"{byte_count // BYTES_PER_GIGABYTE} GiB"
    if byte_count % BYTES_PER_MEGABYTE == 0:
        return f"{byte_count // BYTES_PER_MEGABYTE} MiB"
    return f"{byte_count} bytes"
