import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import reset as reset_module
from tools.migrate import MODEL, ROOT, migrate, write_json
from tools.reset import digest, rebind_data_path, safe_path, verify_snapshot
from tools.validate import model_checks, read_rows, report_checks, validate


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.output, self.mapping = self.folder / "output", self.folder / "mapping.md"
        self.source = ROOT / "sample" / "data" / "ortho_sales.csv"
        migrate(ROOT / "sample" / "OrthoSales.twb", self.output, self.mapping)

    def test_end_to_end_offline_checks(self):
        result = validate(self.output, self.mapping)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(len(result["checks"]), 7)
        self.assertEqual(result["metrics"]["rows"], 2000)
        self.assertEqual(result["metrics"]["yoy_contexts"], 600)
        self.assertEqual(result["metrics"]["top_n_contexts"], 20)
        self.assertIn("Power Query and DAX engine execution", result["not_verified"])

    def test_mutated_dax_fails(self):
        path = self.output / MODEL / "definition" / "tables" / "Sales.tmdl"
        path.write_text(path.read_text().replace("DIVIDE([Total Revenue], [Total Units])", "SUM('Sales'[revenue])"),
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Average Selling Price"):
            model_checks(self.output, self.source)

    def test_wrong_csv_path_fails(self):
        rebind_data_path(self.output, ROOT / "sample" / "data" / "missing.csv")
        with self.assertRaisesRegex(ValueError, "CSV path"):
            model_checks(self.output, self.source)

    def test_broken_relationship_fails(self):
        path = self.output / MODEL / "definition" / "relationships.tmdl"
        path.write_text(path.read_text().replace("Calendar.Date", "Calendar.Month"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Relationship"):
            model_checks(self.output, self.source)

    def test_wrong_visual_binding_fails(self):
        symbols = model_checks(self.output, self.source)
        path = next(self.output.rglob("MonthlyUnits\\visual.json"))
        document = json.loads(path.read_text())
        document["visual"]["query"]["queryState"]["Y"]["projections"][0]["field"]["Measure"]["Property"] = "Total Revenue"
        write_json(path, document)
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            report_checks(self.output, symbols)

    def test_missing_output_fails_explicitly(self):
        result = validate(self.folder / "missing", self.mapping)
        self.assertFalse(result["ok"])
        self.assertTrue(any(c["status"] == "FAIL" for c in result["checks"]))

    def test_numeric_top_n_range_slicer_rejected(self):
        symbols = model_checks(self.output, self.source)
        path = next(self.output.rglob("TopN\\visual.json"))
        document = json.loads(path.read_text())
        document["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"] = "'Between'"
        write_json(path, document)
        with self.assertRaisesRegex(ValueError, "dropdown"):
            report_checks(self.output, symbols)

    def test_reject_unsafe_reset_path(self):
        with self.assertRaisesRegex(ValueError, "unsafe"):
            safe_path(ROOT)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            safe_path(ROOT.parent)

    def test_corrupt_fallback_does_not_remove_existing_output(self):
        snapshot = self.folder / "prebuilt"
        shutil.copytree(ROOT / "prebuilt", snapshot)
        (snapshot / "output" / "OrthoSales.pbip").write_text("corrupt", encoding="utf-8")
        with patch.object(reset_module, "PREBUILT", snapshot), patch.object(reset_module, "OUTPUT", self.output), (
            patch.object(reset_module, "MAPPING", self.mapping)
        ):
            with self.assertRaisesRegex(ValueError, "integrity"):
                reset_module.reset(fallback=True)
        self.assertTrue((self.output / "OrthoSales.pbip").is_file())
        self.assertTrue(self.mapping.is_file())

    def test_fallback_manifest_and_path_rebinding(self):
        verify_snapshot()
        rebind_data_path(self.output, self.source)
        model_checks(self.output, self.source)
        snapshot = json.loads((ROOT / "prebuilt" / "manifest.json").read_text())
        self.assertFalse(snapshot["runtime_verified"])

    def test_invalid_csv_currency_rejected(self):
        path = self.folder / "bad.csv"
        path.write_text("order_date,region,territory,product_line,sku,units,revenue\n"
                        "2024-01-01,East,Atlantic,Hips,HIP-001,1,1.001\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact cents"):
            read_rows(path)


if __name__ == "__main__":
    unittest.main()
