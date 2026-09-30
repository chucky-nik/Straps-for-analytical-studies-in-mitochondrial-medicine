# Harness — analytical studies in mitochondrial medicine (ANTEI × ИТМО)

Исследовательский прототип по архитектуре **Harness** (оркестратор → субагенты → tools → skills):  
экспресс-обзор митохондриально-таргетных направлений **vs** стандарт лечения по официальным источникам.

> **Не медицинская рекомендация.** Не начинайте и не отменяйте терапию по этому отчёту.

## Что делает система

1. Ищет литературу в **PubMed** и испытания в **ClinicalTrials.gov**
2. Извлекает структуру в Pydantic-схему (эвристики и/или LLM)
3. Сравнивает направления (score / label), строит график
4. Пишет Markdown-отчёт и прогоняет **Reviewer** (анти-галлюцинации + анти-вред)

**Источник истины:** только ответы API. LLM не добавляет PMID/NCT/цифры «из памяти».

## Схема

```
Запрос
  → Orchestrator (план + лог)
      → SearchAgent     pubmed_search, clinicaltrials_search
      → ExtractAgent    parse_annotation_to_schema + evidence_levels
      → CompareAgent    prospect_criteria, quality_signals, safety
      → VizAgent        plot_direction_ranking
      → Report + ReviewerAgent (citation_checklist, sanitize)
  → reports/report_*.md + figures/ranking_*.png
```

## Заболевания

| id | Заболевание |
|----|-------------|
| `lhon` | LHON (демо по умолчанию) |
| `primary_mito` | Первичные митохондриальные болезни |
| `parkinson` | Болезнь Паркинсона |
| `heart_failure` | Сердечная недостаточность |
| `sarcopenia` | Саркопения |
| `iri` | Ишемия-реперфузия |

## Быстрый старт

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # NEURAL_DEEP_API_KEY и/или LLM7_API_KEY
```

```bash
export PYTHONPATH=src
python main.py --list-diseases
python main.py                              # демо LHON
python main.py --disease parkinson
python main.py --no-llm-extract             # только API + эвристики
python main.py --compare-llms               # бонус: primary vs fallback LLM
```

### Streamlit UI

```bash
PYTHONPATH=src streamlit run app/streamlit_app.py
```

Вкладки: отчёт · график · рейтинг · качество · лог.

### Готовые демо-артефакты

- `reports/report_lhon.md` (+ другие заболевания)
- `figures/ranking_lhon.png` (+ другие)

## Tools

| Tool | Назначение |
|------|------------|
| `pubmed_search` | NCBI E-utilities, skip retracted |
| `clinicaltrials_search` | ClinicalTrials.gov API v2 |
| `parse_annotation_to_schema` | abstract → Pydantic + sanitize |
| `plot_direction_ranking` | график сравнения направлений |
| кэш | `cache/` (локально, не в git) |

## Skills (runtime)

- `evidence_levels.md` — шкала A–D  
- `prospect_criteria.md` — перспективность и потолки score  
- `citation_checklist.md` — проверка ID / цитат  
- `mito_extraction_rules.json` — мито-агенты, SoC, forbidden claims  
- `safety_guardrails.md` — анти-вред  
- `quality_signals.md` — COI, journal trusted/suspect, NCT status  

## Безопасность и анти-галлюцинации

Reviewer / sanitize:

- неизвестные PMID / NCT / DOI → удаление  
- дозировки, «излечивает», «замените SoC», advice пациенту → блокировка  
- обязательный дисклеймер  
- эффект без опоры в abstract / выдуманные % → `null`  
- ClinicalTrials.gov без результатов → не считается эффективностью  
- terminal / withdrawn NCT → штраф, не `promising`  
- suspect journal → пропорциональный штраф к score  
- retracted PubMed → skip  

```bash
PYTHONPATH=src python scripts/audit_report.py reports/report_lhon.md
PYTHONPATH=src python scripts/test_safety_logic.py
```

## Бонусы ТЗ

- кэш API  
- метрики извлечения: `data/gold_extraction.json` + `scripts/eval_extraction.py`  
- dual-LLM: `python main.py --compare-llms` / `scripts/compare_llms.py`  
- сигналы качества источника (COI / journal / NCT)  

## Структура репозитория

```
app/streamlit_app.py
main.py
src/mito_harness/             # пакет реализации
skills/
data/gold_extraction.json
reports/report_*.md
figures/ranking_*.png
scripts/audit_report.py
scripts/test_safety_logic.py
scripts/eval_extraction.py
scripts/compare_llms.py
```

## Ограничения

| Ограничение | Как смягчаем |
|-------------|--------------|
| Галлюцинации ссылок/цифр | Только ID из API; Reviewer; `null` вместо домысла |
| Не systematic review | Явные limitations в отчёте |
| Bias поиска | Каталог disease × therapy |
| Доклиника ≠ клиника | evidence_levels + потолки score |
| Советы пациентам | forbidden claims + дисклеймер |

## Стек

Python 3.11+, Pydantic, httpx, matplotlib, Streamlit, OpenAI-compatible LLM (Neural Deep → llm7 fallback).
