"""Streamlit UI для Harness (analytical studies in mitochondrial medicine).

Запуск:
  source .venv/bin/activate
  PYTHONPATH=src streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mito_harness.agents.orchestrator import DEFAULT_QUERY, Orchestrator
from mito_harness.catalog import list_diseases
from mito_harness.config import has_llm_api_key, settings
from mito_harness.logging_util import RunLogger

st.set_page_config(
    page_title="Harness — mitochondrial medicine",
    page_icon="🧬",
    layout="wide",
)

st.title("Harness")
st.caption(
    "Analytical studies in mitochondrial medicine · "
    "не медицинская рекомендация"
)

diseases = list_diseases()
disease_labels = {d["id"]: f"{d['id']} — {d['name_ru']}" for d in diseases}

with st.sidebar:
    st.header("Параметры")
    disease_id = st.selectbox(
        "Заболевание",
        options=list(disease_labels.keys()),
        format_func=lambda x: disease_labels[x],
        index=0,
    )
    use_llm = st.toggle(
        "LLM-извлечение",
        value=False,
        help="Медленнее, но точнее структурирует abstracts. Нужен ключ в .env",
    )
    compare_llms = st.toggle(
        "Сравнить две LLM",
        value=False,
        help="Бонус ТЗ: primary vs fallback на нескольких abstracts",
    )
    run_eval = st.toggle(
        "Метрики на gold-разметке",
        value=True,
        help="Считает accuracy study_type / intervention_kind по data/gold_extraction.json",
    )
    max_pubmed = st.slider(
        "Сколько статей брать из PubMed",
        min_value=4,
        max_value=20,
        value=8,
        help="Максимум научных статей из базы PubMed за один запуск. Больше = шире обзор, но дольше.",
    )
    max_ctgov = st.slider(
        "Сколько испытаний брать из ClinicalTrials.gov",
        min_value=2,
        max_value=15,
        value=5,
        help="Максимум клинических испытаний из официального реестра ClinicalTrials.gov. Больше = шире обзор, но дольше.",
    )
    st.caption("Для быстрого теста обычно хватает 8 статей и 5 испытаний.")
    st.divider()
    st.write(f"LLM ключ: {'есть' if has_llm_api_key() else 'нет (.env)'}")
    st.caption("Источники: только PubMed + ClinicalTrials.gov")
    st.caption("Качество: COI · journal whitelist/suspect · NCT status · cache")

query = st.text_area(
    "Исследовательский запрос",
    value=DEFAULT_QUERY if disease_id == "lhon" else (
        f"Сравнение митохондриально-таргетной терапии и стандарта лечения "
        f"при {disease_labels[disease_id].split('—', 1)[-1].strip()} за последние 5 лет"
    ),
    height=120,
)

col_run, col_hint = st.columns([1, 3])
with col_run:
    run = st.button("Запустить Harness", type="primary", width="stretch")
with col_hint:
    st.caption("Прогон: поиск → extract → compare → график → отчёт → reviewer")

if run:
    if not query.strip():
        st.error("Введите запрос")
        st.stop()

    logger = RunLogger()
    orch = Orchestrator(logger)
    progress = st.progress(0, text="Запуск оркестратора…")
    status = st.empty()

    try:
        status.info("Идёт поиск и анализ официальных источников…")
        progress.progress(15, text="Search / Extract / Compare…")
        result = orch.run(
            query.strip(),
            disease_id=disease_id,
            max_pubmed=max_pubmed,
            max_ctgov=max_ctgov,
            use_llm_extract=use_llm,
            compare_llms=compare_llms,
            run_extraction_eval=run_eval,
        )
        progress.progress(85, text="Сохранение артефактов…")
        log_path = settings()["reports_dir"] / f"run_log_{result.disease_id}.json"
        logger.save(log_path)
        progress.progress(100, text="Готово")
    except Exception as e:  # noqa: BLE001
        progress.empty()
        st.exception(e)
        st.stop()

    st.session_state["last_result"] = result.model_dump()
    st.session_state["last_log"] = logger.events
    st.session_state["last_log_path"] = str(log_path)

if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    st.success(
        f"Готово: {result['disease_name']} · "
        f"записей {result['studies_raw_count']} · "
        f"review_ok={result.get('review', {}).get('ok') if result.get('review') else None}"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Извлечено", len(result.get("studies_extracted") or []))
    m2.metric("Направлений", len(result.get("ranking") or []))
    top = (result.get("ranking") or [{}])[0]
    m3.metric("Топ score", f"{top.get('score', 0):.0f}" if top else "—")
    m4.metric("Топ label", (top.get("label") or "—") if top else "—")

    ev = result.get("extraction_eval") or {}
    if ev:
        e1, e2, e3 = st.columns(3)
        e1.metric("Gold n", ev.get("n", "—"))
        e2.metric("Acc. study_type", f"{ev.get('accuracy_study_type', 0):.0%}")
        e3.metric("Acc. kind", f"{ev.get('accuracy_intervention_kind', 0):.0%}")

    studies = result.get("studies_extracted") or []
    n_trusted = sum(1 for s in studies if s.get("journal_quality") == "trusted")
    n_suspect = sum(1 for s in studies if s.get("journal_quality") == "suspect")
    n_terminal = sum(1 for s in studies if s.get("nct_is_terminal"))
    n_coi = sum(1 for s in studies if s.get("conflicts_of_interest"))
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Журналы trusted", n_trusted)
    q2.metric("Suspect", n_suspect)
    q3.metric("NCT terminal", n_terminal)
    q4.metric("COI signals", n_coi)

    tab_report, tab_chart, tab_rank, tab_quality, tab_log = st.tabs(
        ["Отчёт", "График", "Рейтинг", "Качество", "Лог"]
    )

    with tab_report:
        report_path = result.get("report_path")
        if report_path and Path(report_path).exists():
            st.markdown(Path(report_path).read_text(encoding="utf-8"))
        else:
            st.warning("Отчёт не найден")

    with tab_chart:
        fig = result.get("figure_path")
        if fig and Path(fig).exists():
            st.image(fig, width="stretch")
        else:
            st.info("График ещё не построен")

    with tab_rank:
        rows = []
        for r in result.get("ranking") or []:
            rows.append(
                {
                    "направление": r.get("direction_name"),
                    "score": r.get("score"),
                    "label": r.get("label"),
                    "evidence": r.get("evidence_level_best"),
                    "n": r.get("n_studies"),
                    "vs_SoC": "yes" if r.get("claims_superior_to_soc") else "no",
                    "ids": ", ".join((r.get("supporting_ids") or [])[:6]),
                }
            )
        st.dataframe(rows, width="stretch")

    with tab_quality:
        qrows = []
        for s in studies:
            qrows.append(
                {
                    "id": s.get("source_id"),
                    "journal": s.get("journal_name") or "",
                    "jq": s.get("journal_quality") or "",
                    "nct_status": s.get("nct_status") or "",
                    "bucket": s.get("nct_status_bucket") or "",
                    "coi": (s.get("conflicts_of_interest") or "")[:80],
                    "type": s.get("study_type"),
                    "kind": s.get("intervention_kind"),
                }
            )
        st.dataframe(qrows, width="stretch")
        cmp = result.get("llm_compare")
        if cmp:
            st.subheader("Сравнение LLM")
            st.json(cmp)
        elif compare_llms:
            st.info("Сравнение LLM не вернуло данных (нет ключа или abstracts).")

    with tab_log:
        st.caption(st.session_state.get("last_log_path", ""))
        st.json(st.session_state.get("last_log") or [])
        st.write("Skills:", ", ".join(result.get("skills_used") or []))
        st.code(json.dumps(result.get("tool_calls") or [], ensure_ascii=False, indent=2))

else:
    st.info("Выберите заболевание, при необходимости поправьте запрос и нажмите «Запустить Harness».")
    with st.expander("Показать сохранённый отчёт LHON (если есть)"):
        sample = ROOT / "reports" / "report_lhon.md"
        fig = ROOT / "figures" / "ranking_lhon.png"
        if sample.exists():
            st.markdown(sample.read_text(encoding="utf-8")[:4000] + "\n\n…")
        if fig.exists():
            st.image(str(fig), width="stretch")
