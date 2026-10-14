"""RepoQA-specific nominal sizing; never expose variant identity to policies."""
from ctxbench.adaptive.types import RequestFeatures, SizeBin


def prepare_request_features(sequence_index: int, context_bytes: int, nominal_variant: str,
                             profile: str = "standard") -> RequestFeatures:
    bins = {"2k": SizeBin.SMALL, "4k": SizeBin.SMALL,
            "8k": SizeBin.LARGE, "16k": SizeBin.LARGE}
    if profile == "long64":
        bins = {"2k": SizeBin.SMALL, "4k": SizeBin.SMALL,
                "8k": SizeBin.MEDIUM, "16k": SizeBin.MEDIUM,
                "32k": SizeBin.LARGE, "64k": SizeBin.LARGE}
    elif profile != "standard":
        raise ValueError("unsupported RepoQA size profile")
    if nominal_variant not in bins:
        raise ValueError("unsupported RepoQA nominal variant")
    return RequestFeatures(sequence_index, context_bytes, bins[nominal_variant])
