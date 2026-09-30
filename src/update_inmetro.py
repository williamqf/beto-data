#!/usr/bin/env python3
"""Build a conservative, searchable PBE Veicular dataset from official INMETRO tables."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import pymupdf

SOURCE_INDEX = "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/veiculos-automotivos-pbe-veicular"
SOURCE_NAME = "INMETRO — Programa Brasileiro de Etiquetagem Veicular (PBE Veicular)"
ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SCHEMA_VERSION = 1
PROFILES = {
    2021: {"columns": 23, "header_rows": 4, "propulsion": 8, "fuel": 9, "ethanol_urban": 16, "gasoline_urban": 18, "energy": 20, "range": None, "class": 21, "conpet": None},
    2022: {"columns": 24, "header_rows": 3, "propulsion": 5, "fuel": 9, "ethanol_urban": 16, "gasoline_urban": 18, "energy": 20, "range": None, "class": 21, "conpet": 23},
    2023: {"columns": 28, "header_rows": 4, "propulsion": 5, "fuel": 9, "ethanol_urban": 17, "gasoline_urban": 19, "energy": 23, "range": 24, "class": 25, "conpet": 27},
    2024: {"columns": 28, "header_rows": 4, "propulsion": 5, "fuel": 9, "ethanol_urban": 17, "gasoline_urban": 19, "energy": 23, "range": 24, "class": 25, "conpet": 27},
    2025: {"columns": 28, "header_rows": 4, "propulsion": 5, "fuel": 9, "ethanol_urban": 17, "gasoline_urban": 19, "energy": 23, "range": 24, "class": 25, "conpet": 27},
    2026: {"columns": 33, "header_rows": 1, "propulsion": 5, "fuel": 9, "ethanol_urban": 18, "gasoline_urban": 21, "energy": 28, "range": 29, "class": 30, "conpet": 32},
}


def text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def key(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", value.upper()) if unicodedata.category(c) != "Mn").split())


def header_key(value: str) -> str:
    # Embedded PDF fonts can map the tilde in a header to U+FFFD; only use this on known header labels.
    return key(value).replace("�", "A").strip(":")


class IndexParser(HTMLParser):
    """Tie each official PDF link to its enclosing cycle heading and update date."""
    def __init__(self):
        super().__init__(); self.cycles = []; self.heading = ""; self.capture_heading = False; self.capture_date = False; self.current_date = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag in {"h2", "h3"} and ("headline" in classes or tag == "h2"):
            self.capture_heading = True; self.heading = ""; self.current_date = ""
        if tag == "span" and "value" in classes:
            self.capture_date = True
        if tag == "a" and attrs.get("href"):
            href = attrs["href"]
            if "@@download/file" in href or href.lower().endswith(".pdf"):
                self.cycles.append({"sourceCycle": self.heading.strip(), "sourceReferenceDate": self.current_date.strip(), "url": href})

    def handle_endtag(self, tag):
        if tag in {"h2", "h3"}: self.capture_heading = False
        if tag == "span": self.capture_date = False

    def handle_data(self, data):
        if self.capture_heading: self.heading += data
        if self.capture_date: self.current_date += data


def discover_cycles(html: str, base_url: str = SOURCE_INDEX, years: set[int] | None = None) -> list[dict]:
    parser = IndexParser(); parser.feed(html)
    results = []
    for item in parser.cycles:
        match = re.search(r"(20\d{2}).*?(\d{1,2})[º°]?(?:\s*ciclo)?", item["sourceCycle"], re.I)
        year_match = re.search(r"20\d{2}", item["sourceCycle"])
        if not year_match: continue
        year = int(year_match.group())
        if year > max(PROFILES): raise ValueError(f"Novo ciclo PBEV {year} encontrado, mas o parser ainda não foi homologado para este formato.")
        # The official index labels 2021/2022 without a cycle number; retain its exact title.
        if not re.search(r"\bciclo\b", item["sourceCycle"], re.I) and year not in {2021, 2022}: continue
        if years and year not in years: continue
        if year not in PROFILES: continue
        cycle = int(match.group(2)) if match else None
        href = urljoin(base_url, item["url"])
        if not href.startswith("https://www.gov.br/inmetro/"): raise ValueError("URL de tabela fora do domínio oficial INMETRO.")
        date_match = re.search(r"(\d{2})/(\d{2})/(\d{4})", item["sourceReferenceDate"])
        reference_date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}" if date_match else None
        results.append({"sourceYear": year, "sourceCycle": item["sourceCycle"], "cycleNumber": cycle,
                        "sourceReferenceDate": reference_date, "documentUrl": href})
    by_year = {}
    for item in results:
        if item["sourceYear"] in by_year: raise ValueError(f"Mais de uma tabela PBE Veicular listada para {item['sourceYear']}.")
        by_year[item["sourceYear"]] = item
    if not by_year: raise ValueError("Nenhuma tabela oficial reconhecida para ciclos suportados.")
    if max(by_year) < max(PROFILES): raise ValueError("Índice oficial não contém o ciclo suportado mais recente; falha fechada.")
    return [by_year[y] for y in sorted(by_year)]


def parse_number(value: object, *, upper: float = 1000) -> float | None:
    raw = text(value).replace("−", "-")
    # Some official PDF text cells prepend the unit to a numeric value; accept only this exact known unit.
    unit_value = re.fullmatch(r"\(?\s*km\s*/\s*l\s*\)?\s+(\d+(?:[,.]\d+)?)", raw, re.I)
    if unit_value: raw = unit_value.group(1)
    if not raw or raw in {"\\", "-", "ND", "N.D.", "N/A", "NA"}: return None
    if not re.fullmatch(r"\d+(?:[,.]\d+)?", raw): raise ValueError(f"Número PBEV não reconhecido: {raw!r}")
    value = float(raw.replace(",", "."))
    if value < 0 or value > upper: raise ValueError(f"Número PBEV fora da faixa: {value}")
    return value


def record_id(record: dict) -> str:
    identity = json.dumps({field: record.get(field) for field in ("sourceYear", "sourceCycle", "category", "brand", "model", "version", "engine", "transmission", "propulsionType", "airConditioning", "steering", "officialFuelCode", "fuels", "energyConsumptionMJPerKm", "electricRangeKm", "efficiencyClass", "conpetSeal")}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "pbev-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _cells_for_row(row: list, count: int, first_header_row: bool = False) -> list[list[str]]:
    cells = []
    for value in row:
        lines = [text(v) for v in str(value or "").splitlines()]
        lines = [line for line in lines if line]
        # The 2026 PDF sometimes exposes an overlapped glyph layer as a fake line.
        # Drop only unmistakably corrupt lines; ordinary multiword labels remain intact.
        def artifact(line: str) -> bool:
            single_character_tokens = sum(len(token) == 1 and token.isalnum() for token in line.split())
            return "\ufffd" in line or bool(re.search(r"(.)\1{4,}", line)) or single_character_tokens >= 7
        lines = [line for line in lines if not artifact(line)]
        if first_header_row and lines:
            # On the 2026 first data row, the PDF extractor joins the column label and one vehicle.
            lines = lines[-1:]
        cells.append(lines)
    cells += [[] for _ in range(max(0, count - len(cells)))]
    return cells[:count]


def _iter_raw_rows(pdf, year: int):
    profile = PROFILES[year]
    found_profile = False
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if not table or len(table[0]) != profile["columns"]: continue
            found_profile = True
            for row_index, row in enumerate(table):
                if year == 2026 and row_index == 0: continue
                if year == 2026:
                    cells = _cells_for_row(row, profile["columns"], first_header_row=(row_index == 1 and "\n" in str(row[0] or "")))
                    indices = (0, 1, 2, 3, 4, 5, 6, 9, profile["ethanol_urban"], profile["gasoline_urban"])
                    lengths = [len(cells[i]) for i in indices]
                    positive = [length for length in lengths if length]
                    count = min(positive) if positive else 0
                    if count == 0: continue
                    if any(length not in (0, count) for length in lengths):
                        # Allow excess trailing cells only when their trailing item is visibly corrupted.
                        excess_columns = [i for i in indices if len(cells[i]) > count]
                        if any(not re.search(r"�|(?:\b\w\b\s*){4,}", cells[i][-1]) for i in excess_columns):
                            raise ValueError(f"Campos desalinhados na extração agrupada do ciclo {year}.")
                        for i in excess_columns: cells[i] = cells[i][:count]
                    if any(length not in (0, count) for length in (len(cells[i]) for i in indices)):
                        raise ValueError(f"Campos desalinhados na extração agrupada do ciclo {year}.")
                    for idx in range(count):
                        yield [cells[col][idx] if idx < len(cells[col]) else "" for col in range(profile["columns"])], profile
                else:
                    if row_index < profile["header_rows"]: continue
                    yield [text(value) for value in row], profile
    if not found_profile: raise ValueError(f"Perfil de tabela oficial não reconhecido para {year}.")


def _iter_2026_rows(pdf, fitz_document):
    """2026 PDF has overlapping table-cell extraction; rebuild each visual row from positioned words."""
    found = False
    for page_index, page in enumerate(pdf.pages):
        fitz_page = fitz_document[page_index]
        for table in page.find_tables():
            if not table.rows or len(table.rows[0].cells) != PROFILES[2026]["columns"]: continue
            found = True
            reference_row = next((candidate for candidate in table.rows
                if all(candidate.cells[i] is not None for i in range(PROFILES[2026]["columns"]))), None)
            if reference_row is None: raise ValueError("Não foi possível estabelecer os limites das colunas PBEV 2026.")
            x_bounds = [(reference_row.cells[i][0], reference_row.cells[i][2]) for i in range(PROFILES[2026]["columns"])]
            cuts = [(x_bounds[i][1] + x_bounds[i + 1][0]) / 2 for i in range(len(x_bounds) - 1)]
            bins: dict[float, list[list[tuple[float, str]]]] = {}
            for word in fitz_page.get_text("words"):
                x0, y0, _, _, token = word[:5]
                if not (table.bbox[1] <= y0 <= table.bbox[3]): continue
                if not (x_bounds[0][0] - 1 <= x0 <= x_bounds[-1][1] + 1): continue
                column = next((i for i, cut in enumerate(cuts) if x0 < cut), len(cuts))
                bins.setdefault(round(y0, 1), [[] for _ in x_bounds])[column].append((x0, text(token)))
            for cells in bins.values():
                row = [" ".join(token for _, token in sorted(column_words)) for column_words in cells]
                if not row[1] or not row[2] or header_key(row[1]) == "marca": continue
                # Section labels can be rendered as a sparse pseudo-row by PDF word extraction.
                if not any(row[i] for i in (3, 4, 5, 6, 9, 18, 19, 20, 21, 22, 23, 28, 29)): continue
                # Rows without a propulsion label are sparse continuation/category artifacts in this PDF extraction,
                # not complete PBE vehicle records; omit them rather than fabricate identifying attributes.
                if not row[5]: continue
                yield row
    if not found: raise ValueError("Tabela/PDF oficial de 2026 não reconhecida.")


def normalize_rows(raw_rows: list[list], year: int, cycle: str, reference_date: str | None, document_url: str) -> list[dict]:
    profile = PROFILES[year]; records = []
    expected_width = profile["columns"]
    for row in raw_rows:
        if len(row) != expected_width: raise ValueError(f"Largura de linha inesperada no ciclo {year}.")
        category, brand, model, version = (text(row[i]) for i in range(4))
        if not brand or not model or key(brand) in {"MARCA", "CATEGORIA"} or key(model) == "MODELO": continue
        propulsion, official_fuel_code = text(row[profile["propulsion"]]), text(row[profile["fuel"]])
        fuel_code = official_fuel_code.upper()
        fuel_kind = {"G": "GASOLINE", "GASOLINA": "GASOLINE", "F": "FLEX", "E100": "ETHANOL",
                     "E": "ELECTRIC", "D": "DIESEL"}.get(fuel_code)
        if not fuel_kind and official_fuel_code:
            raise ValueError(f"Código de combustível PBEV desconhecido: {official_fuel_code!r} no ciclo {year}.")
        fuel_kind = fuel_kind or "UNSPECIFIED"
        if not propulsion: raise ValueError(f"Propulsão ausente em {brand} {model} ({year}).")
        # Do not interpret electric-equivalent / diesel columns as km/L for gasoline or ethanol.
        urban_ethanol = parse_number(row[profile["ethanol_urban"]], upper=80) if fuel_kind in {"FLEX", "ETHANOL"} else None
        urban_gasoline = parse_number(row[profile["gasoline_urban"]], upper=80) if fuel_kind in {"GASOLINE", "FLEX"} else None
        fuels = {}
        try:
            if urban_gasoline is not None and fuel_kind in {"GASOLINE", "FLEX"}: fuels["GASOLINE"] = {"urban": urban_gasoline, "unit": "km/L", "road": parse_number(row[profile["gasoline_urban"] + 1], upper=300) if profile["gasoline_urban"] + 1 < expected_width else None}
            if urban_ethanol is not None and fuel_kind in {"FLEX", "ETHANOL"}: fuels["ETHANOL"] = {"urban": urban_ethanol, "unit": "km/L", "road": parse_number(row[profile["ethanol_urban"] + 1], upper=300) if profile["ethanol_urban"] + 1 < expected_width else None}
        except ValueError as exc:
            raise ValueError(f"Consumo/unidade inconsistente em {brand} {model} {version}, ciclo {year}: {exc}") from exc
        record = {
            "sourceYear": year, "sourceCycle": cycle, "sourceReferenceDate": reference_date,
            "sourceDocument": document_url, "category": category or None, "brand": brand, "model": model,
            "version": version or None, "engine": text(row[4]) or None,
            "propulsionType": propulsion, "transmission": text(row[6]) or None,
            "airConditioning": text(row[7]) or None, "steering": text(row[8]) or None,
            "officialFuelCode": official_fuel_code or None, "fuels": fuels,
            "energyConsumptionMJPerKm": parse_number(row[profile["energy"]], upper=20) if profile["energy"] is not None else None,
            "electricRangeKm": parse_number(row[profile["range"]], upper=3000) if profile["range"] is not None else None,
            "efficiencyClass": text(row[profile["class"]]) or None if profile["class"] is not None else None,
            "conpetSeal": text(row[profile["conpet"]]) or None if profile["conpet"] is not None else None,
        }
        record["id"] = record_id(record)
        records.append(record)
    if len(records) < 30: raise ValueError(f"Quantidade de registros incompatível no ciclo {year}: {len(records)}.")
    by_id = {}
    for record in records:
        existing = by_id.get(record["id"])
        if existing is not None and existing != record:
            differing = [field for field in record if record.get(field) != existing.get(field)]
            raise ValueError(f"Registros conflitantes com ID técnico igual no ciclo {year}: {record['brand']} {record['model']} {record.get('version') or ''} ({', '.join(differing)}): {existing.get('fuels')} / {record.get('fuels')}.")
        by_id[record["id"]] = record
    return list(by_id.values())


def parse_pdf(raw: bytes, cycle: dict) -> list[dict]:
    if not raw or len(raw) < 1000 or not raw.startswith(b"%PDF"): raise ValueError("Documento PBEV vazio ou não é PDF.")
    import io
    with pdfplumber.open(io.BytesIO(raw)) as pdf, pymupdf.open(stream=raw, filetype="pdf") as fitz_document:
        if not pdf.pages: raise ValueError("Documento PBEV sem páginas.")
        rows = list(_iter_2026_rows(pdf, fitz_document)) if cycle["sourceYear"] == 2026 else [row for row, _ in _iter_raw_rows(pdf, cycle["sourceYear"])]
    return normalize_rows(rows, cycle["sourceYear"], cycle["sourceCycle"], cycle.get("sourceReferenceDate"), cycle["documentUrl"])


def build_files(cycles: list[dict], generated_at: str, previous_manifest: dict | None = None, previous_files: dict[str, bytes] | None = None) -> dict[str, bytes]:
    files = dict(previous_files or {}); previous = (previous_manifest or {}).get("vehicleEfficiency", {})
    cycle_manifest = {}; all_records = []
    for cycle in cycles:
        year = cycle["sourceYear"]; records = cycle["records"]
        if len(records) < 30: raise ValueError(f"Ciclo {year} não validado: registros insuficientes.")
        path = f"datasets/vehicle-efficiency/{year}.json"
        body = json.dumps({"schemaVersion": SCHEMA_VERSION, "sourceYear": year, "sourceCycle": cycle["sourceCycle"], "records": records}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        files[path] = body
        cycle_manifest[str(year)] = {"sourceYear": year, "sourceCycle": cycle["sourceCycle"], "sourceReferenceDate": cycle.get("sourceReferenceDate"), "documentUrl": cycle["documentUrl"], "sha256": cycle.get("sourceSha256"), "dataset": {"path": path, "sha256": hashlib.sha256(body).hexdigest(), "recordCount": len(records)}}
        all_records.extend(records)
    old_cycle_keys = set(previous.get("cycles", {}))
    if old_cycle_keys - set(cycle_manifest): raise ValueError("Algum ciclo anteriormente publicado sumiu da descoberta oficial; atualização cancelada.")
    for year, current in cycle_manifest.items():
        old = previous.get("cycles", {}).get(year, {}).get("dataset", {}).get("recordCount", 0)
        if old and current["dataset"]["recordCount"] < int(old * 0.5):
            raise ValueError(f"Queda anormal de registros PBEV no ciclo {year}: {old} → {current['dataset']['recordCount']}.")
    catalog_records = [{k: r.get(k) for k in ("id", "sourceYear", "sourceCycle", "category", "brand", "model", "version", "engine", "propulsionType", "transmission", "airConditioning", "steering", "officialFuelCode", "fuels")} for r in all_records]
    catalog_records.sort(key=lambda r: (key(r["brand"]), key(r["model"]), key(r.get("version") or ""), r["sourceYear"], r["id"]))
    catalog_path = "datasets/vehicle-efficiency/catalog.json"
    catalog_body = json.dumps({"schemaVersion": SCHEMA_VERSION, "records": catalog_records}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    files[catalog_path] = catalog_body
    dataset_version = hashlib.sha256("".join(cycle_manifest[str(y)]["dataset"]["sha256"] for y in sorted(map(int, cycle_manifest))).encode()).hexdigest()[:20]
    return {**files, "vehicleEfficiency": json.dumps({
        "schemaVersion": SCHEMA_VERSION, "datasetVersion": dataset_version, "generatedAt": generated_at,
        "source": "INMETRO_PBE", "sourceName": SOURCE_NAME, "sourceIndex": SOURCE_INDEX,
        "sourceReferenceDate": max((c["sourceReferenceDate"] or "" for c in cycles), default="") or None,
        "recordCount": len(catalog_records), "catalog": {"path": catalog_path, "sha256": hashlib.sha256(catalog_body).hexdigest(), "recordCount": len(catalog_records)},
        "cycles": cycle_manifest}, ensure_ascii=False, sort_keys=True, indent=2).encode()}


def fetch(url: str, timeout: int = 60) -> bytes:
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": "BetoData/1.0 (+https://github.com/williamqf/Beto)"})
    with urlopen(req, timeout=timeout) as response:
        body = response.read()
        if response.status != 200 or not body: raise ValueError(f"Download PBEV inválido: HTTP {response.status}.")
        return body


def update(destination: Path = DIST, fetcher=fetch, generated_at: str | None = None) -> bool:
    html = fetcher(SOURCE_INDEX).decode("utf-8", errors="replace")
    discovered = discover_cycles(html)
    previous_manifest = json.loads((destination / "manifest.json").read_text("utf-8")) if (destination / "manifest.json").exists() else {}
    old_vehicle = previous_manifest.get("vehicleEfficiency", {})
    previous_files = {}
    base = "https://williamqf.github.io/beto-data"
    if old_vehicle:
        for meta in [old_vehicle.get("catalog", {})] + [v.get("dataset", {}) for v in old_vehicle.get("cycles", {}).values()]:
            path = meta.get("path")
            if path and (destination / path).exists(): previous_files[path] = (destination / path).read_bytes()
    cycles = []
    for item in discovered:
        raw = fetcher(item["documentUrl"])
        item = {**item, "sourceSha256": hashlib.sha256(raw).hexdigest(), "records": parse_pdf(raw, item)}
        cycles.append(item)
    built = build_files(cycles, generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), previous_manifest, previous_files)
    vehicle_meta = json.loads(built.pop("vehicleEfficiency"))
    new_manifest = {**previous_manifest, "schemaVersion": SCHEMA_VERSION, "vehicleEfficiency": vehicle_meta}
    built["manifest.json"] = json.dumps(new_manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
    # Compare only this source branch; do not republish when official inputs are byte-identical.
    if old_vehicle.get("datasetVersion") == vehicle_meta["datasetVersion"] and all((destination / p).exists() and (destination / p).read_bytes() == b for p, b in built.items() if p.startswith("datasets/vehicle-efficiency/")):
        return False
    return built


def main() -> int:
    import argparse, os, shutil, sys, tempfile
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--dist", type=Path, default=DIST); args = parser.parse_args()
    try:
        built = update(args.dist)
        if built is False: print(json.dumps({"changed": False})); return 0
        manifest = json.loads(built["manifest.json"])
        # Merge the validated vehicle branch into the current ANP publication without touching ANP datasets.
        with tempfile.TemporaryDirectory(prefix="beto-pbev-") as td:
            stage = Path(td) / "stage"; shutil.copytree(args.dist, stage, dirs_exist_ok=True)
            for relative, body in built.items():
                target = stage / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
            backup = Path(td) / "old"
            if args.dist.exists(): os.replace(args.dist, backup)
            try: os.replace(stage, args.dist)
            except Exception:
                if backup.exists() and not args.dist.exists(): os.replace(backup, args.dist)
                raise
        print(json.dumps({"changed": True, "datasetVersion": manifest["vehicleEfficiency"]["datasetVersion"]}))
        return 0
    except Exception as exc:
        print(f"Beto Data INMETRO: atualização cancelada; publicação anterior preservada. {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
