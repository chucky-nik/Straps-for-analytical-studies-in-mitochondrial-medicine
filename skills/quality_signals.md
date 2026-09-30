# Skill: Сигналы качества источника (quality_signals)

Подгружается CompareAgent и ReviewerAgent. Цель — не принять слабый/рискованный источник за сильное доказательство.

## Журнал (без платного Impact Factor API)

1. `trusted` — площадка из curated whitelist (NEJM, Lancet, JAMA, Nature Medicine, Sci Transl Med и др.).
2. `suspect` — маркеры из curated списка риска / известных predatory-паттернов.
3. `unknown` — всё остальное (не значит «плохо», значит «нет сигнала»).

Правила:
- `suspect` → штраф score, нельзя опираться для `promising`.
- Impact Factor числом **не выдумывать**. Если IF нет в официальном ответе API — пишем unknown/whitelist-эвристику.

## Конфликт интересов (COI)

Если в abstract/notes явно есть conflict/competing interest/sponsored by:
- сохранить цитату в `conflicts_of_interest`;
- при `effect_direction=benefit` добавить info/warning в Reviewer;
- небольшой штраф score (−3), без автоматического «фейка».

## ClinicalTrials.gov статус

Bucket:
- `active` — recruiting / active not recruiting / enrolling…
- `completed` — completed / approved for marketing
- `terminal` — terminated / withdrawn / suspended…
- `other` / `unknown` / `missing`

Правила:
- `terminal` NCT **нельзя** трактовать как доказанную эффективность (−15, потолок, warning/error в review).
- `completed` без публикации результатов ≠ доказанный клинический эффект.
- Live-проверка статуса через API v2 + кэш.

## Retracted

PubMed `Retracted Publication` → запись не включается в выборку.
