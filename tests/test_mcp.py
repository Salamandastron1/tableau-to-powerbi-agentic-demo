import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.migrate import ROOT, migrate


class Client:
    def __init__(self, script, env=None):
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / script)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", env={**os.environ, **(env or {})})
        self.next = 0
        init = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "1"}})
        assert "tools" in init["capabilities"]
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")

    def request(self, method, params=None):
        self.next += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        assert reply["id"] == self.next, reply
        return reply["result"]

    def call(self, name, arguments=None):
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        text = result["content"][0]["text"]
        return result["isError"], (json.loads(text) if text[:1] in "[{" else text)

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


class McpTests(unittest.TestCase):
    def test_method_b_migrates_changed_worksheet_through_mcp_tools_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory) / "output"
            migrate(ROOT / "sample" / "OrthoSales.twb", output, Path(directory) / "mapping.md")
            tableau = Client("tableau_mcp.py")
            pbip = Client("pbip_mcp.py", {"PBIP_MCP_OUTPUT": str(output)})
            try:
                names = {t["name"] for t in tableau.request("tools/list")["tools"]}
                self.assertEqual(names, {"list_workbooks", "get_workbook_inventory", "get_calculated_fields",
                                         "get_worksheet"})
                error, books = tableau.call("list_workbooks")
                self.assertIn("sample/changes/OrthoSales.twb", books)
                error, sheet = tableau.call("get_worksheet", {"path": "sample/changes/OrthoSales.twb",
                                                              "name": "Revenue by Region"})
                self.assertFalse(error)
                self.assertEqual(sheet["encodings"][0]["channel"], "color")
                error, _ = tableau.call("get_worksheet", {"path": "../TASK.md", "name": "x"})
                self.assertTrue(error)
                error, visual = pbip.call("get_visual", {"name": "RevenueByRegion"})
                visual["visual"]["visualType"] = "barChart"
                visual["visual"]["query"]["queryState"]["Series"] = {"projections": [{
                    "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "product_line"}},
                    "queryRef": "Sales.product_line", "nativeQueryRef": "product_line"}]}
                self.assertFalse(pbip.call("set_source_workbook", {"path": "sample/changes/OrthoSales.twb"})[0])
                error, invalid = pbip.call("write_visual", {"name": "RevenueByRegion", "visual": {"bogus": 1}})
                self.assertTrue(error)
                error, written = pbip.call("write_visual", {"name": "RevenueByRegion", "visual": visual})
                self.assertFalse(error, written)
                error, escape = pbip.call("write_visual", {"name": "..", "visual": visual})
                self.assertTrue(error)
                error, report = pbip.call("validate")
                self.assertTrue(report["ok"], report)
                error, measure = pbip.call("write_measure", {"table": "Sales", "name": "Total Units",
                                                             "expression": "SUM('Sales'[units])", "format_string": "#,##0"})
                self.assertEqual(measure["action"], "replaced")
                self.assertTrue(pbip.call("validate")[1]["ok"])
            finally:
                tableau.close()
                pbip.close()


if __name__ == "__main__":
    unittest.main()
