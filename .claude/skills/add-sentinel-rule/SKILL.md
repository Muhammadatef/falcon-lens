---
name: add-sentinel-rule
description: Add a deterministic Sentinel trigger rule.
---
# add-sentinel-rule

1. Add an entry to `services/sentinel/rules.yaml`: id, type (an incident.type enum value), window, conditions over correlation keys and counts, severity_floor.
2. Unit test in `services/sentinel/tests/test_rules.py`, using a synthetic event list built from `tests/factories.py`: it must fire and must not fire, and it must be idempotent on replay.
3. Add the metric label `fl_rule_fired_total{rule}` (automatic) and a RUNBOOK anchor if it alerts.
4. Run the Sentinel replay eval (`make eval-sentinel`). Incident precision must not drop.
