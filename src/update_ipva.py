#!/usr/bin/env python3
"""Validate official state sources and publish normalized IPVA rules for supported UFs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SCHEMA_VERSION = 1
RULES = {
    "MG": {
        "sourceName": "SEF/MG — dúvidas frequentes e legislação do IPVA",
        "sourceUrl": "https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ipva/duvidas_frequentes/",
        "baseSourceName": "SEF/MG — Resolução 5.977/2025 e tabelas de base do IPVA 2026",
        "baseSourceUrl": "https://diarioeletronico.fazenda.mg.gov.br/opendiariogeral/resultados-ipva/index.html",
        "markers": ["4% (quatro por cento) para automóvel", "redução de 30% da base de cálculo"],
        "baseMarkers": ["base de cálculo do IPVA", "IPVA 2026"],
        "rules": [
            {"vehicleCategory": "PASSENGER_CAR", "rate": 4.0,
             "conditions": {"fuelTypes": ["GASOLINE", "FLEX", "DIESEL"]},
             "notes": "Automóvel de passeio. Combustível exclusivamente álcool possui redução legal de 30% na base; categorias e propulsões especiais exigem análise separada.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK", "supported": True},
            {"vehicleCategory": "PASSENGER_CAR", "rate": 4.0,
             "conditions": {"fuelTypes": ["ETHANOL"]},
             "notes": "Veículo exclusivamente movido a álcool: redução de 30% da base de cálculo, conforme regra oficial.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK", "baseMultiplier": 0.7, "supported": True},
        ],
    },
    "SP": {
        "sourceName": "ALESP — Lei 13.296/2008, texto compilado",
        "sourceUrl": "https://www.al.sp.gov.br/repositorio/legislacao/lei/2008/lei-13296-23.12.2008.html",
        "baseSourceName": "SEFAZ/SP — tabela anual de valores venais do exercício",
        "baseSourceUrl": "https://portal.fazenda.sp.gov.br/servicos/ipva/Paginas/perguntas-frequentes.aspx",
        "markers": ["3% (três por cento) para veículos que utilizarem motor especificado para funcionar exclusivamente", "4% (quatro por cento) para qualquer veículo automotor não incluído", "valor de mercado do veículo usado constante da tabela"],
        "baseMarkers": [],
        "rules": [
            {"vehicleCategory": "PASSENGER_CAR", "rate": 4.0,
             "conditions": {"fuelTypes": ["GASOLINE", "FLEX", "DIESEL"]},
             "notes": "Regra geral para automóvel não abrangido por categoria, redução ou isenção específica. A base depende da tabela estadual anual.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK", "supported": True},
            {"vehicleCategory": "PASSENGER_CAR", "rate": 3.0,
             "conditions": {"fuelTypes": ["ETHANOL", "GNV", "ELECTRIC"]},
             "notes": "Alíquota legal reduzida para motor exclusivamente movido a álcool, GNV ou eletricidade; a identificação do tipo de veículo precisa ser confiável.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK", "supported": True},
        ],
    },
    "PR": {
        "sourceName": "SEFA/PR — regras e alíquotas IPVA 2026",
        "sourceUrl": "https://www.fazenda.pr.gov.br/Pagina/Calcule-agora-seu-IPVA-2026",
        "baseSourceName": "SEFA/PR — valor venal de mercado do veículo",
        "baseSourceUrl": "https://www.fazenda.pr.gov.br/Noticia/Com-reducao-de-45-Parana-tera-menor-aliquota-de-IPVA-do-Brasil-em-2026",
        "markers": ["passa de 3,5% para 1,9% do valor do veículo"],
        "baseMarkers": [],
        "rules": [
            {"vehicleCategory": "PASSENGER_CAR", "rate": 1.0,
             "conditions": {"fuelTypes": ["GNV"]},
             "notes": "Veículo movido a GNV: alíquota especial de 1%.",
             "baseType": "STATE_MARKET_REFERENCE_WITH_FIPE_FALLBACK", "supported": True},
            {"vehicleCategory": "PASSENGER_CAR", "rate": 1.9,
             "conditions": {"fuelTypes": ["GASOLINE", "FLEX", "DIESEL", "ETHANOL"]},
             "notes": "Regra geral de 1,9% para automóveis no exercício 2026. Categorias especiais não cobertas permanecem manuais.",
             "baseType": "STATE_MARKET_REFERENCE_WITH_FIPE_FALLBACK", "supported": True},
        ],
    },
}


def normalized(value: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", value.upper()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", plain).split())


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def fetch_source(url: str, timeout: int = 25) -> str:
    request = Request(url, headers={"User-Agent": "Beto-Data-IPVA/1.0 (+https://github.com/williamqf/beto-data)"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"Fonte oficial respondeu HTTP {response.status}: {url}")
        raw = response.read()
    parser = TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(parser.parts)


def validate_sources(fetcher=fetch_source) -> None:
    for uf, config in RULES.items():
        text = normalized(fetcher(config["sourceUrl"]))
        for marker in config["markers"]:
            if normalized(marker) not in text:
                raise ValueError(f"Fonte {uf} mudou ou não confirma o marcador esperado: {marker}")
        if config.get("baseMarkers"):
            base_text = normalized(fetcher(config["baseSourceUrl"]))
            for marker in config["baseMarkers"]:
                if normalized(marker) not in base_text:
                    raise ValueError(f"Fonte de base {uf} mudou ou não confirma o marcador esperado: {marker}")
        for rule in config["rules"]:
            if not 0.0 < float(rule["rate"]) <= 100.0:
                raise ValueError(f"Alíquota inválida em {uf}.")
            if not 0.0 < float(rule.get("baseMultiplier", 1.0)) <= 1.0:
                raise ValueError(f"Fator de base inválido em {uf}.")


def build_files(previous_manifest: dict, previous_files: dict[str, bytes], now: datetime) -> dict[str, bytes]:
    year = 2026
    content_signature = json.dumps(RULES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    dataset_version = hashlib.sha256(content_signature).hexdigest()[:16]
    timestamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    old_branch = previous_manifest.get("ipva", {})
    old_year = old_branch.get("years", {}).get(str(year), {})
    files = dict(previous_files)
    state_index = {}
    for uf, config in RULES.items():
        path = f"datasets/taxes/ipva/{year}/{uf}.json"
        old_entry = old_year.get(uf, {})
        old_bytes = files.get(path)
        old_dataset = None
        if old_bytes:
            try:
                old_dataset = json.loads(old_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError):
                old_dataset = None
        verified_at = old_dataset.get("verifiedAt", timestamp) if old_dataset and old_dataset.get("datasetVersion") == dataset_version else timestamp
        published_at = old_dataset.get("publishedAt", timestamp) if old_dataset and old_dataset.get("datasetVersion") == dataset_version else timestamp
        dataset = {
            "uf": uf, "year": year, "schemaVersion": SCHEMA_VERSION, "datasetVersion": dataset_version,
            "sourceName": config["sourceName"], "sourceUrl": config["sourceUrl"],
            "baseSourceName": config["baseSourceName"], "baseSourceUrl": config["baseSourceUrl"],
            "publishedAt": published_at, "verifiedAt": verified_at,
            "rules": config["rules"],
        }
        body = (json.dumps(dataset, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        files[path] = body
        state_index[uf] = {"path": path, "sha256": digest, "recordCount": len(dataset["rules"])}

    ipva_manifest = {
        "schemaVersion": SCHEMA_VERSION, "datasetVersion": dataset_version,
        "years": {str(year): state_index},
    }
    manifest = {**previous_manifest, "ipva": ipva_manifest}
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    validate_output(files, year)
    return files


def validate_output(files: dict[str, bytes], year: int) -> None:
    manifest = json.loads(files["manifest.json"])
    branch = manifest["ipva"]
    if branch.get("schemaVersion") != SCHEMA_VERSION or str(year) not in branch.get("years", {}):
        raise ValueError("Manifesto IPVA inválido.")
    for uf, entry in branch["years"][str(year)].items():
        if uf not in RULES or not re.fullmatch(r"datasets/taxes/ipva/\d{4}/[A-Z]{2}\.json", entry["path"]):
            raise ValueError("Caminho ou UF inválido no manifesto IPVA.")
        body = files.get(entry["path"])
        if body is None or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum ausente/inválido para {uf}.")
        dataset = json.loads(body)
        if dataset.get("schemaVersion") != SCHEMA_VERSION or dataset.get("uf") != uf or dataset.get("year") != year:
            raise ValueError(f"Schema/UF/exercício inválido para {uf}.")
        if len(dataset.get("rules", [])) != entry.get("recordCount"):
            raise ValueError(f"Contagem de regras inválida para {uf}.")
        for source in (dataset.get("sourceUrl", ""), dataset.get("baseSourceUrl", "")):
            if not source.startswith("https://") or not re.search(r"(?:\.gov\.br|\.al\.sp\.gov\.br)(?:/|$)", source.split("/", 3)[2]):
                raise ValueError(f"Fonte não oficial para {uf}: {source}")


def read_dist(destination: Path) -> tuple[dict, dict[str, bytes]]:
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    files = {path.relative_to(destination).as_posix(): path.read_bytes() for path in destination.rglob("*") if path.is_file() and path.name != "manifest.json"}
    return manifest, files


def fetch_remote_dist(base_url: str) -> tuple[dict, dict[str, bytes]]:
    import urllib.request
    base = base_url.rstrip("/")
    raw = urllib.request.urlopen(base + "/manifest.json", timeout=25).read()
    manifest = json.loads(raw)
    files: dict[str, bytes] = {"manifest.json": raw}
    entries = []
    entries.extend(manifest.get("datasets", {}).values())
    vehicle = manifest.get("vehicleEfficiency", {})
    entries.append(vehicle.get("catalog", {}))
    entries.extend(c.get("dataset", {}) for c in vehicle.get("cycles", {}).values())
    for states in manifest.get("ipva", {}).get("years", {}).values():
        entries.extend(states.values())
    for entry in entries:
        path = entry.get("path")
        if not path or ".." in path or not path.startswith("datasets/"):
            continue
        body = urllib.request.urlopen(base + "/" + path, timeout=45).read()
        if hashlib.sha256(body).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Checksum remoto inválido: {path}")
        files[path] = body
    return manifest, files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-base-url", help="Baixa a publicação atual para preservar os outros ramos do Beto Data.")
    parser.add_argument("--skip-source-verification", action="store_true", help="Uso local/offline; nunca usado pelo workflow.")
    args = parser.parse_args()
    if not args.skip_source_verification:
        validate_sources()
    if args.previous_base_url:
        manifest, files = fetch_remote_dist(args.previous_base_url)
    else:
        manifest, files = read_dist(DIST)
    built = build_files(manifest, files, datetime.now(timezone.utc))
    old = {path.relative_to(DIST).as_posix(): path.read_bytes() for path in DIST.rglob("*") if path.is_file()} if DIST.exists() else {}
    changed = built != old
    if changed:
        # Stage beside dist and restore the old publication if replacement fails.
        DIST.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dist-ipva-", dir=DIST.parent) as temp_root:
            temp = Path(temp_root) / "dist"
            temp.mkdir()
            for path, body in built.items():
                target = temp / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            backup = Path(temp_root) / "previous-dist"
            had_previous = DIST.exists()
            if had_previous:
                DIST.rename(backup)
            try:
                temp.rename(DIST)
            except Exception:
                if had_previous and backup.exists() and not DIST.exists():
                    backup.rename(DIST)
                raise
    branch = json.loads(built["manifest.json"])["ipva"]
    print(json.dumps({"changed": changed, "datasetVersion": branch["datasetVersion"], "states": sorted(RULES)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
