"""Time a real Copilot CLI custom-agent run from a clean before state."""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

try:
    from .migrate import ROOT
    from .reset import reset
    from .validate import validate
except ImportError:
    from migrate import ROOT
    from reset import reset
    from validate import validate


def run_agent(command, timeout):
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", **options)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise RuntimeError("Cannot stop the timed-out agent tree: PowerShell is unavailable. Do not reset output.")
            script = """
$ErrorActionPreference = 'Stop'
function Stop-OwnedTree([int] $ProcessId) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" |
        ForEach-Object { Stop-OwnedTree ([int] $_.ProcessId) }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    }
}
Stop-OwnedTree """ + str(process.pid)
            subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, check=True, timeout=30)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Agent output pipes remain open after tree cleanup. Do not reset output.") from exc
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=300, help="Agent wall-clock deadline, seconds")
    args = parser.parse_args()
    executable = shutil.which("copilot")
    if not executable:
        print("FAIL Copilot CLI not installed. Use VS Code Chat and time the full interaction manually.")
        return 1
    if args.timeout <= 0 or args.timeout > 300:
        parser.error("Use a deadline between 1 and 300 seconds.")
    evidence_root = ROOT / "rehearsal"
    folder = evidence_root / datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    folder.mkdir(parents=True, exist_ok=False)
    reset()
    command = [
        executable, "--agent", "tableau-to-pbi", "--prompt", "Migrate sample/OrthoSales.twb",
        "--trust-folder", "--no-ask-user", "--no-color", "--no-auto-update", "--disable-builtin-mcps",
        "--allow-tool", "shell(python:*)",
        "--allow-tool", "powershell(python:*)",
    ]
    for server in ("computer-navigator", "gmail", "m365", "msx", "msxi", "outbox", "slack", "workiq"):
        command.extend(["--disable-mcp-server", server])
    start = time.perf_counter()
    started_at = datetime.now().astimezone().isoformat()
    timed_out = False
    try:
        result = run_agent(command, args.timeout)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        code = 124
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAIL agent launch/tree cleanup: {exc}. Output left untouched; verify no agent is running before reset.")
        return 1
    elapsed = time.perf_counter() - start
    (folder / "agent.stdout.txt").write_text(stdout, encoding="utf-8")
    (folder / "agent.stderr.txt").write_text(stderr, encoding="utf-8")
    # Agent success text is not evidence; validate the files independently after exit.
    validation = validate()
    report = {
        "interface": "GitHub Copilot CLI custom agent (not VS Code UI)",
        "prompt": "Migrate sample/OrthoSales.twb", "started_at": started_at,
        "elapsed_seconds": round(elapsed, 3), "deadline_seconds": args.timeout,
        "returncode": code, "timed_out": timed_out,
        "within_five_minutes": elapsed < 300,
        "output_validated_independently": validation["ok"],
        "validation": validation,
        "success": code == 0 and not timed_out and elapsed < 300 and validation["ok"],
    }
    report["fallback_restored"] = False
    if not report["success"]:
        reset(fallback=True)
        report["fallback_restored"] = True
    (folder / "timing.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (evidence_root / "timing.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    print(f"{'PASS' if report['success'] else 'FAIL'} actual agent wall clock: {elapsed:.3f}s")
    if report["fallback_restored"]:
        print("RESTORED fallback after the failed rehearsal; this is not agent-generated output.")
    print(f"Evidence: {folder / 'timing.json'}; agent stdout/stderr kept locally, not committed.")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
