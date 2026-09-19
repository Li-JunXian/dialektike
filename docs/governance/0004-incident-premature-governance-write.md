# Governance record 0004 — incident: governance file written before any go

Date of incident: 2026-07-13. Recorded: 2026-07-13, inside WP v2.4 (the first
package authorized after the incident), per Live's instruction.

## What happened

While cross-examining Codex audit R8 — with **no active work package and no go
from Live** — Claude (executor) created `docs/governance/0003-modularity-plug-and-play.md`
in the repository, recording Live's plug-and-play modularity requirement verbatim.

Codex flagged it in the same round: the repository was no longer unchanged
(`?? docs/governance/0003-...md`), and a filesystem write is a work-package
action regardless of intent or commit status.

## Claude's account (no defense entered)

The write followed the anti-erasure bookkeeping pattern of record 0002 — but 0002
was written *inside* an approved work package (v2.3). That cover did not exist
here. Incident 0001 already established the standard: explicit go per work
package. This is a second, smaller deviation from the same rule. Conceded.

## Live's ruling

> I accept the substance of governance 0003, but you created its file before
> receiving my explicit GO; record that as a process deviation and leave it
> uncommitted pending this package.

## Disposition

- 0003 was left uncommitted and untouched until WP v2.4 received Live's
  conditional GO; it is revised (per Codex R8 amendments Live endorsed) and
  committed *within* v2.4, together with this record.
- Standing rule restated for the executor: between work packages, the only
  automatic writes are session memory/bookkeeping **outside the repository**.
  Every write inside `/Users/live/dialektike/` — including governance records —
  waits for the package go, and rulings arriving between packages are recorded
  as part of the next authorized package.
