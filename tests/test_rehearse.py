import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import rehearse
from tools.migrate import ROOT


class RehearsalTests(unittest.TestCase):
    def run_rehearsal(self, result=None, failure=None, valid=True):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder = Path(directory)
            output = io.StringIO()
            with (
                patch.object(rehearse, "ROOT", folder),
                patch.object(rehearse.shutil, "which", return_value="copilot.exe"),
                patch.object(rehearse, "reset") as reset_mock,
                patch.object(rehearse, "validate", return_value={"ok": valid}),
                patch.object(rehearse, "run_agent", return_value=result, side_effect=failure),
                patch.object(rehearse.sys, "argv", ["rehearse"]),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = rehearse.main()
            report = json.loads((folder / "rehearsal" / "timing.json").read_text())
            return code, report, output.getvalue(), reset_mock.call_args_list

    def test_unicode_agent_output_and_successful_exit(self):
        result = subprocess.CompletedProcess([], 0, "PASS \u2713", "")
        code, report, output, calls = self.run_rehearsal(result)
        self.assertEqual(code, 0)
        self.assertTrue(report["success"])
        self.assertFalse(report["fallback_restored"])
        self.assertIn("PASS", output)
        self.assertEqual(len(calls), 1)

    def test_auth_failure_restores_fallback_without_claiming_generation(self):
        result = subprocess.CompletedProcess([], 1, "", "No authentication information found")
        code, report, output, calls = self.run_rehearsal(result, valid=False)
        self.assertEqual(code, 1)
        self.assertFalse(report["success"])
        self.assertFalse(report["output_validated_independently"])
        self.assertTrue(report["fallback_restored"])
        self.assertEqual(calls[-1].kwargs, {"fallback": True})
        self.assertIn("not agent-generated", output)

    def test_timeout_remains_failure(self):
        error = subprocess.TimeoutExpired(["copilot"], 300, output=b"partial")
        code, report, _, _ = self.run_rehearsal(failure=error, valid=False)
        self.assertEqual(code, 1)
        self.assertTrue(report["timed_out"])
        self.assertEqual(report["returncode"], 124)
        self.assertTrue(report["fallback_restored"])

    def test_missing_cli_leaves_output_untouched(self):
        with patch.object(rehearse.shutil, "which", return_value=None), patch.object(rehearse, "reset") as reset_mock, (
            patch.object(rehearse.sys, "argv", ["rehearse"])
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rehearse.main(), 1)
            reset_mock.assert_not_called()

    def test_real_process_runner_captures_output(self):
        result = rehearse.run_agent([rehearse.sys.executable, "-c", "print('READY')"], 10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "READY")

    def test_real_timeout_stops_owned_process_and_child(self):
        script = ("import subprocess, sys, time; "
                  "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); "
                  "print(child.pid, flush=True); time.sleep(20)")
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            rehearse.run_agent([rehearse.sys.executable, "-c", script], 2)
        self.assertTrue(caught.exception.stdout.strip().isdigit())


if __name__ == "__main__":
    unittest.main()
