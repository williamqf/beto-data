import hashlib
import json
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import URLError
import pymupdf

from src import update_ipva


class IpvaPipelineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 2, tzinfo=timezone.utc)

    def test_builds_versioned_2026_rules_and_national_coverage_without_losing_other_manifest_branches(self):
        previous = {"schemaVersion": 1, "datasetVersion": "fuel-x", "vehicleEfficiency": {"datasetVersion": "pbe-x"}}
        files = {"datasets/fuel/old/BR.json": b"old fuel"}
        built = update_ipva.build_files(previous, files, self.now)
        manifest = json.loads(built["manifest.json"])
        self.assertEqual({"MG", "SP", "PR", "AC", "CE", "ES", "GO", "MT", "PB", "SC"}, set(manifest["ipva"]["years"]["2026"]))
        self.assertEqual(update_ipva.UF_CODES, set(manifest["ipva"]["coverage"]))
        self.assertEqual(7, sum(row["status"] == "AUTO" for row in manifest["ipva"]["coverage"].values()))
        self.assertEqual(3, sum(row["status"] == "AUTO_WITH_USER_INPUT" for row in manifest["ipva"]["coverage"].values()))
        self.assertEqual(11, sum(row["status"] == "PARTIAL" for row in manifest["ipva"]["coverage"].values()))
        self.assertEqual(6, sum(row["status"] == "MANUAL_ONLY" for row in manifest["ipva"]["coverage"].values()))
        self.assertEqual("pbe-x", manifest["vehicleEfficiency"]["datasetVersion"])
        self.assertEqual("fuel-x", manifest["datasetVersion"])
        self.assertEqual("national-passenger-vehicle-20-years-immunity", manifest["ipva"]["commonRules"][0]["id"])
        self.assertEqual("EXEMPT", manifest["ipva"]["commonRules"][0]["effects"][0]["type"])
        for uf, entry in manifest["ipva"]["years"]["2026"].items():
            body = built[entry["path"]]
            self.assertEqual(entry["sha256"], hashlib.sha256(body).hexdigest())
            dataset = json.loads(body)
            self.assertEqual((uf, 2026, 2), (dataset["uf"], dataset["year"], dataset["schemaVersion"]))
            self.assertTrue(dataset["sourceUrl"].startswith("https://"))
            if uf == "SP":
                self.assertEqual([4.0, 3.0], [rule["effects"][0]["value"] for rule in dataset["rules"]])
                self.assertEqual("PASSENGER_CAR", dataset["rules"][0]["conditions"]["all"][0]["value"])
                self.assertEqual(["GASOLINE", "FLEX", "DIESEL"], dataset["rules"][0]["conditions"]["all"][1]["value"])
                self.assertEqual(["ETHANOL", "GNV", "ELECTRIC"], dataset["rules"][1]["conditions"]["all"][1]["value"])
                self.assertEqual(2, manifest["ipva"]["schemaVersion"])
            if uf == "PR":
                gnv = next(rule for rule in dataset["rules"] if rule["id"] == "pr-passenger-gnv")
                self.assertIn({"field": "gnvRegularized", "operator": "EQUALS", "value": "YES"}, gnv["conditions"]["all"])

    def test_validation_blocks_changed_official_source_markers(self):
        config = update_ipva.RULES
        responses = {}
        for row in config.values():
            responses[row["sourceUrl"]] = " ".join(row["markers"])
            if row.get("baseMarkers"):
                responses[row["baseSourceUrl"]] = " ".join(row["baseMarkers"])
        update_ipva.validate_sources(lambda url: responses[url])
        mg_url = config["MG"]["sourceUrl"]
        responses[mg_url] = "conteúdo sem confirmação"
        with self.assertRaisesRegex(ValueError, "Fonte MG mudou"):
            update_ipva.validate_sources(lambda url: responses[url])

    def test_source_connection_failures_name_the_state_and_url(self):
        with self.assertRaisesRegex(RuntimeError, r"Fonte oficial de AC indisponível.*sefaz\.ac\.gov\.br"):
            update_ipva.validate_sources(lambda url: (_ for _ in ()).throw(TimeoutError("fixture timeout")))

    def test_fetch_source_retries_one_transient_timeout(self):
        class Response:
            status = 200
            headers = type("Headers", (), {"get_content_charset": staticmethod(lambda: "utf-8")})()

            def __init__(self, body):
                self.body = body

            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return self.body

        with patch("src.update_ipva.urlopen", side_effect=[URLError(socket.timeout("transient")), Response(b"<p>fonte oficial</p>")]) as open_url:
            with patch("src.update_ipva.time.sleep"):
                self.assertEqual("fonte oficial", update_ipva.fetch_source("https://example.gov.br", timeout=1))
        self.assertEqual(2, open_url.call_count)

    def test_fetch_source_extracts_text_from_official_pdf(self):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Lei 11.007 IPVA 2,5%")
        body = document.tobytes()
        document.close()

        response = type("Response", (), {
            "status": 200,
            "headers": type("Headers", (), {"get_content_charset": staticmethod(lambda: "utf-8")})(),
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
            "read": lambda self: body,
        })()
        with patch("src.update_ipva.urlopen", return_value=response):
            text = update_ipva.fetch_source("https://example.gov.br/law.pdf")
        self.assertIn("Lei 11.007", text)
        self.assertIn("2,5%", text)

    def test_unsupported_ufs_are_explicitly_manual_or_partial_instead_of_receiving_fake_rules(self):
        built = update_ipva.build_files({}, {}, self.now)
        manifest = json.loads(built["manifest.json"])
        self.assertNotIn("RJ", manifest["ipva"]["years"]["2026"])
        self.assertIn("SC", manifest["ipva"]["years"]["2026"])
        self.assertEqual("MANUAL_ONLY", manifest["ipva"]["coverage"]["RJ"]["status"])
        self.assertEqual("AUTO", manifest["ipva"]["coverage"]["SC"]["status"])

    def test_coverage_sources_must_be_official_https(self):
        self.assertEqual(update_ipva.UF_CODES, set(update_ipva.COVERAGE_2026))
        for row in update_ipva.COVERAGE_2026.values():
            self.assertTrue(row["source"].startswith("https://"))
            self.assertTrue(row["baseSource"].startswith("https://"))

    def test_schema_v2_validation_rejects_or_unknown_fields_operators_and_bad_effect_order(self):
        valid = {
            "id": "range-rule", "priority": 10,
            "conditions": {"all": [{"field": "enginePowerHp", "operator": "BETWEEN", "value": [80, 120]}]},
            "effects": [{"type": "BASE_REDUCTION", "value": 0.3}, {"type": "RATE", "value": 4.0}],
        }
        update_ipva.validate_v2_rule(valid)
        invalid_rules = [
            {**valid, "conditions": {"any": []}},
            {**valid, "conditions": {"all": [{"field": "random", "operator": "EQUALS", "value": "x"}]}},
            {**valid, "conditions": {"all": [{"field": "fuelType", "operator": "NOT_IN", "value": ["GNV"]}]}},
            {**valid, "effects": [{"type": "RATE", "value": 4.0}, {"type": "BASE_REDUCTION", "value": 0.3}]},
        ]
        for rule in invalid_rules:
            with self.assertRaises(ValueError):
                update_ipva.validate_v2_rule(rule)

    def test_shared_national_rule_uses_official_constitution_source_and_vehicle_category_guard(self):
        rule = update_ipva.COMMON_RULES[0]
        self.assertIn("planalto.gov.br", rule["sourceUrl"])
        self.assertIn({"field": "vehicleAge", "operator": "GTE", "value": 20}, rule["conditions"]["all"])
        self.assertIn("vehicleCategory", {condition["field"] for condition in rule["conditions"]["all"]})
        update_ipva.validate_v2_rule(rule, "NATIONAL")


if __name__ == "__main__":
    unittest.main()
