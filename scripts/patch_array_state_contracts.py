#!/usr/bin/env python3
"""
Automatically protect React array state from inconsistent API list responses.

The patcher only targets variables explicitly initialized with:
    React.useState([])
    useState([])

For those variables it:
1. Wraps API/state assignments with normalizeArray().
2. Wraps array render operations such as .map(), .filter(), and .slice().
3. Adds the shared normalizeArray import.
4. Creates one backup per modified file.
5. Writes a migration report.

It does not modify scalar, object, form, or nullable state.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
COLLECTIONS_FILE = SRC / "lib" / "collections"

TARGET_DIRS = [
    SRC / "pages",
    SRC / "components",
    SRC / "hooks",
]

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
    "includes",
)

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


def import_path_for(file_path: Path) -> str:
    relative = os.path.relpath(
        COLLECTIONS_FILE,
        start=file_path.parent,
    ).replace(os.sep, "/")

    if not relative.startswith("."):
        relative = f"./{relative}"

    return relative


def add_import(text: str, file_path: Path) -> tuple[str, bool]:
    if re.search(
        r'import\s*\{\s*normalizeArray\s*\}\s*from\s*["\'][^"\']+collections["\'];?',
        text,
    ):
        return text, False

    import_line = (
        f'import {{ normalizeArray }} from '
        f'"{import_path_for(file_path)}";\n'
    )

    lines = text.splitlines(keepends=True)
    last_import_end = -1
    inside_import = False

    for index, line in enumerate(lines):
        stripped = line.strip()

        if line.startswith("import "):
            last_import_end = index
            inside_import = not stripped.endswith(";")

        elif inside_import:
            last_import_end = index

            if stripped.endswith(";"):
                inside_import = False

        elif last_import_end >= 0 and stripped:
            break

    if last_import_end < 0:
        return import_line + text, True

    lines.insert(last_import_end + 1, import_line)
    return "".join(lines), True


def patch_setter(
    text: str,
    state: str,
    setter: str,
) -> tuple[str, int]:
    changes = 0
    preferred_key = state

    # setState(response.data || [])
    pattern = re.compile(
        rf"""
        \b{re.escape(setter)}
        \s*\(
        \s*
        (?P<expr>
            [A-Za-z_$][\w$]*
            (?:\?\.)?
            \.data
        )
        \s*\|\|\s*\[\s*\]
        \s*
        \)
        """,
        re.VERBOSE,
    )

    def replace_or_empty(match: re.Match) -> str:
        nonlocal changes
        changes += 1

        return (
            f'{setter}(normalizeArray('
            f'{match.group("expr")}, ["{preferred_key}"]))'
        )

    text = pattern.sub(replace_or_empty, text)

    # setState(response.data)
    pattern_direct = re.compile(
        rf"""
        \b{re.escape(setter)}
        \s*\(
        \s*
        (?P<expr>
            [A-Za-z_$][\w$]*
            (?:\?\.)?
            \.data
        )
        \s*
        \)
        """,
        re.VERBOSE,
    )

    def replace_direct(match: re.Match) -> str:
        nonlocal changes

        full = match.group(0)

        if "normalizeArray" in full:
            return full

        changes += 1

        return (
            f'{setter}(normalizeArray('
            f'{match.group("expr")}, ["{preferred_key}"]))'
        )

    text = pattern_direct.sub(replace_direct, text)

    # setState((response.data || []).filter(...))
    pattern_chained = re.compile(
        rf"""
        \b{re.escape(setter)}
        \s*\(
        \s*
        \(
        \s*
        (?P<expr>
            [A-Za-z_$][\w$]*
            (?:\?\.)?
            \.data
        )
        \s*\|\|\s*\[\s*\]
        \s*
        \)
        (?P<chain>
            \s*\.
            (?:filter|map|slice|sort)
            \s*\(
        )
        """,
        re.VERBOSE,
    )

    def replace_chained(match: re.Match) -> str:
        nonlocal changes
        changes += 1

        return (
            f'{setter}(normalizeArray('
            f'{match.group("expr")}, ["{preferred_key}"])'
            f'{match.group("chain")}'
        )

    text = pattern_chained.sub(replace_chained, text)

    return text, changes


def patch_array_methods(
    text: str,
    state: str,
) -> tuple[str, int]:
    changes = 0

    for method in ARRAY_METHODS:
        pattern = re.compile(
            rf"""
            (?<!normalizeArray\()
            (?<![\w$])
            {re.escape(state)}
            \s*\.
            {method}
            \s*\(
            """,
            re.VERBOSE,
        )

        replacement = f"normalizeArray({state}).{method}("

        text, count = pattern.subn(replacement, text)
        changes += count

    return text, changes


def remove_nested_normalizers(text: str) -> tuple[str, int]:
    changes = 0

    # Handles simple accidental nesting:
    # normalizeArray(normalizeArray(value))
    pattern = re.compile(
        r"normalizeArray\(\s*normalizeArray\(([^()]+)\)\s*\)"
    )

    while True:
        text, count = pattern.subn(
            r"normalizeArray(\1)",
            text,
        )

        if count == 0:
            break

        changes += count

    return text, changes


def process_file(path: Path) -> dict | None:
    original = path.read_text()
    matches = list(STATE_PATTERN.finditer(original))

    if not matches:
        return None

    updated = original
    states = []

    for match in matches:
        state = match.group("state")
        setter = match.group("setter")
        states.append((state, setter))

    total_changes = 0

    for state, setter in states:
        updated, count = patch_setter(
            updated,
            state,
            setter,
        )
        total_changes += count

        updated, count = patch_array_methods(
            updated,
            state,
        )
        total_changes += count

    updated, count = remove_nested_normalizers(updated)
    total_changes += count

    if updated == original:
        return None

    updated, import_added = add_import(updated, path)

    backup = path.with_suffix(
        path.suffix + ".before-array-contract-auto"
    )

    if not backup.exists():
        shutil.copy2(path, backup)

    path.write_text(updated)

    return {
        "file": str(path.relative_to(ROOT)),
        "array_states": [state for state, _ in states],
        "changes": total_changes,
        "import_added": import_added,
        "backup": str(backup.relative_to(ROOT)),
    }


def main() -> None:
    results = []

    for directory in TARGET_DIRS:
        if not directory.exists():
            continue

        for path in sorted(directory.rglob("*.jsx")):
            if ".before-" in path.name:
                continue

            result = process_file(path)

            if result:
                results.append(result)
                print(
                    f'UPDATED {result["file"]}: '
                    f'{result["changes"]} change(s), '
                    f'states={result["array_states"]}'
                )

    report = ROOT / "frontend-array-contract-migration.txt"

    lines = [
        "NMS frontend array-contract migration",
        "=====================================",
        "",
        f"Files modified: {len(results)}",
        "",
    ]

    for result in results:
        lines.extend([
            f'File: {result["file"]}',
            f'Array states: {", ".join(result["array_states"])}',
            f'Changes: {result["changes"]}',
            f'Import added: {result["import_added"]}',
            f'Backup: {result["backup"]}',
            "",
        ])

    report.write_text("\n".join(lines))

    print()
    print(f"Modified files: {len(results)}")
    print(f"Report: {report.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
