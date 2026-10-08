"""RepoQA-specific nominal sizing; never expose variant identity to policies."""
from ctxbench.adaptive.types import RequestFeatures, SizeBin


def prepare_request_features(sequence_index: int, context_bytes: int, nominal_variant: str) -> RequestFeatures:
    bins = {"2k": SizeBin.SMALL, "4k": SizeBin.SMALL,
            "8k": SizeBin.LARGE, "16k": SizeBin.LARGE}
    if nominal_variant not in bins:
        raise ValueError("unsupported RepoQA nominal variant")
    return RequestFeatures(sequence_index, context_bytes, bins[nominal_variant])
