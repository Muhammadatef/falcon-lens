---
name: submission-check
description: Verify the submission package before the owner uploads it.
---
# submission-check

1. `make submission`, then check `submission/`: title, description_en/ar (≤600 chars, checked by a script), tools_used.txt (generated), deck ≤20 MB, description doc ≤20 MB, video shot list, CHECKLIST.md.
2. Every number in the deck, doc and README must match `evals/results/published/` (`scripts/check_numbers.py`).
3. No ADP logos or branding, no endorsement wording, and every statistic has a source link.
4. Secret scan and live-URL scan of the whole repo. The repo is public.
5. Open each link in a private window (a manual step for the owner, listed in CHECKLIST.md).
