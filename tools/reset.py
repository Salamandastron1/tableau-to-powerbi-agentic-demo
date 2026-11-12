"""Reset only generated demo artifacts, or restore the checked prebuilt fallback."""
import argparse
import hashlib
import json
import shutil
import stat
import sys
import time
from pathlib import Path

try:
    from .migrate import MODEL, ROOT, path_expression
except ImportError:
    from migrate import MODEL, ROOT, path_expression

OUTPUT = ROOT / "output"
MAPPING = ROOT / "docs" / "mapping.md"
PREBUILT = ROOT / "prebuilt"
PREVIEW_DIR = ROOT / "preview"


def safe_path(path: Path):
    require_inside = path.absolute().is_relative_to(ROOT) and path.absolute() != ROOT
    if not require_inside or path.resolve() != path.absolute():
        raise ValueError(f"Refusing unsafe cleanup/copy path: {path}")
    candidates = [path] + (list(path.rglob("*")) if path.is_dir() else [])
    for candidate in candidates:
        if candidate.exists() or candidate.is_symlink():
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
            if candidate.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise ValueError(f"Refusing reparse point/symlink in generated artifacts: {candidate}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_snapshot():
    safe_path(PREBUILT)
    manifest = json.loads((PREBUILT / "manifest.json").read_text(encoding="utf-8"))
    expected = manifest["files"]
    actual = {str(p.relative_to(PREBUILT)) for p in PREBUILT.rglob("*")
              if p.is_file() and p != PREBUILT / "manifest.json"}
    if actual != set(expected):
        raise ValueError("Fallback file set differs from its manifest. Do not use a partial snapshot.")
    for name, checksum in expected.items():
        path = PREBUILT / name
        if not path.resolve().is_relative_to(PREBUILT) or digest(path) != checksum:
            raise ValueError(f"Fallback integrity failed: {name}")
    if manifest.get("runtime_verified") is not False:
        raise ValueError("Fallback verification boundary is missing.")


def rebind_data_path(output: Path, source: Path):
    path = output / MODEL / "definition" / "expressions.tmdl"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith("expression DataFilePath = ")]
    if len(matches) != 1:
        raise ValueError("Fallback requires exactly one DataFilePath expression.")
    lines[matches[0]] = path_expression(source).strip()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def reset(fallback=False):
    safe_path(OUTPUT)
    safe_path(MAPPING)
    if fallback:
        verify_snapshot()
        # Check input compatibility before removing a currently working output.
        try:
            from .inspect_twb import inspect
            from .migrate import check_profile, source_file, text_hash
        except ImportError:
            from inspect_twb import inspect
            from migrate import check_profile, source_file, text_hash
        metadata = json.loads((PREBUILT / "output" / "migration.json").read_text())
        workbook = (ROOT / metadata["workbook"]).resolve()
        if not workbook.is_relative_to(ROOT):
            raise ValueError("Fallback workbook must be in this repository.")
        item = inspect(workbook)
        check_profile(item)
        source = source_file(workbook, item)
        if text_hash(workbook) != metadata["workbook_sha256"] or text_hash(source) != metadata["source_sha256"]:
            raise ValueError("Fallback no longer matches the source workbook/data. Rebuild and freeze it.")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    if MAPPING.exists():
        MAPPING.unlink()
    safe_path(PREVIEW_DIR)
    if PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)
    if fallback:
        shutil.copytree(PREBUILT / "output", OUTPUT)
        MAPPING.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PREBUILT / "docs" / "mapping.md", MAPPING)
        rebind_data_path(OUTPUT, source)
        try:
            from .validate import validate
        except ImportError:
            from validate import validate
        report = validate()
        if not report["ok"]:
            failures = [r for r in report["checks"] if r["status"] == "FAIL"]
            raise ValueError(f"Restored fallback failed validation: {failures}")
        try:
            from .preview import build
        except ImportError:
            from preview import build
        preview = build(OUTPUT, PREVIEW_DIR / "index.html")
        if not preview["ok"]:
            raise ValueError(f"Fallback restored and valid, but preview parity failed: {preview}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["before", "fallback"], default="before")
    args = parser.parse_args()
    start = time.perf_counter()
    try:
        reset(args.mode == "fallback")
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL reset: {exc}")
        return 1
    print(f"PASS {'Restored and offline-validated prebuilt project; preview rebuilt (preview/index.html)' if args.mode == 'fallback' else 'Before state: output, generated mapping and preview removed'}")
    print(f"Reset elapsed: {time.perf_counter() - start:.3f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
