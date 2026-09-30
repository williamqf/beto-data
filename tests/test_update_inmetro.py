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
        files = pbev.build_files([{"sourceYear":2024,"sourceCycle":"Veículos leves 2024 - 16º Ciclo","sourceReferenceDate":None,"documentUrl":"https://www.gov.br/inmetro/x.pdf","records":records}], "2026-09-29T00:00:00Z")
        meta = json.loads(files["vehicleEfficiency"])
        self.assertEqual(hashlib.sha256(files[meta["catalog"]["path"]]).hexdigest(), meta["catalog"]["sha256"])


if __name__ == "__main__": unittest.main()
