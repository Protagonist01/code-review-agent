from __future__ import annotations

import pytest

from src.agent.models import DiffHunk
from src.agent.nodes.diff_parser import diff_parser

SIMPLE_DIFF = """diff --git a/src/calculator.py b/src/calculator.py
index abc123..def456 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -10,7 +10,10 @@ def divide(a, b):
     \"\"\"Divide a by b.\"\"\"
-    return a / b
+    if b == 0:
+        return None
+    return a / b
"""

MULTI_FILE_DIFF = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,4 @@
+import os
 def foo():
     pass
diff --git a/src/b.ts b/src/b.ts
--- a/src/b.ts
+++ b/src/b.ts
@@ -5,2 +5,3 @@
+const x = 1;
 function bar() {}
"""

BINARY_DIFF = """diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
"""


@pytest.mark.asyncio
async def test_simple_diff_produces_one_hunk():
    """A diff with a single hunk should yield exactly one DiffHunk."""
    state = {"raw_diff": SIMPLE_DIFF}
    result = await diff_parser(state)
    assert "hunks" in result
    assert len(result["hunks"]) == 1
    hunk: DiffHunk = result["hunks"][0]
    assert hunk.file_path == "src/calculator.py"
    assert hunk.start_line == 10
    assert hunk.language == "Python"


@pytest.mark.asyncio
async def test_multi_file_diff_produces_multiple_hunks():
    """A diff touching two files should yield one hunk per file."""
    state = {"raw_diff": MULTI_FILE_DIFF}
    result = await diff_parser(state)
    assert len(result["hunks"]) == 2
    paths = {h.file_path for h in result["hunks"]}
    assert "src/a.py" in paths
    assert "src/b.ts" in paths


@pytest.mark.asyncio
async def test_binary_file_skipped():
    """Binary file diffs should be ignored and produce no hunks."""
    state = {"raw_diff": BINARY_DIFF}
    result = await diff_parser(state)
    assert len(result["hunks"]) == 0


@pytest.mark.asyncio
async def test_empty_diff_returns_empty_hunks():
    """An empty diff string should return an empty hunks list."""
    state = {"raw_diff": ""}
    result = await diff_parser(state)
    assert result["hunks"] == []


@pytest.mark.asyncio
async def test_language_detection_go():
    """Go source files should be tagged with language='Go'."""
    diff = (
        "diff --git a/main.go b/main.go\n"
        "--- a/main.go\n"
        "+++ b/main.go\n"
        "@@ -1,2 +1,3 @@\n"
        "+import fmt\n"
        " func main() {}\n"
    )
    state = {"raw_diff": diff}
    result = await diff_parser(state)
    if result["hunks"]:
        assert result["hunks"][0].language == "Go"


@pytest.mark.asyncio
async def test_language_detection_typescript():
    """TypeScript source files should be tagged with language='TypeScript'."""
    diff = (
        "diff --git a/src/app.ts b/src/app.ts\n"
        "--- a/src/app.ts\n"
        "+++ b/src/app.ts\n"
        "@@ -1,2 +1,3 @@\n"
        "+const x: number = 1;\n"
        " export {};\n"
    )
    state = {"raw_diff": diff}
    result = await diff_parser(state)
    if result["hunks"]:
        assert result["hunks"][0].language == "TypeScript"


@pytest.mark.asyncio
async def test_lock_file_skipped():
    """Lock files (e.g. package-lock.json) should be excluded from hunks."""
    diff = (
        "diff --git a/package-lock.json b/package-lock.json\n"
        "--- a/package-lock.json\n"
        "+++ b/package-lock.json\n"
        "@@ -1,2 +1,3 @@\n"
        "+{}\n"
    )
    state = {"raw_diff": diff}
    result = await diff_parser(state)
    assert len(result["hunks"]) == 0


@pytest.mark.asyncio
async def test_hunk_content_contains_diff_lines():
    """The hunk content should include the changed lines from the diff."""
    state = {"raw_diff": SIMPLE_DIFF}
    result = await diff_parser(state)
    hunk = result["hunks"][0]
    assert "return a / b" in hunk.content


@pytest.mark.asyncio
async def test_hunk_header_preserved():
    """The hunk_header field should contain the @@ ... @@ marker line."""
    state = {"raw_diff": SIMPLE_DIFF}
    result = await diff_parser(state)
    hunk = result["hunks"][0]
    assert hunk.hunk_header.startswith("@@")


@pytest.mark.asyncio
async def test_oversized_diff_fails_explicitly(monkeypatch):
    """Diffs exceeding max_diff_lines must not produce a clean review."""
    from src.config import settings

    monkeypatch.setattr(settings, "max_diff_lines", 2)
    state = {"raw_diff": SIMPLE_DIFF}
    with pytest.raises(ValueError, match="MAX_DIFF_LINES"):
        await diff_parser(state)
