from __future__ import annotations

from ctxbench.adapters.lattes.models import LattesCurriculum


class LattesReader:
    def read(self, path: str) -> LattesCurriculum:
        raise NotImplementedError
