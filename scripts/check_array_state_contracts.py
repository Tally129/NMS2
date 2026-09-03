#!/usr/bin/env python3
"""Fail when React array state is used without normalization."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

STATE_PATTERN = re.compile(
    r"""
    const\s*\[\s*
    (?P<state>[A-Za-z_$][\w$]*)\s*,\s*
    (?P<setter>[A-Za-z_$][\w$]*)\s*
    \]\s*=\s*
    (?:(?:React\.)?useState)
    \s*\(\s*\[\s*\]\s*\)
    """,
    re.VERBOSE,
)

ARRAY_METHODS = (
    "map",
    "filter",
    "slice",
    "sort",
    "find",
    "some",
    "every",
    "reduce",
    "forEach",
)

problems = []

for path in sorted(SRC.rglob("*.jsx")):
    if ".before-" in path.name:
        continue

    text = path.read_text()
    states = list(STATE_PATTERN.finditer(text))

    for match in states:
        state = match.group("state")
        setter = match.group("setter")

        for line_number, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            if re.search(
                rf"\b{re.escape(setter)}"
                rf"\s*\([^;\n]*\.data\s*\|\|\s*\[\s*\]\)",
                line,
            ):
                problems.append(
                    f"{path.relative_to(ROOT)}:{line_number}: "
                    f"unsafe array assignment: {line.strip()}"
                )

            for method in ARRAY_METHODS:
                if re.search(
                    rf"(?<!normalizeArray\()"
                    rf"\b{re.escape(state)}\.{method}\s*\(",
                    line,
                ):
                    problems.append(
                        f"{path.relative_to(ROOT)}:{line_number}: "
                        f"unsafe {state}.{method}(): {line.strip()}"
                    )

if problems:
    print("Unsafe frontend array-state patterns found:")
    print()

    for problem in problems:
        print(problem)

    print()
    print(
        "Run: python3 scripts/patch_array_state_contracts.py"
    )
    sys.exit(1)

print("Frontend array-state contract check passed.")
