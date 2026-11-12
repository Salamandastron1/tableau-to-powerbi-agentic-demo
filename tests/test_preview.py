import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.migrate import ROOT, migrate
from tools.preview import build
from tools.validate import validate


class PreviewTests(unittest.TestCase):
    def test_baseline_and_stacked_change_render_identically_on_both_sides(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder = Path(directory)
            output, mapping, page = folder / "output", folder / "mapping.md", folder / "index.html"
            migrate(ROOT / "sample" / "OrthoSales.twb", output, mapping)
            result = build(output, page)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["changes"], 0)
            text = page.read_text(encoding="utf-8")
            self.assertIn("preview renderer, not Power BI", text)
            self.assertNotIn("https://", text.split("<script>")[1])
            migrate(ROOT / "sample" / "changes" / "OrthoSales.twb", output, mapping, replace=True)
            self.assertTrue(validate(output, mapping)["ok"])
            visual = json.loads((output / "OrthoSales.Report" / "definition" / "pages" / "Overview" /
                                 "visuals" / "RevenueByRegion" / "visual.json").read_text())
            self.assertEqual(visual["visual"]["visualType"], "barChart")
            self.assertIn("Series", visual["visual"]["query"]["queryState"])
            result = build(output, page)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["changes"], 2)

    def test_tampered_measure_breaks_renderer_parity(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder = Path(directory)
            output, mapping = folder / "output", folder / "mapping.md"
            migrate(ROOT / "sample" / "OrthoSales.twb", output, mapping)
            sales = output / "OrthoSales.SemanticModel" / "definition" / "tables" / "Sales.tmdl"
            sales.write_text(sales.read_text().replace("SUM('Sales'[revenue])", "SUM('Sales'[units])"),
                             encoding="utf-8")
            result = build(output, folder / "index.html")
            self.assertFalse(result["ok"])
            self.assertFalse(result["same"]["bar"])


if __name__ == "__main__":
    unittest.main()
