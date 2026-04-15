# KMS Development Runbook

This directory tracks milestone execution, parallel agent coordination, and mandatory review gates.

## Workflow

1. Implement the current milestone only.
2. Run the main-agent review for that milestone.
3. Record findings in `review-log.md`.
4. Fix all accepted findings.
5. Mark the milestone as approved in `stage-status.md`.
6. Move to the next milestone.

## Files

- `stage-status.md`: milestone status board and exit criteria
- `agent-board.md`: sub-agent ownership and handoff notes
- `review-log.md`: review findings and fix tracking
