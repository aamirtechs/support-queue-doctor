"""Tests for support-queue-doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import support_queue_doctor as sqd

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")

AS_OF = datetime(2026, 11, 17, tzinfo=timezone.utc)

HEADER = ("id,subject,status,agent,channel,created_at,"
          "first_response_at,last_activity_at,resolved_at\n")


def write_csv(content):
    """Write content to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return handle.name


def row(ticket_id="Q-1", status="open", agent="Ana", channel="email",
        created="2026-11-16 09:00", first="2026-11-16 09:30",
        activity="2026-11-16 15:00", resolved=""):
    """Build one CSV row with the standard columns."""
    return ",".join([ticket_id, "Subject", status, agent, channel,
                     created, first, activity, resolved]) + "\n"


def parse(content, as_of=AS_OF):
    """Parse CSV content and return (tickets, findings)."""
    return sqd.parse_csv(write_csv(content), as_of)


def audit(content, **kwargs):
    """Parse CSV content and audit it, returning all findings."""
    tickets, findings = parse(content)
    findings.extend(sqd.audit(tickets, as_of=AS_OF, **kwargs))
    return tickets, findings


def rules(findings):
    """Return the sorted rule names of a findings list."""
    return sorted(item.rule for item in findings)


def summary_for(content, **kwargs):
    """Parse and audit content and return the summary dict."""
    tickets, findings = audit(content, **kwargs)
    return sqd.summarize(tickets, findings, AS_OF,
                          stale_hours=kwargs.get("stale_hours", 48))


class TestParseTimestamp(unittest.TestCase):
    """Timestamp parsing accepts the documented formats."""

    def test_iso_with_space(self):
        parsed = sqd.parse_timestamp("2026-11-16 09:00")
        self.assertEqual(parsed, datetime(2026, 11, 16, 9, 0,
                                         tzinfo=timezone.utc))

    def test_iso_with_z(self):
        parsed = sqd.parse_timestamp("2026-11-16T09:00:00Z")
        self.assertEqual(parsed, datetime(2026, 11, 16, 9, 0,
                                         tzinfo=timezone.utc))

    def test_date_only(self):
        parsed = sqd.parse_timestamp("2026-11-16")
        self.assertEqual(parsed, datetime(2026, 11, 16, 0, 0,
                                         tzinfo=timezone.utc))

    def test_day_month_year(self):
        parsed = sqd.parse_timestamp("16/11/2026 09:00")
        self.assertEqual(parsed, datetime(2026, 11, 16, 9, 0,
                                         tzinfo=timezone.utc))

    def test_month_day_year(self):
        parsed = sqd.parse_timestamp("11/16/2026 09:00")
        self.assertEqual(parsed, datetime(2026, 11, 16, 9, 0,
                                         tzinfo=timezone.utc))

    def test_empty_and_bad_return_none(self):
        self.assertIsNone(sqd.parse_timestamp(""))
        self.assertIsNone(sqd.parse_timestamp("  "))
        self.assertIsNone(sqd.parse_timestamp("not-a-date"))
        self.assertIsNone(sqd.parse_timestamp(None))

    def test_naive_is_read_as_utc(self):
        parsed = sqd.parse_timestamp("2026-11-16 09:00")
        self.assertEqual(parsed.tzinfo, timezone.utc)


class TestParseCsv(unittest.TestCase):
    """CSV parsing, headers, aliases, and data quality findings."""

    def test_header_aliases(self):
        content = ("ticket_id,subject,state,assignee,source,"
                   "created,first_reply_at,last_updated_at,"
                   "resolved\n"
                   + "Q-1,Subject,open,Ana,email,"
                   "2026-11-16 09:00,2026-11-16 09:30,"
                   "2026-11-16 15:00,\n")
        tickets, findings = parse(content)
        self.assertEqual(findings, [])
        self.assertEqual(tickets[0]["id"], "Q-1")
        self.assertEqual(tickets[0]["agent"], "Ana")
        self.assertEqual(tickets[0]["channel"], "email")
        self.assertEqual(tickets[0]["status"], "open")

    def test_bom_header(self):
        content = "\ufeff" + HEADER + row()
        tickets, findings = parse(content)
        self.assertEqual(findings, [])
        self.assertEqual(len(tickets), 1)

    def test_extra_columns_ignored(self):
        content = HEADER.replace("\n", ",priority\n") + \
            row().rstrip("\n") + ",high\n"
        tickets, findings = parse(content)
        self.assertEqual(findings, [])
        self.assertEqual(len(tickets), 1)

    def test_missing_id_column(self):
        content = "subject,status,created_at\nSubject,open," \
            "2026-11-16 09:00\n"
        with self.assertRaises(ValueError) as ctx:
            parse(content)
        self.assertIn("no id", str(ctx.exception))

    def test_missing_created_column(self):
        content = "id,subject,status\nQ-1,Subject,open\n"
        with self.assertRaises(ValueError) as ctx:
            parse(content)
        self.assertIn("no created_at", str(ctx.exception))

    def test_empty_file(self):
        with self.assertRaises(ValueError) as ctx:
            parse("")
        self.assertIn("empty", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ValueError) as ctx:
            sqd.parse_csv("/tmp/does-not-exist-queue.csv", AS_OF)
        self.assertIn("cannot read", str(ctx.exception))

    def test_malformed_row_skipped(self):
        content = HEADER + row() + "Q-2,Subject,open,Ben,chat\n"
        tickets, findings = parse(content)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(rules(findings), ["malformed-row"])
        self.assertEqual(findings[0].severity, "error")

    def test_blank_lines_skipped(self):
        content = HEADER + "\n" + row() + "\n"
        tickets, findings = parse(content)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(findings, [])

    def test_duplicate_ticket_id(self):
        content = HEADER + row("Q-1") + row("Q-1")
        tickets, findings = parse(content)
        self.assertEqual(len(tickets), 2)
        self.assertEqual(rules(findings), ["duplicate-ticket-id"])

    def test_invalid_timestamp(self):
        content = HEADER + row(created="not-a-date")
        tickets, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])
        self.assertIsNone(tickets[0]["created_at"])

    def test_invalid_first_response_timestamp(self):
        content = HEADER + row(first="soon")
        tickets, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])
        self.assertIsNone(tickets[0]["first_response_at"])

    def test_future_timestamp(self):
        content = HEADER + row(created="2026-12-01 09:00")
        tickets, findings = parse(content)
        self.assertEqual(rules(findings), ["future-timestamp"])

    def test_missing_created_at(self):
        content = HEADER + row(created="")
        tickets, findings = parse(content)
        self.assertEqual(rules(findings), ["missing-timestamp"])

    def test_optional_columns_absent(self):
        content = "id,status,agent,channel,created_at\n" \
            "Q-1,open,Ana,email,2026-11-16 09:00\n"
        tickets, findings = parse(content)
        self.assertEqual(findings, [])
        self.assertIsNone(tickets[0]["first_response_at"])
        self.assertIsNone(tickets[0]["last_activity_at"])


class TestAgeRules(unittest.TestCase):
    """Old ticket, age buckets, and the 72 hour boundary."""

    def test_old_ticket_over_72_hours(self):
        content = HEADER + row(created="2026-11-13 09:00",
                               first="2026-11-13 10:00",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("old-ticket", rules(findings))

    def test_ticket_at_exactly_72_hours_is_not_old(self):
        content = HEADER + row(created="2026-11-14 00:00",
                               first="2026-11-14 01:00",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertNotIn("old-ticket", rules(findings))

    def test_young_ticket_is_clean(self):
        content = HEADER + row()
        tickets, findings = audit(content)
        self.assertEqual(findings, [])

    def test_age_buckets(self):
        content = HEADER \
            + row("Q-1", created="2026-11-16 09:00",
                  first="2026-11-16 09:30",
                  activity="2026-11-16 15:00") \
            + row("Q-2", created="2026-11-15 09:00",
                  first="2026-11-15 10:00",
                  activity="2026-11-16 09:00") \
            + row("Q-3", created="2026-11-13 09:00",
                  first="2026-11-13 10:00",
                  activity="2026-11-16 09:00") \
            + row("Q-4", created="2026-11-09 09:00",
                  first="2026-11-09 10:00",
                  activity="2026-11-16 09:00")
        summary = summary_for(content)
        self.assertEqual(summary["age_buckets"],
                         {"0-24h": 1, "24-72h": 1, "72h-7d": 1,
                          "7d+": 1})
        self.assertEqual(summary["old"], 2)

    def test_future_created_ticket_skips_age_checks(self):
        content = HEADER + row(created="2026-12-01 09:00",
                               first="", activity="")
        tickets, findings = audit(content)
        self.assertEqual(rules(findings), ["future-timestamp"])
        self.assertNotIn("old-ticket", rules(findings))

    def test_missing_created_ticket_skips_age_checks(self):
        content = HEADER + row(created="")
        tickets, findings = audit(content)
        self.assertEqual(rules(findings), ["missing-timestamp"])
        self.assertNotIn("old-ticket", rules(findings))


class TestUnassignedRules(unittest.TestCase):
    """Unassigned tickets, young and old."""

    def test_unassigned_old_ticket_is_error(self):
        content = HEADER + row(agent="", created="2026-11-13 09:00",
                               first="", activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("unassigned-old-ticket", rules(findings))
        self.assertIn("old-ticket", rules(findings))
        self.assertNotIn("unassigned-ticket", rules(findings))

    def test_unassigned_young_ticket_is_warning(self):
        content = HEADER + row(agent="", first="",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("unassigned-ticket", rules(findings))
        self.assertNotIn("unassigned-old-ticket", rules(findings))
        warning = [item for item in findings
                   if item.rule == "unassigned-ticket"][0]
        self.assertEqual(warning.severity, "warning")


class TestStuckStatusRules(unittest.TestCase):
    """Pending and on-hold tickets that hide from daily views."""

    def test_stuck_pending_ticket(self):
        content = HEADER + row(status="pending",
                               created="2026-11-12 09:00",
                               first="2026-11-12 10:00",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("stuck-pending-ticket", rules(findings))
        self.assertNotIn("stuck-on-hold-ticket", rules(findings))

    def test_stuck_on_hold_ticket(self):
        content = HEADER + row(status="on-hold",
                               created="2026-11-11 10:00",
                               first="2026-11-11 11:00",
                               activity="2026-11-16 12:00")
        tickets, findings = audit(content)
        self.assertIn("stuck-on-hold-ticket", rules(findings))
        self.assertNotIn("stuck-pending-ticket", rules(findings))

    def test_young_pending_ticket_is_clean(self):
        content = HEADER + row(status="pending")
        tickets, findings = audit(content)
        self.assertEqual(findings, [])

    def test_waiting_status_counts_as_pending(self):
        content = HEADER + row(status="waiting",
                               created="2026-11-12 09:00",
                               first="2026-11-12 10:00",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("stuck-pending-ticket", rules(findings))


class TestFirstResponseRules(unittest.TestCase):
    """First-response breaches and slow first responses."""

    def test_first_response_breach(self):
        content = HEADER + row(created="2026-11-15 09:00",
                               first="",
                               activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertIn("first-response-breach", rules(findings))
        breach = [item for item in findings
                  if item.rule == "first-response-breach"][0]
        self.assertEqual(breach.severity, "error")

    def test_no_breach_within_24_hours(self):
        content = HEADER + row(first="", activity="2026-11-16 09:00")
        tickets, findings = audit(content)
        self.assertNotIn("first-response-breach", rules(findings))

    def test_slow_first_response(self):
        content = HEADER + row(created="2026-11-15 09:00",
                               first="2026-11-16 12:00",
                               activity="2026-11-16 12:00")
        tickets, findings = audit(content)
        self.assertIn("slow-first-response", rules(findings))
        slow = [item for item in findings
                if item.rule == "slow-first-response"][0]
        self.assertEqual(slow.severity, "warning")

    def test_first_response_within_target_is_clean(self):
        content = HEADER + row()
        tickets, findings = audit(content)
        self.assertNotIn("slow-first-response", rules(findings))


class TestStaleRules(unittest.TestCase):
    """Stale tickets with no activity."""

    def test_stale_ticket(self):
        content = HEADER + row(created="2026-11-14 09:00",
                               first="2026-11-14 10:00",
                               activity="2026-11-14 10:00")
        tickets, findings = audit(content)
        self.assertIn("stale-ticket", rules(findings))

    def test_recent_activity_is_not_stale(self):
        content = HEADER + row()
        tickets, findings = audit(content)
        self.assertNotIn("stale-ticket", rules(findings))

    def test_stale_hours_flag(self):
        content = HEADER + row(created="2026-11-14 09:00",
                               first="2026-11-14 10:00",
                               activity="2026-11-14 10:00")
        tickets, findings = audit(content, stale_hours=72)
        self.assertNotIn("stale-ticket", rules(findings))

    def test_missing_activity_falls_back_to_created(self):
        content = HEADER + row(created="2026-11-14 09:00",
                               first="2026-11-14 10:00",
                               activity="")
        tickets, findings = audit(content)
        self.assertIn("stale-ticket", rules(findings))

    def test_summary_stale_count_follows_flag(self):
        content = HEADER + row(created="2026-11-14 09:00",
                               first="2026-11-14 10:00",
                               activity="2026-11-14 10:00")
        summary = summary_for(content, stale_hours=72)
        self.assertEqual(summary["stale"], 0)
        self.assertEqual(summary["per_agent"][0]["stale"], 0)


class TestOverloadRules(unittest.TestCase):
    """Agent overload from open ticket counts."""

    def test_agent_overload(self):
        content = HEADER + "".join(
            row("Q-%d" % number) for number in range(1, 6))
        tickets, findings = audit(content, max_open=4)
        self.assertIn("agent-overload", rules(findings))
        overload = [item for item in findings
                    if item.rule == "agent-overload"][0]
        self.assertEqual(overload.ticket, "Ana")
        self.assertEqual(overload.severity, "error")

    def test_no_overload_at_limit(self):
        content = HEADER + "".join(
            row("Q-%d" % number) for number in range(1, 5))
        tickets, findings = audit(content, max_open=4)
        self.assertNotIn("agent-overload", rules(findings))

    def test_unassigned_tickets_do_not_overload(self):
        content = HEADER + "".join(
            row("Q-%d" % number, agent="") for number in range(1, 6))
        tickets, findings = audit(content, max_open=4)
        self.assertNotIn("agent-overload", rules(findings))

    def test_closed_tickets_do_not_count_toward_load(self):
        content = HEADER + "".join(
            row("Q-%d" % number, status="solved",
                resolved="2026-11-16 12:00")
            for number in range(1, 6))
        tickets, findings = audit(content, max_open=4)
        self.assertNotIn("agent-overload", rules(findings))


class TestDataQualityRules(unittest.TestCase):
    """Date ordering and closed tickets in the queue."""

    def test_resolved_before_created(self):
        content = HEADER + row(resolved="2026-11-12 09:00")
        tickets, findings = audit(content)
        self.assertIn("resolved-before-created", rules(findings))

    def test_first_response_before_created(self):
        content = HEADER + row(first="2026-11-16 08:00")
        tickets, findings = audit(content)
        self.assertIn("first-response-before-created", rules(findings))

    def test_activity_before_created(self):
        content = HEADER + row(activity="2026-11-16 08:00")
        tickets, findings = audit(content)
        self.assertIn("activity-before-created", rules(findings))

    def test_closed_ticket_in_queue(self):
        content = HEADER + row(status="solved",
                               resolved="2026-11-16 12:00")
        tickets, findings = audit(content)
        self.assertIn("closed-ticket-in-queue", rules(findings))
        warning = [item for item in findings
                   if item.rule == "closed-ticket-in-queue"][0]
        self.assertEqual(warning.severity, "warning")

    def test_closed_ticket_skips_age_checks(self):
        content = HEADER + row(status="solved",
                               created="2026-11-01 09:00",
                               first="2026-11-01 10:00",
                               activity="2026-11-01 10:00",
                               resolved="2026-11-02 09:00")
        tickets, findings = audit(content)
        self.assertNotIn("old-ticket", rules(findings))
        self.assertNotIn("stale-ticket", rules(findings))


class TestSummary(unittest.TestCase):
    """Summary counts and the per-agent and per-channel tables."""

    def test_summary_counts(self):
        content = HEADER \
            + row("Q-1", created="2026-11-13 09:00",
                  first="2026-11-13 10:00",
                  activity="2026-11-16 09:00") \
            + row("Q-2", agent="Ben", channel="chat") \
            + row("Q-3", status="solved", agent="Ben",
                  channel="chat", resolved="2026-11-16 12:00")
        summary = summary_for(content)
        self.assertEqual(summary["tickets"], 3)
        self.assertEqual(summary["open"], 2)
        self.assertEqual(summary["old"], 1)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["findings"], 2)

    def test_per_agent_table(self):
        content = HEADER \
            + row("Q-1", created="2026-11-13 09:00",
                  first="2026-11-13 10:00",
                  activity="2026-11-16 09:00") \
            + row("Q-2", agent="Ben", channel="chat") \
            + row("Q-3", agent="", channel="chat")
        summary = summary_for(content)
        agents = {row["agent"]: row for row in summary["per_agent"]}
        self.assertEqual(agents["Ana"]["open"], 1)
        self.assertEqual(agents["Ana"]["old"], 1)
        self.assertEqual(agents["Ben"]["open"], 1)
        self.assertEqual(agents["(unassigned)"]["open"], 1)

    def test_per_channel_table(self):
        content = HEADER \
            + row("Q-1", channel="email") \
            + row("Q-2", channel="chat") \
            + row("Q-3", channel="chat",
                  created="2026-11-15 09:00", first="",
                  activity="2026-11-16 09:00")
        summary = summary_for(content)
        channels = {row["channel"]: row
                    for row in summary["per_channel"]}
        self.assertEqual(channels["email"]["open"], 1)
        self.assertEqual(channels["chat"]["open"], 2)
        self.assertEqual(channels["chat"]["breaches"], 1)

    def test_avg_age(self):
        content = HEADER \
            + row("Q-1", created="2026-11-16 09:00") \
            + row("Q-2", created="2026-11-15 09:00",
                  first="2026-11-15 10:00",
                  activity="2026-11-16 09:00")
        summary = summary_for(content)
        self.assertEqual(summary["avg_age_hours"], 27.0)

    def test_empty_queue_summary(self):
        summary = sqd.summarize([], [], AS_OF)
        self.assertEqual(summary["tickets"], 0)
        self.assertEqual(summary["open"], 0)
        self.assertIsNone(summary["avg_age_hours"])
        self.assertEqual(summary["per_agent"], [])
        self.assertEqual(summary["per_channel"], [])


class TestOutputAndCli(unittest.TestCase):
    """Text and JSON output, and --check and --strict exit codes."""

    def run_main(self, content, argv):
        """Run main on CSV content and capture stdout and exit code."""
        path = write_csv(content)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path] + argv)
        return buffer.getvalue(), code

    def test_sample_file_numbers(self):
        path = os.path.join(EXAMPLES, "queue.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17"])
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Tickets: 18, open: 17, findings: 24, "
                      "errors: 17, warnings: 7", text)
        self.assertIn("Old tickets (over 72 hours): 6", text)
        self.assertIn("Age buckets: 0-24h: 6, 24-72h: 2, "
                      "72h-7d: 6, 7d+: 0", text)

    def test_clean_file(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--check"])
        self.assertEqual(code, 0)
        self.assertIn("Queue is clean.", buffer.getvalue())

    def test_warnings_only_check_and_strict(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--check"])
        self.assertEqual(code, 0)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_check_fails_on_sample(self):
        path = os.path.join(EXAMPLES, "queue.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--check"])
        self.assertEqual(code, 1)

    def test_max_open_flag_adds_overload(self):
        path = os.path.join(EXAMPLES, "queue.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--max-open", "4"])
        self.assertIn("agent-overload", buffer.getvalue())
        self.assertIn("overloaded agents: 1", buffer.getvalue())

    def test_stale_hours_flag(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--stale-hours", "72"])
        self.assertIn("findings: 1, errors: 0, warnings: 1",
                      buffer.getvalue())

    def test_json_output(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(buffer.getvalue())
        self.assertEqual(report["tickets"], 3)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["age_buckets"]["0-24h"], 3)
        self.assertEqual(len(report["per_agent"]), 3)

    def test_out_writes_file(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        out = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False)
        out.close()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main([path, "--as-of", "2026-11-17",
                             "--out", out.name])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "")
        with open(out.name, encoding="utf-8") as handle:
            self.assertIn("Queue is clean.", handle.read())

    def test_bad_as_of(self):
        text, code = self.run_main(HEADER + row(),
                                   ["--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_negative_stale_hours(self):
        text, code = self.run_main(HEADER + row(),
                                   ["--stale-hours", "-1"])
        self.assertEqual(code, 2)

    def test_negative_max_open(self):
        text, code = self.run_main(HEADER + row(),
                                   ["--max-open", "-1"])
        self.assertEqual(code, 2)

    def test_missing_file_exit_code(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sqd.main(["/tmp/does-not-exist-queue.csv"])
        self.assertEqual(code, 2)

    def test_finding_str_format(self):
        finding = sqd.Finding("Q-1", "old-ticket", "error", "too old")
        self.assertEqual(str(finding),
                         "ERROR [old-ticket] Q-1: too old")
        self.assertEqual(finding.as_dict(),
                         {"ticket": "Q-1", "rule": "old-ticket",
                          "severity": "error", "message": "too old"})

    def test_age_bucket_boundaries(self):
        self.assertEqual(sqd.age_bucket(24), "0-24h")
        self.assertEqual(sqd.age_bucket(24.1), "24-72h")
        self.assertEqual(sqd.age_bucket(72), "24-72h")
        self.assertEqual(sqd.age_bucket(72.1), "72h-7d")
        self.assertEqual(sqd.age_bucket(168), "72h-7d")
        self.assertEqual(sqd.age_bucket(168.1), "7d+")


if __name__ == "__main__":
    unittest.main()
