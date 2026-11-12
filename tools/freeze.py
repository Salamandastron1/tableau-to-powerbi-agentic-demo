"""Snapshot offline-validated output as the presenter fallback."""
import json
import shutil
import sys

try:
    from .migrate import ROOT
    from .reset import MAPPING, OUTPUT, PREBUILT, digest, safe_path
    from .validate import validate
except ImportError:
    from migrate import ROOT
    from reset import MAPPING, OUTPUT, PREBUILT, digest, safe_path
    from validate import validate


def main():
    report = validate()
    if not report["ok"]:
        print(json.dumps(report, indent=2))
        print("FAIL refusing to freeze invalid output")
        return 1
    safe_path(PREBUILT)
    if PREBUILT.exists():
        print("FAIL prebuilt already exists. Review it before explicitly removing/replacing that directory.")
        return 1
    shutil.copytree(OUTPUT, PREBUILT / "output")
    (PREBUILT / "docs").mkdir()
    shutil.copy2(MAPPING, PREBUILT / "docs" / "mapping.md")
    # Keep the committed fallback machine-neutral; reset.py binds the current checkout.
    expressions = PREBUILT / "output" / "OrthoSales.SemanticModel" / "definition" / "expressions.tmdl"
    lines = expressions.read_text(encoding="utf-8").splitlines()
    lines[0] = 'expression DataFilePath = "SET_BY_RESET_FALLBACK" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    expressions.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "verification": "Python reference arithmetic, emitted-expression and structural checks only",
        "runtime_verified": False,
        "files": {str(p.relative_to(PREBUILT)): digest(p) for p in sorted(PREBUILT.rglob("*")) if p.is_file()},
    }
    (PREBUILT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS froze {len(manifest['files'])} fallback files; Desktop execution is still unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
