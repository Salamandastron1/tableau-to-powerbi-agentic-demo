import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.inspect_twb import inspect, summary
from tools.make_data import ROOT, generate


class SampleTests(unittest.TestCase):
    def test_seeded_data_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a.csv", Path(directory) / "b.csv"
            generate(a)
            generate(b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(a.read_bytes(), (ROOT / "sample" / "data" / "ortho_sales.csv").read_bytes())
            with a.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2000)
            self.assertEqual(len({r["order_date"][:7] for r in rows}), 24)
            self.assertEqual(len({(r["order_date"][:7], r["product_line"]) for r in rows}), 120)
            self.assertEqual(len({r["region"] for r in rows}), 4)
            self.assertEqual(len({(r["order_date"][:7], r["product_line"], r["region"]) for r in rows}), 480)

    def test_inventory(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        counts = summary(item)
        self.assertEqual(counts["datasources"], 1)
        self.assertEqual(counts["worksheets"], 3)
        self.assertEqual(counts["calculations"], 4)
        self.assertEqual(counts["parameters"], 1)
        self.assertEqual(counts["dashboards"], 1)
        self.assertEqual(counts["table_calculations"], 1)
        self.assertEqual(item["parameters"][0]["value"], "10")

    def test_bad_workbook_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.twb"
            path.write_text("<not-a-workbook />", encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect(path)

    def test_batch_csv_keeps_valid_workbooks_and_reports_parse_errors(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder = Path(directory)
            source = (ROOT / "sample" / "OrthoSales.twb").read_bytes()
            (folder / "a.twb").write_bytes(source)
            (folder / "b.twb").write_bytes(source)
            (folder / "broken.twb").write_text("<workbook>", encoding="utf-8")
            summary_path = folder / "inventory.csv"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "inspect_twb.py"), str(folder),
                 "--csv", str(summary_path), "--json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 1)
            inventory = json.loads(result.stdout)
            self.assertEqual(len(inventory["workbooks"]), 2)
            self.assertEqual(len(inventory["errors"]), 1)
            self.assertIn("FAIL", result.stderr)
            with summary_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["complexity_score"] for row in rows}, {"18"})
            self.assertEqual({row["complexity_bucket"] for row in rows}, {"medium"})


if __name__ == "__main__":
    unittest.main()
