#!/bin/bash
# Commit and push gate_results/ (called under flock gate/git.lock by the lanes).
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 0
git add research/sidepod_opt/gate_results || exit 0
git diff --cached --quiet && exit 0
git commit -q -m "adjoint gate: $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg"
for i in 1 2 3 4; do git push -q origin HEAD 2>/dev/null && break; sleep $((2**i)); done
