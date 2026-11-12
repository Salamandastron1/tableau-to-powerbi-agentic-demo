import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.inspect_twb import inspect
from tools.migrate import ROOT, check_profile, migrate
from tools.schema_check import SchemaError, check_document


class MigrationTests(unittest.TestCase):
    def test_project_emission(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output, mapping = Path(directory) / "output", Path(directory) / "mapping.md"
            manifest = migrate(ROOT / "sample" / "OrthoSales.twb", output, mapping)
            self.assertEqual(len(manifest["calculated_fields"]), 4)
            self.assertTrue(mapping.is_file())
            for path in output.rglob("*"):
                if path.suffix in (".pbip", ".pbir", ".pbism", ".json"):
                    document = json.loads(path.read_text(encoding="utf-8"))
                    if "$schema" in document:
                        check_document(document)
            visuals = list(output.rglob("visual.json"))
            self.assertEqual(len(visuals), 5)
            self.assertEqual(len(list(output.rglob("*.tmdl"))), 7)
            with self.assertRaisesRegex(ValueError, "already exists"):
                migrate(ROOT / "sample" / "OrthoSales.twb", output, mapping)

    def test_changed_formula_is_not_silently_translated(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        altered = copy.deepcopy(item)
        altered["calculations"][0]["formula"] = "AVG([revenue])"
        with self.assertRaisesRegex(ValueError, "Unsupported calculated"):
            check_profile(altered)

    def test_changed_shelf_is_not_silently_translated(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        item["worksheets"][0]["rows"] = "[territory]"
        with self.assertRaisesRegex(ValueError, "Unsupported shelves"):
            check_profile(item)

    def test_missing_region_filter_rejected(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        item["worksheets"][0]["filters"] = []
        with self.assertRaisesRegex(ValueError, "Region.*filter"):
            check_profile(item)

    def test_region_must_run_before_top_n(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        for sheet in item["worksheets"]:
            for filt in sheet["filters"]:
                filt["definition"] = filt["definition"].replace('context="true"', 'context="false"')
        with self.assertRaisesRegex(ValueError, "Region context filter"):
            check_profile(item)

    def test_extra_top_n_condition_rejected(self):
        item = inspect(ROOT / "sample" / "OrthoSales.twb")
        filt = item["worksheets"][2]["filters"][1]
        filt["definition"] = filt["definition"].replace('direction="DESC"', 'direction="ASC"')
        with self.assertRaisesRegex(ValueError, "Top N filter"):
            check_profile(item)

    def test_schema_rejects_bad_visual(self):
        from tools.fetch_schemas import SCHEMAS
        document = {"$schema": SCHEMAS["visual"], "name": "Bad", "position": {"x": 1}}
        with self.assertRaises(SchemaError):
            check_document(document)

    def test_schema_rejects_unknown_property(self):
        from tools.fetch_schemas import SCHEMAS
        with self.assertRaises(SchemaError):
            check_document({"$schema": SCHEMAS["pbip"], "version": "1.0", "artifacts": [], "invented": 1})


if __name__ == "__main__":
    unittest.main()
