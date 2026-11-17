"""Known defects from AUDIT.md that are NOT fixed yet, written as the behaviour we WANT.

Each test is marked xfail(strict=True): it fails today (expected). When the matching phase fixes it, the
test XPASSes, strict mode turns that into a failure, and the fix removes the marker (moving the test to
a normal test file) - so a fix can never land without its test and can never silently regress.

Fixed and moved to normal test files: S1, S3-S9, S11 (test_security.py), bug 10 / S2 (test_recovery_phase3.py),
bugs 1-7 (test_truth_engine.py).

Nothing is currently open. Add new xfail tests here as defects are found.
"""
