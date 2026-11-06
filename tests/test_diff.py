from worker.diff import added_lines, is_skippable, select_files

PATCH = """@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = 3
 def f():
     return x
@@ -20,2 +21,3 @@ def g():
     a = 1
+    b = 2
 \\ No newline at end of file"""


def test_added_lines_tracks_new_file_numbers_across_hunks():
    # Removed lines do not advance the new-file counter; context lines do.
    assert added_lines(PATCH) == {2, 3, 22}


def test_added_lines_for_new_file():
    assert added_lines("@@ -0,0 +1,3 @@\n+a\n+b\n+c") == {1, 2, 3}


def test_added_lines_ignores_pure_deletions():
    assert added_lines("@@ -1,2 +1,0 @@\n-a\n-b") == set()


def test_skips_noise_files():
    assert is_skippable("package-lock.json", "@@")
    assert is_skippable("web/yarn.lock", "@@")
    assert is_skippable("vendor/lib/x.go", "@@")
    assert is_skippable("app/static/app.min.js", "@@")
    assert is_skippable("proto/user_pb2.py", "@@")
    assert is_skippable("logo.png", None)  # binaries have no patch
    assert not is_skippable("src/app.py", "@@")


def _file(name, patch, changes=1, status="modified"):
    return {"filename": name, "patch": patch, "status": status, "additions": changes}


def test_select_files_prefers_source_and_respects_budget():
    big_src = _file("src/big.py", "@@ -1 +1 @@\n+" + "x" * 50, changes=50)
    small_src = _file("src/small.py", "@@ -1 +1 @@\n+y", changes=1)
    doc = _file("README.md", "@@ -1 +1 @@\n+doc", changes=100)
    lock = _file("uv.lock", "@@ -1 +1 @@\n+z")
    removed = _file("old.py", "@@ -1 +0,0 @@\n-a", status="removed")

    selection = select_files([doc, small_src, big_src, lock, removed], max_diff_chars=80)

    # Source files go first (largest first), README no longer fits in the budget.
    assert [f.path for f in selection.files] == ["src/big.py", "src/small.py"]
    assert selection.truncated == ["README.md"]
    assert set(selection.skipped) == {"uv.lock", "old.py"}
    assert selection.files[0].added == {1}
