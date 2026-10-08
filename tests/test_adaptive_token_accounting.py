import pytest
from ctxbench.ai.models.usage import account_tokens


def test_multi_call_provenance_and_missing_coverage():
    raw = [{'usage': {'total_tokens': 10}}, {'usage': {'total_tokens': 20}}]
    assert account_tokens('openai', 30, model_calls=2, raw_response=raw) == (30, 'derived', None)
    raw[1]['usage'] = {}
    assert account_tokens('openai', 10, model_calls=2, raw_response=raw) == (None, 'unavailable', 10)
    assert account_tokens('openai', None, partial_total=10) == (None, 'unavailable', 10)
    assert account_tokens('openai', 10, model_calls=2) == (None, 'unavailable', 10)
    assert account_tokens('mock', 10) == (10, 'estimated', None)
    assert account_tokens('openai', 10) == (10, 'derived', None)
    assert account_tokens('openai', 10, raw_response={'usage': {'total_tokens': 10}}) == (10, 'reported', None)


def test_saved_aggregate_conflict_and_derived_anthropic():
    with pytest.raises(ValueError, match='conflicts'):
        account_tokens('openai', 30, model_calls=2, raw_response=[{'usage': {'total_tokens': 10}}] * 2)
    assert account_tokens('anthropic', 30) == (30, 'derived', None)


@pytest.mark.parametrize('provider,raw', [
    ('openai', {'usage': {'input_tokens': 10, 'output_tokens': 20}}),
    ('anthropic', {'usage': {'input_tokens': 10, 'output_tokens': 20}}),
    ('google', {'usage_metadata': {'prompt_token_count': 10, 'candidates_token_count': 20}}),
])
def test_derived_provider_components(provider, raw):
    assert account_tokens(provider, 30, raw_response=raw) == (30, 'derived', None)
    assert account_tokens(provider, 60, model_calls=2, raw_response=[raw, raw]) == (60, 'derived', None)
