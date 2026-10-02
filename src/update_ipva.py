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
SCHEMA_VERSION = 2
SUPPORTED_OPERATORS = {"EQUALS", "IN", "GT", "GTE", "LT", "LTE", "BETWEEN"}
SUPPORTED_FIELDS = {
    "uf", "taxYear", "vehicleCategory", "vehicleType", "usageType", "manufactureYear", "modelYear",
    "vehicleSpecies", "vehicleSegment", "vehicleSubsegment", "bodyType", "passengerCapacity", "grossVehicleWeight", "axleCount",
    "vehicleAge", "fuelType", "vehicleHasGnv", "gnvRegularized", "enginePowerHp", "engineDisplacementCc", "referenceValue",
}
UF_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
# The coverage registry is deliberately separate from executable rules. A UF can be
# recognized and documented while remaining on the safe manual-entry path.
COVERAGE_2026 = {
    "AC": {"status": "AUTO", "rule": "2% para veículos de passeio", "source": "https://sefaz.ac.gov.br/2021/?p=21413", "base": "Tabela estadual 2026 por tipo, marca e modelo; FIPE pode ser fallback estimado", "baseSource": "https://sefaz.ac.gov.br/2021/?p=23209", "blocker": "Correspondência da tabela estadual por veículo ainda não foi normalizada; resultados atuais usam FIPE como estimativa."},
    "AL": {"status": "PARTIAL", "rule": "2,75% a 3,25% conforme potência; GNV/híbrido 1,5%; elétrico 2%", "source": "https://www.sefaz.al.gov.br/nise/faq/ipva/473-3-calculo-e-aliquotas", "base": "Consulta oficial 2026 usa FIPE por veículo", "baseSource": "https://ipvaonline.sefaz.al.gov.br/", "blocker": "Potência, condição GNV/híbrido e elegibilidade não estão representadas com segurança no modelo atual."},
    "AP": {"status": "MANUAL_ONLY", "rule": "Não confirmada em fonte normativa oficial vigente nesta auditoria", "source": "https://virtual.sefaz.ap.gov.br/", "base": "Tabela oficial 2026 não confirmada", "baseSource": "https://virtual.sefaz.ap.gov.br/", "blocker": "Não foi possível confirmar regra e base oficial de 2026; manter entrada manual."},
    "AM": {"status": "PARTIAL", "rule": "Regra varia por cilindrada; veículos elétricos/híbridos têm tratamento específico", "source": "https://online.sefaz.am.gov.br/doe/toPdf.asp?idPublicacao=2376", "base": "Tabela por modelo publicada para exercício anterior; base 2026 não verificada", "baseSource": "https://www.sefaz.am.gov.br/", "blocker": "Regra condicionada a cilindrada e ano; documentação oficial de base 2026 não confirmada."},
    "BA": {"status": "PARTIAL", "rule": "2,5% para combustíveis não diesel; 3% para diesel", "source": "https://www.sefaz.ba.gov.br/inspetoria-eletronica/ipva/informacoes/", "base": "Tabela estadual oficial por modelo e ano para 2026; FIPE seria estimativa", "baseSource": "https://www.sefaz.ba.gov.br/docs/inspetoria-eletronica/ipva/valor_venal_veiculo_2026.pdf", "blocker": "A tabela oficial ainda não é resolvida pelo Android; exige validação do combustível e correspondência do modelo."},
    "CE": {"status": "AUTO_WITH_USER_INPUT", "rule": "2,5% até 100 cv; 3% acima de 100 até 180 cv; 3,5% acima de 180 cv para automóveis e utilitários a combustão", "source": "https://www2.al.ce.gov.br/legislativo/legislacao5/leis92/12023.htm", "base": "Tabela oficial 2026 publicada por exercício; FIPE compatível é fallback estimado", "baseSource": "https://ipva.sefaz.ce.gov.br/", "blocker": "Tabela oficial de veículos 2026 não está integrada; pergunta potência apenas se ausente e usa FIPE estimada."},
    "DF": {"status": "PARTIAL", "rule": "3% para automóveis; 3,5% em hipóteses específicas de benefício", "source": "https://mobile.receita.fazenda.df.gov.br/aplicacoes/UltimasNormasPublicadas/TelaSaidaDocumento.cfm?txtAno=2026&txtNumero=1&txtParte=IPVA+2026&txtTipo=453", "base": "Pauta de Valores Venais 2026 prevista na Lei nº 7.827/2025", "baseSource": "https://mobile.receita.fazenda.df.gov.br/aplicacoes/UltimasNormasPublicadas/TelaSaidaDocumento.cfm?txtAno=2026&txtNumero=1&txtParte=IPVA+2026&txtTipo=453", "blocker": "A pauta não está normalizada; identificar veículos abrangidos pelas hipóteses especiais exige mais dados."},
    "ES": {"status": "AUTO", "rule": "2% para carros de passeio e utilitários no exercício 2026", "source": "https://sefaz.es.gov.br/informacoes-ipva", "base": "Tabela oficial estadual 2026 em PDFs por categoria; FIPE compatível é fallback estimado", "baseSource": "https://sefaz.es.gov.br/base-de-calculo", "blocker": "Base estadual ainda não tem matching normalizado no app; resultado usa FIPE como estimativa."},
    "GO": {"status": "AUTO_WITH_USER_INPUT", "rule": "3% até 100 cv; 3,75% acima de 100 cv para automóveis de passeio", "source": "https://goias.gov.br/economia/perguntas-e-respostas-6/", "base": "Tabela oficial 2026 por marca, modelo, combustível e ano; FIPE compatível é fallback estimado", "baseSource": "https://goias.gov.br/economia/calendario-de-vencimentos/", "blocker": "Pede potência somente se a resposta da placa não informar um valor com unidade; FIPE é base estimada."},
    "MA": {"status": "PARTIAL", "rule": "2,5% até R$ 150 mil; 3% acima; desconto condicionado à situação do condutor", "source": "https://www.al.ma.leg.br/sitealema/wp-content/uploads/2025/12/DIARIO_221_18.12.2025.pdf", "base": "Base anual estadual; tabela 2026 específica não confirmada nesta auditoria", "baseSource": "https://www.sefaz.ma.gov.br/", "blocker": "Faixa depende do valor venal e há desconto vinculado a dados pessoais que o app não coleta."},
    "MT": {"status": "AUTO_WITH_USER_INPUT", "rule": "2% até 1.000 cm³; 3% acima para automóveis de passeio", "source": "https://www5.sefaz.mt.gov.br/documents/6071037/10218152/AL%C3%8DQUOTAS%2BIPVA.pdf/f1a8491d-484b-5876-2d54-382813d76121", "base": "Tabela estadual de valores venais 2026; FIPE compatível é fallback estimado", "baseSource": "https://www5.sefaz.mt.gov.br/servicos?c=75032612&e=75032935", "blocker": "Pede cilindrada somente se a resposta da placa não informar valor confiável; FIPE é base estimada."},
    "MS": {"status": "PARTIAL", "rule": "Veículos usados: 3% passeio comum; 4,5% passeio diesel; GNV tem redução", "source": "https://www.sefaz.ms.gov.br/ipva/", "base": "FIPE contratada pelo Estado para valor venal", "baseSource": "https://www.sefaz.ms.gov.br/ipva/", "blocker": "Reduções GNV/frotista e separação novo/usado precisam de dados que a seleção atual não fornece."},
    "MG": {"status": "AUTO", "rule": "4% geral; combustível exclusivamente álcool tem redução de 30% da base", "source": "https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ipva/duvidas_frequentes/", "base": "Tabela estadual 2026; fallback FIPE compatível", "baseSource": "https://diarioeletronico.fazenda.mg.gov.br/opendiariogeral/resultados-ipva/index.html", "blocker": "A tabela estadual não está integrada ao app; estimativas usam FIPE compatível."},
    "PA": {"status": "PARTIAL", "rule": "2,5% para automóveis e caminhonetes", "source": "https://site-sefa-wordpress.sefa.pa.gov.br/wp-content/uploads/legislacao/leis_estaduais/lp1996_06017.pdf", "base": "Tabela estadual 2026 publicada por modelo ainda não confirmada", "baseSource": "https://site-sefa-wordpress.sefa.pa.gov.br/", "blocker": "Regra legal encontrada, mas tabela do exercício 2026 e exceções não foram confirmadas."},
    "PB": {"status": "AUTO", "rule": "2,5% para automóveis", "source": "https://www.sefaz.pb.gov.br/legislacao/65-leis/ipva/5032-lei-n-11-007-de-06-de-novembro-de-2017", "base": "Relatório oficial de valores do IPVA 2026 por marca/modelo/ano; FIPE compatível é fallback estimado", "baseSource": "https://www.sefaz.pb.gov.br/legislacao/382-portarias/portarias-2025/17092-portaria-n-00218-2025-sefaz", "blocker": "A base por modelo existe, mas ainda não tem resolução confiável no app; resultado usa FIPE estimada."},
    "PR": {"status": "AUTO", "rule": "1,9% geral para automóveis; 1% GNV", "source": "https://www.fazenda.pr.gov.br/Pagina/Calcule-agora-seu-IPVA-2026", "base": "Referência FIPE compatível; valor estadual não integrado", "baseSource": "https://www.fazenda.pr.gov.br/Noticia/Com-reducao-de-45-Parana-tera-menor-aliquota-de-IPVA-do-Brasil-em-2026", "blocker": "Base oficial exata não está integrada; GNV é regra separada."},
    "PE": {"status": "PARTIAL", "rule": "2,4% geral; GNV até R$ 100 mil 1,5%; elétrico isento; 20 anos ou mais sem incidência", "source": "https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/legislacao/Leis_Tributarias/2023/Lei18305_2023.htm", "base": "Tabela estadual 2026 com base, alíquota e valor por modelo", "baseSource": "https://www.sefaz.pe.gov.br/Servicos/IPVA/Valores%20de%20IPVA/Tabela%20IPVA%202026.pdf", "blocker": "A regra especial depende do combustível, valor, comprovação de adaptação e ano; exige condições ainda ausentes."},
    "PI": {"status": "MANUAL_ONLY", "rule": "Lei localizada indica 2,5% para automóveis, mas consolidação vigente em 2026 não confirmada", "source": "https://www.sefaz.pi.gov.br/arquivos/legislacao/leis/Lei4548.pdf", "base": "Tabela oficial 2026 não confirmada", "baseSource": "https://www.sefaz.pi.gov.br/", "blocker": "Fonte normativa consultada está consolidada somente até 2011; não automatizar sem validar alterações posteriores e base 2026."},
    "RJ": {"status": "MANUAL_ONLY", "rule": "Não confirmada em fonte normativa oficial específica de 2026 nesta auditoria", "source": "https://portal.fazenda.rj.gov.br/ipva/", "base": "A SEFAZ publica base venal anual; vínculo 2026/modelo requer validação", "baseSource": "https://portal.fazenda.rj.gov.br/ipva/", "blocker": "Regra/fonte 2026 não validada; combustível e tratamentos especiais impedem inferência."},
    "RN": {"status": "MANUAL_ONLY", "rule": "Regra de isenção inclui veículos rodoviários com mais de 10 anos e veículos elétricos", "source": "https://www.sefaz.rn.gov.br/postagem/ipva-imunidades-isencoes-dispensa/", "base": "Tabela anual oficial disponível via consulta individual; regra/base 2026 não confirmadas", "baseSource": "https://www.sefaz.rn.gov.br/postagem/ipva/", "blocker": "Alíquota de passeio e tabela 2026 não foram confirmadas; isenção por idade e propulsão aumenta o risco."},
    "RS": {"status": "PARTIAL", "rule": "3% para automóveis; elétricos isentos; veículos com mais de 20 anos isentos", "source": "https://www.sefaz.rs.gov.br/ASP/SEF_ROOT/INF/ipva-index.htm", "base": "Valor médio divulgado anualmente pelo Poder Executivo", "baseSource": "https://www.sefaz.rs.gov.br/ASP/SEF_ROOT/INF/ipva-index.htm", "blocker": "Página pública de alíquotas está desatualizada e não confirma a regra de exercício 2026; FIPE não pode ser tratada como base oficial."},
    "RO": {"status": "MANUAL_ONLY", "rule": "Não confirmada em fonte oficial vigente do exercício 2026 nesta auditoria", "source": "https://www.sefin.ro.gov.br/", "base": "Tabela oficial 2026 não confirmada", "baseSource": "https://www.sefin.ro.gov.br/", "blocker": "Sem fonte normativa e base do exercício 2026 verificadas."},
    "RR": {"status": "MANUAL_ONLY", "rule": "Lei nº 059/1993 prevê exceções; alíquota geral de passeio não confirmada na fonte consultada", "source": "https://www.sefaz.rr.gov.br/downloads/legislacao", "base": "Portaria/tabela 2026 existe, mas sem regra geral de passeio validada", "baseSource": "https://www.sefaz.rr.gov.br/downloads/legislacao", "blocker": "Norma 2026 altera regras de pagamento e redução; sem alíquota de passeio confirmada."},
    "SC": {"status": "AUTO", "rule": "2% para veículos de passeio e utilitários", "source": "https://legislacao.sef.sc.gov.br/html/atos_diat/2025/atodiat_25_099.htm", "base": "Base FIPE usada pela SEF/SC com valor venal estadual; FIPE compatível é fallback estimado", "baseSource": "https://www.sef.sc.gov.br/saiba-mais/ipva-imposto-sobre-veiculos-automotores", "blocker": "A resolução da base estadual por modelo ainda não existe no app; resultado usa FIPE como estimativa."},
    "SP": {"status": "AUTO", "rule": "4% geral; 3% exclusivamente álcool, GNV ou eletricidade", "source": "https://www.al.sp.gov.br/repositorio/legislacao/lei/2008/lei-13296-23.12.2008.html", "base": "Tabela estadual anual; fallback FIPE compatível", "baseSource": "https://portal.fazenda.sp.gov.br/servicos/ipva/Paginas/perguntas-frequentes.aspx", "blocker": "A tabela estadual não está integrada; propulsão deve ser confiável."},
    "SE": {"status": "PARTIAL", "rule": "2,5% se valor venal até R$ 120 mil; 3% acima", "source": "https://www.sefaz.se.gov.br/SitePages/NoticiaDetalhes.aspx?cod=2810", "base": "FIPE usada como valor de mercado para tabela 2026", "baseSource": "https://www.sefaz.se.gov.br/SitePages/NoticiaDetalhes.aspx?cod=2810", "blocker": "Escolha da alíquota depende do valor-base; condição ainda não existe no modelo Android."},
    "TO": {"status": "PARTIAL", "rule": "2,5% até 100 cv e 3,5% acima de 100 cv; regra de não incidência para veículos com 20 anos ou mais", "source": "https://dtri.sefaz.to.gov.br/legislacao/ntributaria/Leis/Lei1.287-01Consolidada.htm", "base": "Valor médio de mercado fixado por ato da SEFAZ", "baseSource": "https://ipva.sefaz.to.gov.br/legislacao.php", "blocker": "A potência em cv, a idade para não incidência e a resolução da base oficial por modelo ainda não estão integradas."},
}
RULES = {
    "AC": {
        "sourceName": "SEFAZ/AC — LC nº 483/2024 e regras IPVA 2026",
        "sourceUrl": "https://sefaz.ac.gov.br/2021/?p=21413",
        "baseSourceName": "SEFAZ/AC — Portaria nº 751/2025, base IPVA 2026",
        "baseSourceUrl": "https://sefaz.ac.gov.br/2021/?p=23209",
        "markers": ["2,0% (dois por cento) para veículos de passeio"],
        "baseMarkers": ["exercício de 2026"],
        "rules": [{"id": "ac-passenger-standard", "priority": 10,
            "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "PICKUP", "MIXED"]}]},
            "effects": [{"type": "RATE", "value": 2.0}],
            "notes": "Automóveis de passeio, utilitários, camionetas de uso misto e caminhonetes abrangidos pela regra; base FIPE resulta em estimativa.",
            "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"}],
    },
    "CE": {
        "sourceName": "SEFAZ/CE — IPVA 2026, alíquotas previstas na Lei nº 12.023/1992",
        "sourceUrl": "https://www2.al.ce.gov.br/legislativo/legislacao5/leis92/12023.htm",
        "baseSourceName": "SEFAZ/CE — valores venais IPVA 2026",
        "baseSourceUrl": "https://ipva.sefaz.ce.gov.br/",
        "markers": ["SUPERIOR A 180CV"], "baseMarkers": [],
        "rules": [
            {"id": "ce-passenger-up-to-100cv", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "PICKUP", "UTILITY"]}, {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "ETHANOL", "DIESEL", "GNV"]}, {"field": "enginePowerHp", "operator": "LTE", "value": 98.632}]},
             "effects": [{"type": "RATE", "value": 2.5}], "notes": "Até 100 cv. Valor FIPE compatível é base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "ce-passenger-100-to-180cv", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "PICKUP", "UTILITY"]}, {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "ETHANOL", "DIESEL", "GNV"]}, {"field": "enginePowerHp", "operator": "GT", "value": 98.632}, {"field": "enginePowerHp", "operator": "LTE", "value": 177.5376}]},
             "effects": [{"type": "RATE", "value": 3.0}], "notes": "Acima de 100 cv até 180 cv. Valor FIPE compatível é base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "ce-passenger-over-180cv", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "PICKUP", "UTILITY"]}, {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "ETHANOL", "DIESEL", "GNV"]}, {"field": "enginePowerHp", "operator": "GT", "value": 177.5376}]},
             "effects": [{"type": "RATE", "value": 3.5}], "notes": "Acima de 180 cv. Valor FIPE compatível é base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
        ],
    },
    "ES": {
        "sourceName": "SEFAZ/ES — IPVA 2026",
        "sourceUrl": "https://sefaz.es.gov.br/informacoes-ipva",
        "baseSourceName": "SEFAZ/ES — base de cálculo do IPVA",
        "baseSourceUrl": "https://sefaz.es.gov.br/base-de-calculo",
        "markers": ["DOIS POR CENTO PARA CARROS DE PASSEIO"], "baseMarkers": [],
        "rules": [{"id": "es-passenger-standard", "priority": 10,
            "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "UTILITY"]}]},
            "effects": [{"type": "RATE", "value": 2.0}], "notes": "Alíquota geral de carros de passeio e utilitários em 2026; FIPE é uma base estimada.",
            "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"}],
    },
    "GO": {
        "sourceName": "Secretaria da Economia/GO — Código Tributário e FAQ do IPVA",
        "sourceUrl": "https://goias.gov.br/economia/perguntas-e-respostas-6/",
        "baseSourceName": "Secretaria da Economia/GO — valores venais IPVA 2026",
        "baseSourceUrl": "https://goias.gov.br/economia/calendario-de-vencimentos/",
        "markers": ["3,75%"], "baseMarkers": ["exercício de 2026"],
        "rules": [
            {"id": "go-passenger-up-to-100hp", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"}, {"field": "enginePowerHp", "operator": "LTE", "value": 100}]},
             "effects": [{"type": "RATE", "value": 3.0}], "notes": "Automóveis de passeio até 100 HP; potência ausente é perguntada ao usuário. FIPE é uma base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "go-passenger-over-100hp", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"}, {"field": "enginePowerHp", "operator": "GT", "value": 100}]},
             "effects": [{"type": "RATE", "value": 3.75}], "notes": "Automóveis de passeio acima de 100 HP; potência ausente é perguntada ao usuário. FIPE é uma base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
        ],
    },
    "MT": {
        "sourceName": "SEFAZ/MT — alíquotas do IPVA",
        "sourceUrl": "https://www5.sefaz.mt.gov.br/documents/6071037/10218152/AL%C3%8DQUOTAS%2BIPVA.pdf/f1a8491d-484b-5876-2d54-382813d76121",
        "baseSourceName": "SEFAZ/MT — tabela de valores venais IPVA 2026",
        "baseSourceUrl": "https://www5.sefaz.mt.gov.br/servicos?c=75032612&e=75032935",
        "markers": [], "baseMarkers": [],
        "rules": [
            {"id": "mt-passenger-up-to-1000cc", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"}, {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "ETHANOL", "DIESEL", "GNV"]}, {"field": "engineDisplacementCc", "operator": "LTE", "value": 1000}]},
             "effects": [{"type": "RATE", "value": 2.0}], "notes": "Automóvel de passeio até 1.000 cm³; cilindrada ausente é perguntada ao usuário. FIPE é uma base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "mt-passenger-over-1000cc", "priority": 20,
             "conditions": {"all": [{"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"}, {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "ETHANOL", "DIESEL", "GNV"]}, {"field": "engineDisplacementCc", "operator": "GT", "value": 1000}]},
             "effects": [{"type": "RATE", "value": 3.0}], "notes": "Automóvel de passeio acima de 1.000 cm³; cilindrada ausente é perguntada ao usuário. FIPE é uma base estimada.", "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
        ],
    },
    "PB": {
        "sourceName": "SEFAZ/PB — Lei nº 11.007/2017 e regras IPVA 2026",
        "sourceUrl": "https://www.sefaz.pb.gov.br/announcements/5033-nova-lei-do-imposto-sobre-a-propriedade-de-veiculos-automotores-ipva-lei-11-007",
        "baseSourceName": "SEFAZ/PB — Portaria nº 218/2025, valores IPVA 2026",
        "baseSourceUrl": "https://www.sefaz.pb.gov.br/legislacao/382-portarias/portarias-2025/17092-portaria-n-00218-2025-sefaz",
        "markers": ["2,5%"], "baseMarkers": [],
        "rules": [{"id": "pb-passenger-standard", "priority": 10,
            "conditions": {"all": [{"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"}]},
            "effects": [{"type": "RATE", "value": 2.5}], "notes": "Alíquota de automóveis; FIPE é uma base estimada quando a tabela estadual não casa com confiança.",
            "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"}],
    },
    "SC": {
        "sourceName": "SEF/SC — legislação do IPVA",
        "sourceUrl": "https://legislacao.sef.sc.gov.br/html/atos_diat/2025/atodiat_25_099.htm",
        "baseSourceName": "SEF/SC — bases anuais do IPVA",
        "baseSourceUrl": "https://www.sef.sc.gov.br/saiba-mais/ipva-imposto-sobre-veiculos-automotores",
        "markers": ["DOIS POR CENTO PARA VE"], "baseMarkers": [],
        "rules": [{"id": "sc-passenger-standard", "priority": 10,
            "conditions": {"all": [{"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "UTILITY"]}]},
            "effects": [{"type": "RATE", "value": 2.0}], "notes": "Veículo terrestre de passeio/utilitário; FIPE compatível continua estimativa da base estadual.",
            "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"}],
    },
    "MG": {
        "sourceName": "SEF/MG — dúvidas frequentes e legislação do IPVA",
        "sourceUrl": "https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ipva/duvidas_frequentes/",
        "baseSourceName": "SEF/MG — Resolução 5.977/2025 e tabelas de base do IPVA 2026",
        "baseSourceUrl": "https://diarioeletronico.fazenda.mg.gov.br/opendiariogeral/resultados-ipva/index.html",
        "markers": ["4% (quatro por cento) para automóvel", "redução de 30% da base de cálculo"],
        "baseMarkers": ["base de cálculo do IPVA", "IPVA 2026"],
        "rules": [
            {"id": "mg-passenger-standard", "priority": 10,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "DIESEL"]},
             ]},
             "effects": [{"type": "RATE", "value": 4.0}],
             "notes": "Automóvel de passeio. Categorias e propulsões especiais exigem análise separada.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "mg-passenger-exclusive-ethanol", "priority": 10,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["ETHANOL"]},
             ]},
             "effects": [{"type": "BASE_REDUCTION", "value": 0.30}, {"type": "RATE", "value": 4.0}],
             "notes": "Veículo exclusivamente movido a álcool: redução legal de 30% da base de cálculo.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
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
            {"id": "sp-passenger-standard", "priority": 10,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "DIESEL"]},
             ]},
             "effects": [{"type": "RATE", "value": 4.0}],
             "notes": "Regra geral para automóvel não abrangido por alíquota especial ou isenção.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
            {"id": "sp-passenger-exclusive-fuel", "priority": 10,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["ETHANOL", "GNV", "ELECTRIC"]},
             ]},
             "effects": [{"type": "RATE", "value": 3.0}],
             "notes": "Alíquota legal reduzida para motor exclusivamente movido a álcool, GNV ou eletricidade.",
             "baseType": "STATE_TABLE_WITH_FIPE_FALLBACK"},
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
            {"id": "pr-passenger-gnv", "priority": 100,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["GNV"]},
                 {"field": "gnvRegularized", "operator": "EQUALS", "value": "YES"},
             ]},
             "effects": [{"type": "RATE", "value": 1.0}],
             "notes": "Alíquota especial de 1% somente quando o complemento de categoria/combustível estiver registrado no DETRAN/PR; declaração do usuário é pedida quando necessária.",
             "baseType": "STATE_MARKET_REFERENCE_WITH_FIPE_FALLBACK"},
            {"id": "pr-passenger-standard", "priority": 10,
             "conditions": {"all": [
                 {"field": "vehicleCategory", "operator": "EQUALS", "value": "PASSENGER_CAR"},
                 {"field": "fuelType", "operator": "IN", "value": ["GASOLINE", "FLEX", "DIESEL", "ETHANOL"]},
             ]},
             "effects": [{"type": "RATE", "value": 1.9}],
             "notes": "Regra geral de 1,9% para automóveis no exercício 2026. Categorias especiais não cobertas permanecem manuais.",
             "baseType": "STATE_MARKET_REFERENCE_WITH_FIPE_FALLBACK"},
        ],
    },
}

# National constitutional immunity effective from 2025-12-09. One shared policy
# avoids duplicating the same vehicle-age rule in each state dataset.
COMMON_RULES = [{
    "id": "national-passenger-vehicle-20-years-immunity",
    "priority": 10_000,
    "conditions": {"all": [
        {"field": "vehicleAge", "operator": "GTE", "value": 20},
        {"field": "vehicleCategory", "operator": "IN", "value": ["PASSENGER_CAR", "PICKUP", "MIXED"]},
    ]},
    "effects": [{"type": "EXEMPT"}],
    "sourceName": "Constituição Federal — EC nº 137/2025",
    "sourceUrl": "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc137.htm",
    "notes": "Imunidade para veículos terrestres de passageiros, caminhonetes e mistos com 20 anos ou mais de fabricação; exclui ônibus, micro-ônibus, reboques e semirreboques.",
    "baseType": "NATIONAL_CONSTITUTIONAL_IMMUNITY",
}]


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
        encoding = response.headers.get_content_charset() or "utf-8"
        raw = response.read()
    parser = TextExtractor()
    parser.feed(raw.decode(encoding, errors="replace"))
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
            validate_v2_rule(rule, uf)


def build_files(previous_manifest: dict, previous_files: dict[str, bytes], now: datetime) -> dict[str, bytes]:
    year = 2026
    content_signature = json.dumps({"rules": RULES, "commonRules": COMMON_RULES}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
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
        "commonRules": COMMON_RULES,
        "coverage": {uf: {"status": row["status"], "rule": row["rule"], "sourceName": "Fonte oficial estadual", "sourceUrl": row["source"], "base": row["base"], "baseSourceUrl": row["baseSource"], "blocker": row["blocker"]} for uf, row in COVERAGE_2026.items()},
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
    coverage = branch.get("coverage", {})
    if set(coverage) != UF_CODES or set(COVERAGE_2026) != UF_CODES:
        raise ValueError("Matriz IPVA deve reconhecer exatamente as 27 UFs brasileiras.")
    statuses = {"AUTO", "AUTO_WITH_USER_INPUT", "PARTIAL", "MANUAL_ONLY"}
    for uf, entry in coverage.items():
        if entry.get("status") not in statuses:
            raise ValueError(f"Status de cobertura inválido para {uf}.")
        for source in (entry.get("sourceUrl", ""), entry.get("baseSourceUrl", "")):
            if not source.startswith("https://") or not re.search(r"(?:\.gov\.br|\.leg\.br|\.al\.sp\.gov\.br)(?:/|$)", source.split("/", 3)[2]):
                raise ValueError(f"Fonte não oficial na matriz IPVA de {uf}: {source}")
    for rule in branch.get("commonRules", []):
        validate_v2_rule(rule, "NATIONAL")
        source = rule.get("sourceUrl", "")
        if not source.startswith("https://") or not re.search(r"(?:\.gov\.br|\.leg\.br)(?:/|$)", source.split("/", 3)[2]):
            raise ValueError(f"Fonte não oficial para regra comum nacional: {source}")
    for uf, entry in branch["years"][str(year)].items():
        if uf not in RULES or not re.fullmatch(r"datasets/taxes/ipva/\d{4}/[A-Z]{2}\.json", entry["path"]):
            raise ValueError("Caminho ou UF inválido no manifesto IPVA.")
        body = files.get(entry["path"])
        if body is None or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum ausente/inválido para {uf}.")
        dataset = json.loads(body)
        if dataset.get("schemaVersion") not in {1, 2} or dataset.get("uf") != uf or dataset.get("year") != year:
            raise ValueError(f"Schema/UF/exercício inválido para {uf}.")
        if len(dataset.get("rules", [])) != entry.get("recordCount"):
            raise ValueError(f"Contagem de regras inválida para {uf}.")
        if dataset.get("schemaVersion") == 2:
            for rule in dataset.get("rules", []):
                validate_v2_rule(rule, uf)
        for source in (dataset.get("sourceUrl", ""), dataset.get("baseSourceUrl", "")):
            if not source.startswith("https://") or not re.search(r"(?:\.gov\.br|\.leg\.br|\.al\.sp\.gov\.br)(?:/|$)", source.split("/", 3)[2]):
                raise ValueError(f"Fonte não oficial para {uf}: {source}")


def validate_v2_rule(rule: dict, uf: str = "?") -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(rule.get("id", ""))):
        raise ValueError(f"Identificador de regra inválido em {uf}.")
    priority = rule.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not -10_000 <= priority <= 10_000:
        raise ValueError(f"Prioridade inválida em {uf}.")
    conditions = rule.get("conditions", {})
    if not isinstance(conditions, dict) or "any" in conditions:
        raise ValueError(f"Conditions v2 inválido (OR não suportado) em {uf}.")
    all_conditions = conditions.get("all", [])
    if not isinstance(all_conditions, list):
        raise ValueError(f"Conditions.all inválido em {uf}.")
    for condition in all_conditions:
        if not isinstance(condition, dict) or condition.get("field") not in SUPPORTED_FIELDS or condition.get("operator") not in SUPPORTED_OPERATORS:
            raise ValueError(f"Campo ou operador de condição inválido em {uf}.")
        operator, value = condition["operator"], condition.get("value")
        if operator == "IN":
            valid = isinstance(value, list) and bool(value) and all(isinstance(item, (str, int, float)) and not isinstance(item, bool) for item in value)
        elif operator == "BETWEEN":
            valid = isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value) and value[0] <= value[1]
        elif operator in {"GT", "GTE", "LT", "LTE"}:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = isinstance(value, (str, int, float)) and not isinstance(value, bool)
        if not valid:
            raise ValueError(f"Valor de condição inválido em {uf}.")
    effects = rule.get("effects")
    if not isinstance(effects, list) or not effects:
        raise ValueError(f"Effects v2 ausente em {uf}.")
    rate_count = 0
    rate_seen = False
    exempt_seen = False
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError(f"Effect inválido em {uf}.")
        kind = effect.get("type")
        value = effect.get("value")
        if kind == "RATE":
            rate_count += 1
            rate_seen = True
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 100:
                raise ValueError(f"RATE inválido em {uf}.")
        elif kind == "BASE_REDUCTION":
            if rate_seen or isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"BASE_REDUCTION inválido/fora de ordem em {uf}.")
        elif kind == "EXEMPT":
            exempt_seen = True
            if "value" in effect:
                raise ValueError(f"EXEMPT não aceita value em {uf}.")
        else:
            raise ValueError(f"Effect não suportado em {uf}.")
    if exempt_seen:
        if len(effects) != 1:
            raise ValueError(f"EXEMPT deve ser efeito único em {uf}.")
    elif rate_count != 1:
        raise ValueError(f"Uma regra não isenta precisa exatamente de um RATE em {uf}.")


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
