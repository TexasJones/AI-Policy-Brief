#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
for t in tests/test_*.py; do echo "== $t"; python3 "$t" | tail -1; done
python3 -m ai_policy_brief.generate --sample --out /tmp/apb_check.html --subject-out /tmp/apb_check.txt > /dev/null && echo "sample render OK"
