# Changelog

## 1.0.0 - 2026-11-20

Initial release.

* Open support queue snapshot audit over a ticket CSV
  export: tickets older than 72 hours, unassigned old
  tickets, tickets stuck in pending or on-hold statuses,
  first-response breaches, agent overload, and stale
  tickets with no activity.
* Age buckets (0-24h, 24-72h, 72h-7d, 7d+), average age of
  open tickets, and per-agent and per-channel summary
  tables.
* Data quality checks: duplicate ticket ids, malformed rows,
  invalid or future timestamps, missing created dates, and
  impossible date orderings (resolved before created, first
  response before created, activity before created).
* Defensive timestamp parsing (ISO 8601 with or without a
  timezone, plus common day/month/year forms); a bad row is
  reported as a finding and never crashes the run. UTF-8 BOM
  headers and extra columns handled.
* Findings carry a ticket id, a rule name, a severity (error
  or warning), and a message; errors and warnings are counted
  in the summary.
* Text and --json output, --out file output, --stale-hours,
  --max-open, and --as-of thresholds, and a --check CI gate
  that exits 1 on errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
