"""ReviewerAgent: citation + safety + forbidden claims (анти-вред)."""

from __future__ import annotations

import re

from mito_harness.schemas import (
    DirectionLabel,
    DirectionScore,
    ExtractedStudy,
    ReviewIssue,
    ReviewResult,
    StudyType,
)
from mito_harness.skills_loader import load_json_skill, load_skill

_ID_RE = re.compile(
    r"\b("
    r"PMID:?\s*\d+"
    r"|NCT\d{8}"
    r"|10\.\d{4,9}/[^\s,;\"'<>\]#]+"
    r")\b",
    re.I,
)

_DOSE_RE = re.compile(
    r"\b("
    r"\d+\s*mg(?:/kg|/day|/d)?"
    r"|\d+\s*мг(?:/кг|/сут|/день)?"
    r"|take\s+\d+"
    r"|принимать\s+\d+"
    r"|dose of\s+\d+"
    r"|\d+\s*(?:tablets?|capsules?|таблет(?:ки|ок|ку)?)"
    r")\b",
    re.I,
)


def _normalize_id(token: str) -> str:
    t = token.strip()
    t = re.sub(r"^PMID:?\s*", "", t, flags=re.I)
    return t


def review_report(
    report_md: str,
    studies: list[ExtractedStudy],
    ranking: list[DirectionScore] | None = None,
) -> ReviewResult:
    _ = load_skill("citation_checklist")
    _ = load_skill("safety_guardrails")
    rules = load_json_skill("mito_extraction_rules")

    allowed = {s.source_id for s in studies}
    allowed |= {s.doi for s in studies if s.doi}
    verified = sorted(x for x in allowed if x)

    issues: list[ReviewIssue] = []
    found_ids = {_normalize_id(m.group(0)) for m in _ID_RE.finditer(report_md)}

    for fid in found_ids:
        ok = fid in allowed or any(fid in (a or "") for a in allowed)
        if not ok:
            if fid.isdigit() and fid in allowed:
                continue
            if fid.upper().startswith("NCT") and fid.upper() in {a.upper() for a in allowed}:
                continue
            issues.append(
                ReviewIssue(
                    severity="error",
                    claim=fid,
                    reason="ID отсутствует среди официальных результатов этого прогона",
                    action="remove",
                )
            )

    lowered = report_md.lower()

    for phrase in rules.get("forbidden_claims", []):
        if phrase.lower() in lowered:
            issues.append(
                ReviewIssue(
                    severity="error",
                    claim=phrase,
                    reason="Запрещённая клинически опасная / рекламная формулировка (mito_extraction_rules)",
                    action="remove",
                )
            )

    for phrase in rules.get("harmful_overclaim_patterns", []):
        if phrase.lower() in lowered:
            issues.append(
                ReviewIssue(
                    severity="error",
                    claim=phrase,
                    reason="Формулировка может побудить отказаться от стандарта лечения без доказательств",
                    action="remove",
                )
            )

    if _DOSE_RE.search(report_md):
        issues.append(
            ReviewIssue(
                severity="error",
                claim="dosing_language",
                reason="В отчёте обнаружена дозировка/схема приёма — удалить (риск вреда)",
                action="remove",
            )
        )

    # дисклеймер обязателен
    if "не медицинская рекомендация" not in lowered and "not a clinical" not in lowered:
        issues.append(
            ReviewIssue(
                severity="error",
                claim="missing_disclaimer",
                reason="Нет явного дисклеймера «не медицинская рекомендация»",
                action="fix",
            )
        )

    if studies and not found_ids:
        issues.append(
            ReviewIssue(
                severity="warning",
                claim="no_ids_in_report",
                reason="В отчёте нет PMID/NCT/DOI",
                action="fix",
            )
        )

    # overclaim: promising label без опоры
    if ranking:
        for r in ranking:
            if r.label == DirectionLabel.PROMISING and r.n_studies == 0:
                issues.append(
                    ReviewIssue(
                        severity="error",
                        claim=r.direction_name,
                        reason="Ярлык promising при n=0 недопустим",
                        action="fix",
                    )
                )
            if r.claims_superior_to_soc is False and re.search(
                rf"{re.escape(r.direction_name)}.{{0,80}}(лучше|superior|превосход)",
                report_md,
                re.I,
            ):
                issues.append(
                    ReviewIssue(
                        severity="error",
                        claim=f"superiority:{r.direction_id}",
                        reason="Заявлено превосходство над SoC без comparative human evidence",
                        action="fix",
                    )
                )

    # доклиника как клинический proof
    if re.search(r"(доказан[аоы]|proven|clinically effective).{0,40}(у людей|in patients)", report_md, re.I):
        if any(s.study_type == StudyType.PRECLINICAL for s in studies):
            issues.append(
                ReviewIssue(
                    severity="warning",
                    claim="clinical_proof_language",
                    reason="Рядом с доклиникой опасна формулировка клинической доказанности",
                    action="flag",
                )
            )

    # пустая выборка
    if not studies:
        issues.append(
            ReviewIssue(
                severity="error",
                claim="empty_evidence",
                reason="Нет официальных записей — отчёт не должен делать позитивных выводов",
                action="flag",
            )
        )

    # Качество источников: suspect journal / terminal NCT / COI
    for s in studies:
        if s.journal_quality == "suspect":
            issues.append(
                ReviewIssue(
                    severity="warning",
                    claim=f"journal_suspect:{s.source_id}",
                    reason=f"Журнал помечен как suspect ({s.journal_name}) — не опираться на сильные выводы",
                    action="flag",
                )
            )
        if s.nct_is_terminal:
            issues.append(
                ReviewIssue(
                    severity="warning",
                    claim=f"nct_terminal:{s.source_id}",
                    reason=f"NCT статус terminal/withdrawn/suspended ({s.nct_status}) — нельзя трактовать как подтверждённую эффективность",
                    action="flag",
                )
            )
        if s.conflicts_of_interest and s.effect_direction == "benefit":
            issues.append(
                ReviewIssue(
                    severity="info",
                    claim=f"coi:{s.source_id}",
                    reason="В тексте есть сигнал конфликта интересов при заявленном benefit",
                    action="flag",
                )
            )

    # В отчёте нельзя утверждать доказанную эффективность на основании terminal NCT.
    # Слово Efficacy в официальном названии NCT (в библиосписке) — не ошибка.
    claim_re = re.compile(
        r"(доказан[аоы]?\s+эффективн|подтвержд[её]нн?\w*\s+эффективн|"
        r"эффективность\s+доказан|proven\s+efficac|demonstrated\s+efficac|"
        r"confirm(ed|s)?\s+efficac)",
        re.I,
    )
    if claim_re.search(report_md):
        terminals = [s.source_id for s in studies if s.nct_is_terminal]
        for tid in terminals:
            # ищем утверждение в окрестности ID вне markdown-ссылки на сам NCT
            for m in re.finditer(re.escape(tid), report_md):
                if _is_inside_markdown_link(report_md, m.start()):
                    continue
                window = report_md[max(0, m.start() - 120) : m.end() + 120]
                if claim_re.search(window):
                    issues.append(
                        ReviewIssue(
                            severity="error",
                            claim=f"efficacy_with_terminal:{tid}",
                            reason="Утверждение доказанной эффективности опирается на terminated/withdrawn NCT",
                            action="fix",
                        )
                    )
                    break

    # Terminal NCT с effect=benefit в извлечении — отдельный warning (не error для review_ok)
    for s in studies:
        if s.nct_is_terminal and s.effect_direction == "benefit":
            issues.append(
                ReviewIssue(
                    severity="warning",
                    claim=f"benefit_on_terminal:{s.source_id}",
                    reason="У terminal NCT не должно быть effect=benefit — очистить при sanitize",
                    action="flag",
                )
            )

    errors = [i for i in issues if i.severity == "error"]
    return ReviewResult(ok=len(errors) == 0, issues=issues, verified_source_ids=verified)


def _is_inside_markdown_link(text: str, pos: int) -> bool:
    """Грубая проверка: совпадение внутри (...) URL markdown-ссылки."""
    left = text.rfind("](", 0, pos)
    if left < 0:
        return False
    right = text.find(")", pos)
    return right > pos and text.find("\n", pos, right) < 0


def _looks_like_source_id(claim: str) -> bool:
    c = claim.strip()
    if re.fullmatch(r"\d{5,}", c):
        return True
    if re.fullmatch(r"NCT\d{8}", c, re.I):
        return True
    if re.fullmatch(r"10\.\d{4,9}/[^\s]+", c, re.I):
        return True
    return False


def sanitize_report_text(report_md: str, issues: list[ReviewIssue]) -> str:
    """Удаляет/нейтрализует опасные фрагменты по findings ревьюера."""
    text = report_md
    removable = [
        issue
        for issue in issues
        if issue.action == "remove"
        and issue.claim not in {"dosing_language", "missing_disclaimer", "empty_evidence"}
        and not issue.claim.startswith("superiority:")
        and issue.claim.strip()
    ]
    # длинные фразы раньше коротких (иначе «излечивает» ломает «доказано излечивает»)
    removable.sort(key=lambda i: len(i.claim.strip()), reverse=True)

    for issue in removable:
        claim = issue.claim.strip()
        is_id = _looks_like_source_id(claim)
        # ID: убираем также префикс PMID:/DOI:
        if is_id:
            if claim.isdigit():
                pattern = re.compile(rf"(?:PMID:?\s*)?\b{re.escape(claim)}\b", re.I)
            elif claim.upper().startswith("NCT"):
                pattern = re.compile(rf"\b{re.escape(claim)}\b", re.I)
            else:
                pattern = re.compile(rf"(?:DOI:?\s*)?{re.escape(claim)}", re.I)
        else:
            # фразы: без опоры на ASCII \b — иначе кириллица/пробелы ломают замену
            pattern = re.compile(re.escape(claim), re.I)

        def _repl(m: re.Match[str], _text: str = text, _is_id: bool = is_id) -> str:
            # Не трогаем только URL внутри markdown-ссылки ](url)
            if _is_inside_markdown_link(_text, m.start()):
                # для неверифицированного ID в URL — тоже вычищаем
                if _is_id:
                    return "[removed: unverified-id]"
                return m.group(0)
            return "[removed: unsafe/unverified]"

        text = pattern.sub(_repl, text)

    text = _DOSE_RE.sub("[removed: dosing]", text)
    # добить типичные RU/EN дозировки, которые не поймал базовый regex
    text = re.sub(
        r"\b\d+\s*(?:мг(?:/сут|/день)?|таблет(?:ки|ок|ку)?|capsules?|tablets?)\b",
        "[removed: dosing]",
        text,
        flags=re.I,
    )
    return text
