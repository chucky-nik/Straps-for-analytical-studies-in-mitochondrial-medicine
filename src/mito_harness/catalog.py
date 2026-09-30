"""Каталог заболеваний и митохондриально-таргетных направлений.

Любое заболевание из DISEASES можно передать в запрос.
Демо-прогон по умолчанию: LHON.
"""

from __future__ import annotations

from typing import Any


DISEASES: dict[str, dict[str, Any]] = {
    "lhon": {
        "id": "lhon",
        "name_ru": "Наследственная оптическая нейропатия Лебера (LHON)",
        "name_en": "Leber hereditary optic neuropathy",
        "aliases": ["LHON", "Leber optic neuropathy"],
        "pubmed_query": (
            '("Leber hereditary optic neuropathy"[Title/Abstract] OR LHON[Title/Abstract])'
        ),
        "ctgov_query": "Leber hereditary optic neuropathy OR LHON",
        "standard_of_care": (
            "Поддерживающая терапия, отказ от курения/алкоголя; "
            "идебенон (где доступен); генная терапия (lenadogene nolparvovec / LUMEVOQ) в исследованиях"
        ),
        "mito_relevant": ["gene_mtdna", "mitoq", "skq1", "ss31", "nad_precursors"],
    },
    "primary_mito": {
        "id": "primary_mito",
        "name_ru": "Первичные митохондриальные болезни",
        "name_en": "Primary mitochondrial diseases",
        "aliases": ["mitochondrial disease", "MELAS", "MERRF", "NARP"],
        "pubmed_query": (
            '("primary mitochondrial disease"[Title/Abstract] OR '
            '"mitochondrial disorder"[Title/Abstract] OR MELAS[Title/Abstract])'
        ),
        "ctgov_query": "primary mitochondrial disease OR MELAS OR mitochondrial disorder",
        "standard_of_care": (
            "Симптоматическая терапия, кофакторные коктейли (CoQ10, рибофлавин, L-карнитин), "
            "избегание митотоксинов"
        ),
        "mito_relevant": ["mitoq", "skq1", "ss31", "urolithin_a", "nad_precursors", "mito_transplant"],
    },
    "parkinson": {
        "id": "parkinson",
        "name_ru": "Болезнь Паркинсона",
        "name_en": "Parkinson disease",
        "aliases": ["Parkinson's disease", "PD"],
        "pubmed_query": '("Parkinson disease"[MeSH] OR "Parkinson\'s"[Title/Abstract])',
        "ctgov_query": "Parkinson disease mitochondrial OR MitoQ OR elamipretide OR urolithin",
        "standard_of_care": (
            "Леводопа/карбидопа, агонисты дофамина, ингибиторы МАО-B/COMT, "
            "глубокая стимуляция мозга при показаниях"
        ),
        "mito_relevant": ["mitoq", "ss31", "urolithin_a", "nad_precursors"],
    },
    "heart_failure": {
        "id": "heart_failure",
        "name_ru": "Сердечная недостаточность",
        "name_en": "Heart failure",
        "aliases": ["HF", "HFrEF", "HFpEF", "chronic heart failure"],
        "pubmed_query": '("Heart Failure"[MeSH] OR "heart failure"[Title/Abstract])',
        "ctgov_query": "heart failure elamipretide OR MitoQ OR mitochondrial",
        "standard_of_care": (
            "иАПФ/АРНИ, бета-блокаторы, антагонисты МКР, SGLT2i, диуретики, устройства по показаниям"
        ),
        "mito_relevant": ["ss31", "mitoq", "skq1", "nad_precursors"],
    },
    "sarcopenia": {
        "id": "sarcopenia",
        "name_ru": "Саркопения",
        "name_en": "Sarcopenia",
        "aliases": ["age-related muscle loss"],
        "pubmed_query": '(sarcopenia[Title/Abstract] OR "muscle aging"[Title/Abstract])',
        "ctgov_query": "sarcopenia urolithin OR NAD OR mitochondrial",
        "standard_of_care": "Силовые тренировки, достаточный белок, лечение вторичных причин",
        "mito_relevant": ["urolithin_a", "nad_precursors", "mitoq"],
    },
    "iri": {
        "id": "iri",
        "name_ru": "Ишемия-реперфузия",
        "name_en": "Ischemia-reperfusion injury",
        "aliases": ["IRI", "ischemia reperfusion"],
        "pubmed_query": '("reperfusion injury"[MeSH] OR "ischemia-reperfusion"[Title/Abstract])',
        "ctgov_query": "ischemia reperfusion mitochondrial OR elamipretide OR MitoQ",
        "standard_of_care": (
            "Ранняя реперфузия (тромболизис/ЧКВ), стандартная кардио/органопротекция по протоколу"
        ),
        "mito_relevant": ["ss31", "mitoq", "skq1"],
    },
}


THERAPIES: dict[str, dict[str, Any]] = {
    "mitoq": {
        "id": "mitoq",
        "name": "MitoQ",
        "class_ru": "Митохондриально-таргетный антиоксидант",
        "target": "mtROS / CoQ10 analogue (TPP-conjugated)",
        "pubmed_terms": "MitoQ OR mitoquinone",
    },
    "skq1": {
        "id": "skq1",
        "name": "SkQ1",
        "class_ru": "Митохондриально-таргетный антиоксидант",
        "target": "mtROS (plastoquinone conjugate)",
        "pubmed_terms": "SkQ1 OR SkQ OR plastoquinonyl",
    },
    "ss31": {
        "id": "ss31",
        "name": "Elamipretide (SS-31)",
        "class_ru": "Митохондриально-таргетный пептид",
        "target": "cardiolipin / ETC membranes",
        "pubmed_terms": "elamipretide OR SS-31 OR SS31 OR Bendavia",
    },
    "urolithin_a": {
        "id": "urolithin_a",
        "name": "Urolithin A",
        "class_ru": "Модулятор митофагии / биогенеза",
        "target": "mitophagy (PINK1/Parkin axis-related)",
        "pubmed_terms": '"urolithin A" OR urolithin-A',
    },
    "nad_precursors": {
        "id": "nad_precursors",
        "name": "NAD+ precursors (NR/NMN)",
        "class_ru": "Модуляторы биоэнергетики / NAD+",
        "target": "NAD+ pool / sirtuins",
        "pubmed_terms": (
            '"nicotinamide riboside" OR NMN OR "nicotinamide mononucleotide" OR "NAD+ precursor"'
        ),
    },
    "gene_mtdna": {
        "id": "gene_mtdna",
        "name": "mtDNA gene therapy (e.g. LHON)",
        "class_ru": "Генная терапия мтДНК / ядерный трансген",
        "target": "MT-ND4 / allotopic expression",
        "pubmed_terms": (
            '(lenadogene OR LUMEVOQ OR "gene therapy") AND (LHON OR ND4 OR mitochondrial)'
        ),
    },
    "mito_transplant": {
        "id": "mito_transplant",
        "name": "Mitochondrial replacement / transplantation",
        "class_ru": "Замещение / трансплантация митохондрий",
        "target": "organelle replacement",
        "pubmed_terms": (
            '"mitochondrial transplantation" OR "mitochondrial replacement" OR MRT OR "spindle transfer"'
        ),
    },
}


def list_diseases() -> list[dict[str, Any]]:
    return [
        {
            "id": d["id"],
            "name_ru": d["name_ru"],
            "name_en": d["name_en"],
            "standard_of_care": d["standard_of_care"],
        }
        for d in DISEASES.values()
    ]


def resolve_disease(query_or_id: str) -> dict[str, Any] | None:
    """Находит заболевание по id, алиасу или подстроке в запросе."""
    q = (query_or_id or "").strip().lower()
    if not q:
        return None
    if q in DISEASES:
        return DISEASES[q]

    for d in DISEASES.values():
        hay = " ".join(
            [d["id"], d["name_ru"], d["name_en"], *d.get("aliases", [])]
        ).lower()
        if q in hay or any(a.lower() in q for a in d.get("aliases", [])) or d["id"] in q:
            return d
        if d["name_en"].lower() in q:
            return d

    # Русские/английские якоря вне цикла — без путаницы приоритетов
    if "лебер" in q or "lhon" in q:
        return DISEASES.get("lhon")
    if "паркинсон" in q:
        return DISEASES.get("parkinson")
    if "саркопен" in q:
        return DISEASES.get("sarcopenia")
    if "сердечн" in q or "heart failure" in q:
        return DISEASES.get("heart_failure")
    if "ишеми" in q or "реперфуз" in q or "ischemia-reperfusion" in q:
        return DISEASES.get("iri")
    if "митохондриальн" in q and "первичн" in q:
        return DISEASES.get("primary_mito")
    return None


def therapies_for_disease(disease_id: str) -> list[dict[str, Any]]:
    d = DISEASES.get(disease_id)
    if not d:
        return list(THERAPIES.values())
    return [THERAPIES[t] for t in d["mito_relevant"] if t in THERAPIES]
