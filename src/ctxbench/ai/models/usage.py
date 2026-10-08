"""Conservative provenance for saved provider usage, without changing artifacts."""
from __future__ import annotations


def _raw_total(provider: str, response: object) -> tuple[int | None, str]:
    if not isinstance(response, dict):
        return None, 'unavailable'
    if provider.startswith('openai') or provider in ('anthropic', 'claude'):
        usage = response.get('usage') or {}
        value = usage.get('total_tokens')
        counts = (usage.get('input_tokens'), usage.get('output_tokens'))
    elif provider in ('google', 'gemini'):
        usage = response.get('usage_metadata') or response.get('usageMetadata') or {}
        value = usage.get('total_token_count', usage.get('totalTokenCount'))
        counts = (usage.get('prompt_token_count', usage.get('promptTokenCount')),
                  usage.get('candidates_token_count', usage.get('candidatesTokenCount')))
    else:
        return None, 'unavailable'
    if type(value) is int and value >= 0:
        return value, 'reported'
    if all(type(v) is int and v >= 0 for v in counts):
        return sum(counts), 'derived'
    return None, 'unavailable'


def account_tokens(provider: str, total_tokens: int | None, *, model_calls: int | None = None,
                   raw_response=None, partial_total=None, missing_total_estimate=None) -> tuple[int | None, str, int | None]:
    """Return complete total, provenance, and a known partial lower bound.

    Multi-call coverage is checked against individual saved responses. Without
    sufficient evidence, keep the complete total unavailable rather than using a
    possibly partial sum to update policy estimates. Mock counts are lexical estimates.
    """
    provider = provider.lower()
    known_partial = total_tokens if total_tokens is not None else partial_total
    if total_tokens is None:
        return None, 'unavailable', known_partial
    if provider in ('mock', 'echo'):
        return total_tokens, 'estimated', None
    if missing_total_estimate is not None:
        return None, 'unavailable', known_partial
    if model_calls and model_calls > 1:
        raw = raw_response if isinstance(raw_response, list) else [raw_response]
        values = [_raw_total(provider, item) for item in raw]
        available = [v for v, _ in values if v is not None]
        if len(raw) != model_calls or len(available) != model_calls:
            return None, 'unavailable', sum(available) if available else known_partial
        if sum(available) != total_tokens:
            raise ValueError('saved usage aggregate conflicts with provider responses')
        return total_tokens, 'derived', None
    value, provenance = _raw_total(provider, raw_response)
    if value is not None and value != total_tokens:
        raise ValueError('saved usage aggregate conflicts with provider response')
    # The canonical value may already be adapter-derived. Without the raw usage
    # fields, do not claim it was returned directly by the provider.
    return total_tokens, provenance if value is not None else 'derived', None
