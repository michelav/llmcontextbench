"""Failure categories attached where the cause is known.

A call site that knows what it was doing (calling the provider, calling a tool) tags the
exception it lets through. The engine reads the tag when it writes the trace error, so it never
has to guess the cause from the exception text.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from ctxbench.ai.rate_control import classify_provider_error


_ATTRIBUTE = "_ctxbench_failure_category"
UNCLASSIFIED = "unknown"


def tag_failure(exc: BaseException, category: str) -> None:
    """Attach a category to an exception. The first tag wins: it is closest to the cause."""
    if getattr(exc, _ATTRIBUTE, None) is not None:
        return
    try:
        setattr(exc, _ATTRIBUTE, category)
    except (AttributeError, TypeError):
        pass  # exception type without instance attributes; it stays unclassified


def failure_category(exc: BaseException) -> str:
    category = getattr(exc, _ATTRIBUTE, None)
    return category if isinstance(category, str) and category else UNCLASSIFIED


@contextmanager
def provider_call(provider_name: str) -> Iterator[None]:
    """Tag an exception raised by a model adapter call with its provider category."""
    try:
        yield
    except Exception as exc:
        tag_failure(exc, classify_provider_error(provider_name, exc).category)
        raise


@contextmanager
def tool_call() -> Iterator[None]:
    """Tag an exception raised by a tool runtime call."""
    try:
        yield
    except Exception as exc:
        tag_failure(exc, "tool_error")
        raise


__all__ = ["UNCLASSIFIED", "failure_category", "provider_call", "tag_failure", "tool_call"]
