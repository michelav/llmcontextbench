#!/usr/bin/env python3
"""Compatibility wrapper for llmctxbench adaptation repoqa."""
from __future__ import annotations

import sys


def main(argv=None):
    from ctxbench.cli import main as benchmark_main
    return benchmark_main(['adaptation', 'repoqa', *(sys.argv[1:] if argv is None else argv)])


if __name__ == '__main__':
    raise SystemExit(main())
