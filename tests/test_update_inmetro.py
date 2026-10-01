import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import update_inmetro as pbev

FIXTURES = Path(__file__).parent / "fixtures" / "inmetro"


def rows():
    fixture = json.loads((FIXTURES / "records.json").read_text(encoding="utf-8"))
    output = []
    for r in fixture:
        row = [""] * 28
        for i, field in enumerate(("category", "brand", "model", "version", "engine")):
            row[i] = r[field]
        row[5] = r["propulsion"]; row[6] = r["transmission"]; row[9] = r["fuel"]
        row[17] = r["ethanol"]; row[18] = "9,0" if r["ethanol"] not in {"\\", "-"} else "\\"
        row[19] = r["gasoline"]; row[20] = "12,0" if r["gasoline"] not in {"\\", "-"} else "\\"
        row[23] = r["energy"]; row[24] = r["range"]; row[25] = r["class"]; row[27] = r["conpet"]
        output.append(row)
    # Small fixture expands to a realistic-sized batch while keeping the technical variants above explicit.
    while len(output) < 32:
        clone = list(output[len(output) % 4]); clone[2] = f"MODELO TESTE {len(output)}"; output.append(clone)
    return output


class InmetroPipelineTests(unittest.TestCase):
    def test_discovers_cycle_and_date_from_official_index_markup(self):
        items = pbev.discover_cycles((FIXTURES / "index.html").read_text(encoding="utf-8"))
        self.assertEqual([2021, 2022, 2025, 2026], [x["sourceYear"] for x in items])
        self.assertEqual("2026-08-31", items[-1]["sourceReferenceDate"])
        self.assertEqual("Veículos leves 2021", items[0]["sourceCycle"])
        self.assertTrue(items[-1]["documentUrl"].startswith("https://www.gov.br/inmetro/"))

    def test_discovers_historical_year_only_archives(self):
        html = '<h2>Veículos leves 2010</h2><a href="/inmetro/arquivo/2010/@@download/file">2010</a><h2>Veículos leves 2026 - 18º Ciclo</h2><a href="/inmetro/arquivo/2026/@@download/file">2026</a>'
        items = pbev.discover_cycles(html)
        self.assertEqual([2010, 2026], [item["sourceYear"] for item in items])

    def test_discovery_fails_closed_on_missing_current_cycle_or_wrong_domain(self):
        with self.assertRaises(ValueError): pbev.discover_cycles('<h2>Veículos leves 2025 - 17º Ciclo</h2><a href="x.pdf">x</a>')
        with self.assertRaises(ValueError): pbev.discover_cycles('<h2>Veículos leves 2026 - 18º Ciclo</h2><a href="https://example.org/x.pdf">x</a>')

    def test_normalizes_flex_variants_without_model_year_or_converting_other_propulsion(self):
        records = pbev.normalize_rows(rows(), 2024, "Veículos leves 2024 - 16º Ciclo", "2024-01-01", "https://www.gov.br/inmetro/x.pdf")
        flex = records[0]
        self.assertEqual(7.4, flex["fuels"]["ETHANOL"]["urban"])
        self.assertEqual(10.5, flex["fuels"]["GASOLINE"]["urban"])
        self.assertNotIn("modelYear", flex)
        self.assertEqual(280, records[2]["electricRangeKm"])
        self.assertEqual({}, records[2]["fuels"])
        # A hybrid may retain its directly published gasoline figure; the Android suggestion policy gates it out.
        self.assertEqual("Híbrido", records[3]["propulsionType"])

    def test_2021_technical_column_positions_are_not_shifted_into_transmission(self):
        row = [""] * 23
        row[:10] = ["Compacto", "FIAT", "ARGO", "DRIVE", "1.3-8V", "M-5", "S", "E", "Combustão", "F"]
        row[16:19] = ["8,8", "10,4", "12,8"]
        row[19:21] = ["14,7", "1,57"]
        batch = [list(row) for _ in range(32)]
        for index, sample in enumerate(batch): sample[2] = f"ARGO {index}"
        record = pbev.normalize_rows(batch, 2021, "Veículos leves 2021", None, "https://www.gov.br/inmetro/x.pdf")[0]
        self.assertEqual("Combustão", record["propulsionType"])
        self.assertEqual("M-5", record["transmission"])
        self.assertEqual("S", record["airConditioning"])
        self.assertEqual("E", record["steering"])

    def test_2026_official_fuel_labels_keep_ethanol_separate(self):
        row = [""] * 33
        row[:10] = ["Compacto", "MARCA TESTE", "MODELO E100", "1.0", "1.0", "Combustão", "M-5", "S", "E", "E100"]
        row[18:21] = ["7,4", "10,0", "8,5"]
        row[21:24] = ["\\", "\\", "\\"]
        row[28] = "1,20"
        batch = []
        for index in range(32):
            sample = list(row); sample[2] = f"MODELO E100 {index}"; batch.append(sample)
        record = pbev.normalize_rows(batch, 2026, "Veículos leves 2026 - 18º Ciclo", None, "https://www.gov.br/inmetro/x.pdf")[0]
        self.assertEqual(7.4, record["fuels"]["ETHANOL"]["urban"])
        self.assertNotIn("GASOLINE", record["fuels"])

    def test_unknown_codes_and_invalid_numbers_fail_closed(self):
        fixture = rows()
        fixture[0][9] = "X"
        with self.assertRaisesRegex(ValueError, "desconhecido"): pbev.normalize_rows(fixture, 2024, "ciclo", None, "https://www.gov.br/inmetro/x.pdf")
        fixture = rows(); fixture[0][19] = "9,9 km/L"
        with self.assertRaisesRegex(ValueError, "não reconhecido"): pbev.normalize_rows(fixture, 2024, "ciclo", None, "https://www.gov.br/inmetro/x.pdf")

    def test_stable_ids_and_catalog_checksums(self):
        records = pbev.normalize_rows(rows(), 2024, "Veículos leves 2024 - 16º Ciclo", None, "https://www.gov.br/inmetro/x.pdf")
        again = pbev.normalize_rows(rows(), 2024, "Veículos leves 2024 - 16º Ciclo", None, "https://www.gov.br/inmetro/x.pdf")
        self.assertEqual([r["id"] for r in records], [r["id"] for r in again])
        historic_rows = []
        for index in range(32):
            row = [""] * 23
            row[:9] = ["COMPACTO", "FIAT", "ARGO" if index == 0 else f"ARGO {index}", "DRIVE GSR", "1.3-8V", "MTA-5", "S", "E", "F"]
            row[15:19] = ["8,9", "10,0", "12,7", "14,4"]
            row[19:23] = ["1,55", "A", "B", "SIM"]
            historic_rows.append(row)
        historic = pbev.normalize_rows(historic_rows, 2019, "Veículos leves 2019", None, "https://www.gov.br/inmetro/x2019.pdf")
        files = pbev.build_files([
            {"sourceYear":2024,"sourceCycle":"Veículos leves 2024 - 16º Ciclo","sourceReferenceDate":None,"documentUrl":"https://www.gov.br/inmetro/x.pdf","records":records},
            {"sourceYear":2019,"sourceCycle":"Veículos leves 2019","sourceReferenceDate":None,"documentUrl":"https://www.gov.br/inmetro/x2019.pdf","records":historic},
        ], "2026-09-29T00:00:00Z")
        meta = json.loads(files["vehicleEfficiency"])
        self.assertEqual(hashlib.sha256(files[meta["catalog"]["path"]]).hexdigest(), meta["catalog"]["sha256"])
        catalog = json.loads(files[meta["catalog"]["path"]])["records"]
        gsr = next(item for item in catalog if item["sourceYear"] == 2019 and item["brand"] == "FIAT" and item["model"] == "ARGO" and item["version"] == "DRIVE GSR")
        self.assertEqual((2019, "DRIVE GSR", "1.3-8V", "MTA-5"),
            (gsr["sourceYear"], gsr["version"], gsr["engine"], gsr["transmission"]))
        self.assertEqual(12.7, gsr["fuels"]["GASOLINE"]["urban"])
        self.assertEqual(8.9, gsr["fuels"]["ETHANOL"]["urban"])

    def test_historical_profiles_preserve_column_order_and_fuel_semantics(self):
        cases = [
            (2010, {0: "FIAT", 1: "PALIO", 2: "ELX", 3: "1.4 - 8V", 4: "M-5", 5: "S", 6: "H", 7: "F", 8: "8,9", 9: "12,7", 10: "10,0", 11: "14,4", 12: "A"}, "ELX", "1.4 - 8V"),
            (2013, {0: "COMPACTO", 1: "FIAT", 2: "ARGO", 3: "1.3-8V", 4: "DRIVE GSR", 5: "MTA-5", 6: "S", 7: "E", 8: "F", 15: "8,9", 16: "10,0", 17: "12,7", 18: "14,4", 19: "1,55", 20: "A", 22: "SIM"}, "DRIVE GSR", "1.3-8V"),
            (2017, {0: "COMPACTO", 1: "FIAT", 2: "ARGO", 3: "DRIVE GSR", 4: "1.3-8V", 5: "MTA-5", 6: "S", 7: "E", 8: "F", 15: "8,9", 16: "10,0", 17: "12,7", 18: "14,4", 19: "1,55", 20: "A", 22: "SIM"}, "DRIVE GSR", "1.3-8V"),
            (2020, {0: "COMPACTO", 1: "FIAT", 2: "ARGO", 3: "1.3-8V", 4: "DRIVE GSR", 5: "MTA-5", 6: "S", 7: "E", 8: "F", 15: "8,9", 16: "10,0", 17: "12,7", 18: "14,4", 19: "1,55", 20: "A", 22: "SIM"}, "DRIVE GSR", "1.3-8V"),
        ]
        for year, values, expected_version, expected_engine in cases:
            with self.subTest(year=year):
                width = pbev.PROFILES[year]["columns"]
                batch = []
                for index in range(32):
                    row = [""] * width
                    for column, value in values.items(): row[column] = value
                    row[pbev.PROFILES[year]["model"]] += f" {index}"
                    batch.append(row)
                record = pbev.normalize_rows(batch, year, f"Veículos leves {year}", None, "https://www.gov.br/inmetro/x.pdf")[0]
                self.assertEqual(expected_version, record["version"])
                self.assertEqual(expected_engine, record["engine"])
                self.assertEqual("Combustão", record["propulsionType"])
                self.assertEqual(12.7, record["fuels"]["GASOLINE"]["urban"])
                self.assertEqual(8.9, record["fuels"]["ETHANOL"]["urban"])
        # The 2010 compact table calls ethanol fuel "A"; 2012 uses "E".
        for year, code in ((2010, "A"), (2012, "E")):
            profile = pbev.PROFILES[year]; batch = []
            for index in range(32):
                row = [""] * profile["columns"]
                row[0:8] = ["FIAT", f"UNO {index}", "MILLE", "1.0-8V", "M-5", "N", "M", code]
                row[8:13] = ["8,9", "12,7", "10,7", "15,6", "A"]
                batch.append(row)
            record = pbev.normalize_rows(batch, year, f"Veículos leves {year}", None, "https://www.gov.br/inmetro/x.pdf")[0]
            self.assertEqual(8.9, record["fuels"]["ETHANOL"]["urban"])
            self.assertNotIn("GASOLINE", record["fuels"])


if __name__ == "__main__": unittest.main()
