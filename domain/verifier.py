import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerificationResult:
    passed: bool
    tests_total: int | None
    tests_passed: int | None
    stdout: str
    error: str | None


_OUTCOME_RE = re.compile(r"(\d+) (passed|failed|errors?)\b")


def run_tests(candidate_source: str, test_source: str, timeout: float = 10.0) -> VerificationResult:
    """Objective, executable verification (§D.9 of the design review): runs the
    candidate fix against the task's pytest suite in a separate process, so a bad
    fix can crash or infinite-loop without taking this process down with it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_candidate.py"
        test_file.write_text(candidate_source + "\n\n" + test_source, encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-q"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                passed=False, tests_total=None, tests_passed=None,
                stdout="", error=f"timed out after {timeout}s",
            )

        stdout = proc.stdout
        # pytest's summary line lists outcome counts in whatever order it
        # decides (e.g. "1 failed, 2 passed" -- failed first), not always
        # "passed" first, so every outcome kind is matched independently
        # rather than assuming "passed" comes before an optional "failed".
        counts = {kind: int(n) for n, kind in _OUTCOME_RE.findall(stdout)}
        tests_passed = counts.get("passed") if counts else None
        tests_total = sum(counts.values()) if counts else None

        return VerificationResult(
            passed=(proc.returncode == 0),
            tests_total=tests_total,
            tests_passed=tests_passed,
            stdout=stdout,
            error=None if proc.returncode == 0 else (proc.stderr or "test(s) failed"),
        )
