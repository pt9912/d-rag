# Daten-Plan für Rasa-Dialogmanagement

## Ziel
Trainings- und Testdaten für NLU (Intents/Entities) und Core (Stories/Rules) bereitstellen, um Variante 2 (kontextuelle Gesprächsführung) abzudecken.

## Aktueller Stand
- Basis-NLU-Beispiele für alle Intents/Entities liegen in `rasa/data/nlu.yml`, aber Stückzahlen sind noch deutlich unter Ziel (je Intent bisher <10 Beispiele).
- Stories/Rules für Happy-/Slot-Filling-/Fallback-Flows liegen in `rasa/data/stories.yml` und `rasa/data/rules.yml`.
- Action-Server-Unit-Tests existieren (`rasa/actions/tests/test_actions.py`); NLU/Core/E2E-Tests fehlen noch.

## Quellen
- Bestehende Intent-only Daten (siehe `docs/archive/rasa-intent-only.md`); übernehmen und mit neuen Intents erweitern.
- ADRs/ARCHITECTURE-Dokumente aus dem Repo für Domänenbegriffe (Synonyme/Regex).
- Synthese-Beispiele für Slot-Filling und Nachfragen, manuell kuratiert.

## Umfang & Abdeckung
- Intents: `ask_rag`, `greet`, `goodbye`, `help`, `thank`, `out_of_scope`, `affirm`, `deny`, `provide_topic`, `provide_doc_type`, `provide_role`.
- Entities: `topic`, `doc_type`, `role`, `name` (optional).
- Stories: Happy Path, Slot-Filling (fehlende Topic/DocType), Nachfragen mit History, Fallback-Flows, Abbruch während Form.
- Zielmenge: je Intent 20–40 Beispiele (balanced), je Entity-Variante 15–20 markierte Beispiele; Stories mindestens 2–3 pro Pfad. Aktuell: wenige Beispiele pro Intent → Ausbau nötig.

## Aufbereitung & Qualität
- Annotation in YAML (`data/nlu.yml`, `data/stories.yml`, `data/rules.yml`), Synonyme in `domain.yml`.
- Review durch zweite Person für 4-Augen-Prinzip; Lint via `rasa data validate`.
- Balancing: Out-of-scope und Fallback-Beispiele auf ca. 10–15% der NLU-Daten erhöhen.

## Splits & Tests
- Trainingsdaten als Default; Test-Split über `rasa test` (Cross-Validation) oder explizit `data/test_nlu.yml` für Regression.
- E2E-Beispiele (REST-Payloads) in `data/e2e/` für wiederholbare Integrationstests.
- Offene Aufgaben: Regression-Set (`data/test_nlu.yml`) anlegen, E2E-Beispiele sammeln, `rasa data validate`/`rasa test nlu/core` in CI einbinden.

## Zeitplan (grober Richtwert)
- Woche 1: Sammlung/Annotation neuer Intents & Entities.
- Woche 2: Stories/Rules erstellen, erste `rasa test` Läufe, Balancing.
- Woche 3: Review/Feinschliff, Regression-Set einfrieren.
