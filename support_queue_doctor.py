"""Support queue health audit CLI.

Reads an open support queue snapshot CSV export and audits
every ticket for queue health problems: tickets older than
72 hours, unassigned old tickets, tickets stuck in pending
or on-hold (the statuses that hide tickets from daily views),
first-response breaches, agent overload, and stale tickets
with no activity. Age buckets and per-agent and per-channel
tables show where the backlog sits and who carries it.

Each problem is a finding with a ticket id, a rule name, a
severity (error or warning), and a message. Errors are
rotting or breached tickets and broken data; warnings are
patterns worth investigating. --check exits 1 when any
error is found, and --strict also fails on warnings.

Timestamps are parsed defensively. A bad timestamp is
reported as a finding and the row is still audited on the
fields that did parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 support_queue_doctor.py examples/queue.csv
    python3 support_queue_doctor.py queue.csv --json --check
    python3 support_queue_doctor.py queue.csv --as-of 2026-11-17
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_STALE_HOURS = 48
DEFAULT_MAX_OPEN = 20
OLD_HOURS = 72
FIRST_RESPONSE_HOURS = 24

RESOLVED_STATUSES = {"solved", "resolved", "closed"}
PENDING_STATUSES = {"pending", "waiting", "awaiting-customer",
                    "awaiting customer"}
ON_HOLD_STATUSES = {"on hold", "on-hold", "hold", "paused"}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one ticket, or for the ticket set."""

    def __init__(self, ticket, rule, severity, message):
        self.ticket = ticket
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"ticket": self.ticket, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.ticket, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def parse_csv(path, as_of):
    """Parse a support queue snapshot CSV export.

    Returns (tickets, findings). Each ticket is a dict with the
    id, status, agent, channel, and the parsed timestamps.
    Rows with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    tickets = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("id", "ticket_id"))
        if id_column is None:
            raise ValueError(
                "%s has no id or ticket_id column (header is: %s)"
                % (path, ", ".join(header)))
        created_column = find_column(
            header, ("created_at", "created", "opened_at"))
        if created_column is None:
            raise ValueError(
                "%s has no created_at column (header is: %s)"
                % (path, ", ".join(header)))
        status_column = find_column(header, ("status", "state"))
        agent_column = find_column(header, ("agent", "assignee",
                                            "agent_name"))
        channel_column = find_column(header, ("channel", "source",
                                              "via"))
        first_column = find_column(
            header, ("first_response_at", "first_reply_at",
                     "first_agent_response_at"))
        activity_column = find_column(
            header, ("last_activity_at", "last_updated_at",
                     "last_update_at", "updated_at"))
        resolved_column = find_column(
            header, ("resolved_at", "resolved", "solved_at"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            ticket_id = cells[id_column] or "row %d" % line_number
            if ticket_id in seen_ids:
                findings.append(Finding(
                    ticket_id, "duplicate-ticket-id", "error",
                    "ticket id appears more than once in the export"))
            else:
                seen_ids.add(ticket_id)
            ticket = {"id": ticket_id,
                      "status": (cells[status_column].lower()
                                 if status_column else ""),
                      "agent": (cells[agent_column]
                                if agent_column else ""),
                      "channel": (cells[channel_column]
                                  if channel_column else ""),
                      "created_at": None,
                      "first_response_at": None,
                      "last_activity_at": None,
                      "resolved_at": None,
                      "line": line_number}
            created_raw = cells[created_column]
            if not created_raw:
                findings.append(Finding(
                    ticket_id, "missing-timestamp", "error",
                    "created_at is empty, so the ticket has no "
                    "open date to measure against"))
            else:
                ticket["created_at"] = parse_timestamp(created_raw)
                if ticket["created_at"] is None:
                    findings.append(Finding(
                        ticket_id, "invalid-timestamp", "error",
                        "created_at %r is not a readable date"
                        % created_raw))
            for column, key, label in (
                    (first_column, "first_response_at",
                     "first_response_at"),
                    (activity_column, "last_activity_at",
                     "last_activity_at"),
                    (resolved_column, "resolved_at", "resolved_at")):
                if column is None:
                    continue
                raw = cells[column]
                if not raw:
                    continue
                parsed = parse_timestamp(raw)
                if parsed is None:
                    findings.append(Finding(
                        ticket_id, "invalid-timestamp", "error",
                        "%s %r is not a readable date"
                        % (label, raw)))
                else:
                    ticket[key] = parsed
            for key, label in (
                    ("created_at", "created_at"),
                    ("first_response_at", "first_response_at"),
                    ("last_activity_at", "last_activity_at"),
                    ("resolved_at", "resolved_at")):
                value = ticket[key]
                if value is not None and value > as_of:
                    findings.append(Finding(
                        ticket_id, "future-timestamp", "error",
                        "%s %s is after the as-of date %s"
                        % (label, value.strftime("%Y-%m-%d %H:%M"),
                           as_of.strftime("%Y-%m-%d %H:%M"))))
            tickets.append(ticket)
    return tickets, findings


def hours_between(start, end):
    """Return the hours from start to end as a float."""
    return (end - start).total_seconds() / 3600.0


def is_open(ticket):
    """Return True when the ticket is still in the open queue."""
    return ticket["status"] not in RESOLVED_STATUSES


def is_pending(ticket):
    """Return True when the ticket sits in a pending status."""
    return ticket["status"] in PENDING_STATUSES


def is_on_hold(ticket):
    """Return True when the ticket sits in an on-hold status."""
    return ticket["status"] in ON_HOLD_STATUSES


def audit(tickets, stale_hours=DEFAULT_STALE_HOURS,
          max_open=DEFAULT_MAX_OPEN, as_of=None, old_hours=OLD_HOURS):
    """Audit a parsed ticket list and return a list of findings."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    findings = []
    for ticket in tickets:
        ticket_id = ticket["id"]
        created = ticket["created_at"]
        first = ticket["first_response_at"]
        activity = ticket["last_activity_at"]
        resolved = ticket["resolved_at"]
        open_flag = is_open(ticket)

        if created is not None and resolved is not None \
                and resolved < created:
            findings.append(Finding(
                ticket_id, "resolved-before-created", "error",
                "resolved_at %s is before created_at %s"
                % (resolved.strftime("%Y-%m-%d %H:%M"),
                   created.strftime("%Y-%m-%d %H:%M"))))
        if created is not None and first is not None \
                and first < created:
            findings.append(Finding(
                ticket_id, "first-response-before-created", "error",
                "first_response_at %s is before created_at %s"
                % (first.strftime("%Y-%m-%d %H:%M"),
                   created.strftime("%Y-%m-%d %H:%M"))))
        if created is not None and activity is not None \
                and activity < created:
            findings.append(Finding(
                ticket_id, "activity-before-created", "error",
                "last_activity_at %s is before created_at %s"
                % (activity.strftime("%Y-%m-%d %H:%M"),
                   created.strftime("%Y-%m-%d %H:%M"))))

        if not open_flag:
            findings.append(Finding(
                ticket_id, "closed-ticket-in-queue", "warning",
                "status is %s but the ticket is still in the "
                "open queue snapshot" % ticket["status"]))
            continue
        if created is None:
            continue
        age = hours_between(created, as_of)
        if age < 0:
            continue
        if age > old_hours:
            findings.append(Finding(
                ticket_id, "old-ticket", "error",
                "ticket has been open for %.1f hours, over the "
                "limit of %d hours" % (age, old_hours)))
        if not ticket["agent"]:
            if age > old_hours:
                findings.append(Finding(
                    ticket_id, "unassigned-old-ticket", "error",
                    "ticket has no agent and has been open for "
                    "%.1f hours, over the limit of %d hours"
                    % (age, old_hours)))
            else:
                findings.append(Finding(
                    ticket_id, "unassigned-ticket", "warning",
                    "ticket has no agent assigned, so nobody "
                    "owns it"))
        if is_pending(ticket) and age > old_hours:
            findings.append(Finding(
                ticket_id, "stuck-pending-ticket", "error",
                "ticket has been pending for %.1f hours, over "
                "the limit of %d hours, so it is hidden from "
                "daily views" % (age, old_hours)))
        if is_on_hold(ticket) and age > old_hours:
            findings.append(Finding(
                ticket_id, "stuck-on-hold-ticket", "error",
                "ticket has been on hold for %.1f hours, over "
                "the limit of %d hours, so it is hidden from "
                "daily views" % (age, old_hours)))
        if first is None:
            if age > FIRST_RESPONSE_HOURS:
                findings.append(Finding(
                    ticket_id, "first-response-breach", "error",
                    "ticket has had no first response after "
                    "%.1f hours, over the target of %d hours"
                    % (age, FIRST_RESPONSE_HOURS)))
        elif first >= created:
            wait = hours_between(created, first)
            if wait > FIRST_RESPONSE_HOURS:
                findings.append(Finding(
                    ticket_id, "slow-first-response", "warning",
                    "first response came %.1f hours after the "
                    "ticket opened, over the target of %d hours"
                    % (wait, FIRST_RESPONSE_HOURS)))
        last_seen = activity if activity is not None else created
        idle = hours_between(last_seen, as_of)
        if idle > stale_hours:
            findings.append(Finding(
                ticket_id, "stale-ticket", "warning",
                "ticket has had no activity for %.1f hours, "
                "over the limit of %d hours"
                % (idle, stale_hours)))
    open_counts = {}
    for ticket in tickets:
        if not is_open(ticket) or not ticket["agent"]:
            continue
        open_counts[ticket["agent"]] = \
            open_counts.get(ticket["agent"], 0) + 1
    for agent in sorted(open_counts):
        count = open_counts[agent]
        if count > max_open:
            findings.append(Finding(
                agent, "agent-overload", "error",
                "%s has %d open tickets, over the limit of %d"
                % (agent, count, max_open)))
    return findings


def age_bucket(age, old_hours=OLD_HOURS):
    """Return the age bucket label for an age in hours."""
    if age <= 24:
        return "0-24h"
    if age <= old_hours:
        return "24-72h"
    if age <= 168:
        return "72h-7d"
    return "7d+"


def summarize(tickets, findings, as_of,
              stale_hours=DEFAULT_STALE_HOURS, old_hours=OLD_HOURS):
    """Return the summary counts for a ticket list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    rule_counts = {}
    for item in findings:
        rule_counts[item.rule] = rule_counts.get(item.rule, 0) + 1
    open_tickets = [ticket for ticket in tickets
                    if is_open(ticket)]
    buckets = {"0-24h": 0, "24-72h": 0, "72h-7d": 0, "7d+": 0}
    ages = []
    for ticket in open_tickets:
        created = ticket["created_at"]
        if created is None:
            continue
        age = hours_between(created, as_of)
        if age < 0:
            continue
        buckets[age_bucket(age, old_hours)] += 1
        ages.append(age)
    per_agent = {}
    for ticket in open_tickets:
        agent = ticket["agent"] or "(unassigned)"
        row = per_agent.setdefault(agent, {
            "agent": agent, "open": 0, "old": 0, "stale": 0,
            "ages": []})
        row["open"] += 1
        created = ticket["created_at"]
        if created is None:
            continue
        age = hours_between(created, as_of)
        if age < 0:
            continue
        row["ages"].append(age)
        if age > old_hours:
            row["old"] += 1
        last_seen = ticket["last_activity_at"] \
            if ticket["last_activity_at"] is not None else created
        if hours_between(last_seen, as_of) > stale_hours:
            row["stale"] += 1
    agents = []
    for row in sorted(per_agent.values(),
                      key=lambda item: item["agent"]):
        agent_ages = row.pop("ages")
        row["avg_age_hours"] = (
            round(sum(agent_ages) / len(agent_ages), 1)
            if agent_ages else None)
        agents.append(row)
    per_channel = {}
    for ticket in open_tickets:
        channel = ticket["channel"] or "(no channel)"
        row = per_channel.setdefault(channel, {
            "channel": channel, "open": 0, "old": 0, "breaches": 0})
        row["open"] += 1
        created = ticket["created_at"]
        if created is None:
            continue
        age = hours_between(created, as_of)
        if age < 0:
            continue
        if age > old_hours:
            row["old"] += 1
        if ticket["first_response_at"] is None \
                and age > FIRST_RESPONSE_HOURS:
            row["breaches"] += 1
    channels = sorted(per_channel.values(),
                      key=lambda item: item["channel"])
    total = len(tickets)
    return {"tickets": total,
            "open": len(open_tickets),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "old": rule_counts.get("old-ticket", 0),
            "unassigned_old": rule_counts.get(
                "unassigned-old-ticket", 0),
            "stuck_pending": rule_counts.get(
                "stuck-pending-ticket", 0),
            "stuck_on_hold": rule_counts.get(
                "stuck-on-hold-ticket", 0),
            "first_response_breaches": rule_counts.get(
                "first-response-breach", 0),
            "stale": rule_counts.get("stale-ticket", 0),
            "overloaded_agents": rule_counts.get(
                "agent-overload", 0),
            "age_buckets": buckets,
            "avg_age_hours": round(sum(ages) / len(ages), 1)
            if ages else None,
            "per_agent": agents,
            "per_channel": channels}


def render_text(tickets, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Tickets: %(tickets)d, open: %(open)d, "
                 "findings: %(findings)d, errors: %(errors)d, "
                 "warnings: %(warnings)d" % summary)
    lines.append("Old tickets (over %(old_limit)d hours): %(old)d, "
                 "unassigned old: %(unassigned_old)d, stuck "
                 "pending: %(stuck_pending)d, stuck on hold: "
                 "%(stuck_on_hold)d" % dict(
                     summary, old_limit=summary.get("old_limit", OLD_HOURS)))
    lines.append("First-response breaches: "
                 "%(first_response_breaches)d, stale tickets: "
                 "%(stale)d, overloaded agents: "
                 "%(overloaded_agents)d" % summary)
    buckets = summary["age_buckets"]
    lines.append("Age buckets: 0-24h: %(0-24h)d, 24-72h: "
                 "%(24-72h)d, 72h-7d: %(72h-7d)d, 7d+: %(7d+)d"
                 % buckets)
    if summary["avg_age_hours"] is None:
        lines.append("Average age of open tickets: none")
    else:
        lines.append("Average age of open tickets: %.1f hours"
                     % summary["avg_age_hours"])
    lines.append("")
    lines.append("Per-agent summary:")
    lines.append("%-12s %5s %4s %6s %9s"
                 % ("agent", "open", "old", "stale", "avg hours"))
    for row in summary["per_agent"]:
        avg = ("%.1f" % row["avg_age_hours"]
               if row["avg_age_hours"] is not None else "-")
        lines.append("%-12s %5d %4d %6d %9s"
                     % (row["agent"], row["open"], row["old"],
                        row["stale"], avg))
    top_old = sorted(
        (row for row in summary["per_agent"]
         if row["agent"] != "(unassigned)" and row["old"] > 0),
        key=lambda row: (
            -row["old"],
            -(row["avg_age_hours"]
              if row["avg_age_hours"] is not None else -1.0),
            row["agent"],
        ),
    )[:3]
    if top_old:
        lines.append("")
        lines.append("Agents with most old tickets:")
        lines.append("%-12s %4s %9s" % ("agent", "old", "avg hours"))
        for row in top_old:
            avg = ("%.1f" % row["avg_age_hours"]
                   if row["avg_age_hours"] is not None else "-")
            lines.append("%-12s %4d %9s"
                         % (row["agent"], row["old"], avg))
    lines.append("")
    lines.append("Per-channel summary:")
    lines.append("%-12s %5s %4s %9s"
                 % ("channel", "open", "old", "breaches"))
    for row in summary["per_channel"]:
        lines.append("%-12s %5d %4d %9d"
                     % (row["channel"], row["open"], row["old"],
                        row["breaches"]))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("Queue is clean.")
    return "\n".join(lines) + "\n"


def render_json(tickets, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="support-queue-doctor",
        description="Audit an open support queue snapshot CSV "
                    "for old, unassigned, stuck, breached, and "
                    "stale tickets.")
    parser.add_argument("csv_file", help="queue CSV export to audit")
    parser.add_argument("--old-hours", type=int,
                        default=OLD_HOURS,
                        help="an open, pending, or on-hold ticket older "
                        "than this many hours is flagged as old "
                        "(default: %d)" % OLD_HOURS)
    parser.add_argument("--stale-hours", type=int,
                        default=DEFAULT_STALE_HOURS,
                        help="a ticket with no activity for more "
                        "than this many hours is stale "
                        "(default: %d)" % DEFAULT_STALE_HOURS)
    parser.add_argument("--max-open", type=int,
                        default=DEFAULT_MAX_OPEN,
                        help="most open tickets allowed per agent "
                        "before overload is flagged "
                        "(default: %d)" % DEFAULT_MAX_OPEN)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-17 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.old_hours < 0:
        print("error: --old-hours must be at least 0",
              file=sys.stderr)
        return 2
    if args.stale_hours < 0:
        print("error: --stale-hours must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_open < 0:
        print("error: --max-open must be at least 0",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        tickets, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(tickets,
                          stale_hours=args.stale_hours,
                          max_open=args.max_open,
                          as_of=as_of,
                          old_hours=args.old_hours))
    summary = summarize(tickets, findings, as_of,
                        stale_hours=args.stale_hours,
                        old_hours=args.old_hours)
    if args.json:
        report = render_json(tickets, findings, summary)
    else:
        summary_for_text = dict(summary, old_limit=args.old_hours)
        report = render_text(tickets, findings, summary_for_text)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
