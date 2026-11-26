# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a worst-offenders table

Title: Show the agents with the most old tickets

Description: After the per-agent summary, print a short table
of the three agents with the highest old ticket count (agent,
old count, average age hours), so a support lead can see at a
glance whose queue is rotting fastest. Ties should break by
average age, then by agent name. Only named agents are listed;
the `(unassigned)` row is excluded.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct top three for the sample file (Cara with 2 old tickets
and 110.5 average hours, Ana with 2 old tickets and 53.4
average hours, Ben with 1 old ticket); JSON output is
unchanged; a test checks the table rows.

## 2. Add an oldest-tickets table

Title: List the five oldest open tickets

Description: After the per-channel summary, print a short table
of the five oldest open tickets (ticket id, agent, age in hours,
status), so a support lead can work the queue oldest first
without sorting the export by hand. Tickets with no usable
created date are skipped. Ties break by ticket id.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct top five for the sample file (Q-104 at 134.0 hours,
Q-103 at 111.0 hours, Q-106 at 111.0 hours, Q-101 at 87.0
hours, Q-114 at 87.0 hours); JSON output is unchanged; a test
checks the table rows.

## 3. Make the old-ticket limit configurable

Title: Add an --old-hours flag

Description: The old-ticket limit is currently fixed at 72
hours. Add an --old-hours flag that takes a number of hours,
and use it for the old-ticket, unassigned-old-ticket,
stuck-pending-ticket, and stuck-on-hold-ticket checks, the age
bucket boundary, and the per-agent old counts. The default
stays 72 hours, so existing output is unchanged without the
flag.

Difficulty: Easy

Acceptance criteria: with --old-hours 48 the sample flags
Q-102 (64.0 hours old) as an old ticket and the summary shows
7 old tickets; without the flag the sample output is
unchanged; a test covers both cases; README documents the flag.

## 4. Add a priority breakdown

Title: Count old tickets by a priority column when one is present

Description: Support exports often carry a priority column
(`priority`). When that column exists, add a per-priority count
to the summary (priority, open tickets, old tickets), so a team
can see whether the rotting tickets are the urgent ones or the
low-priority ones everyone ignores. When the column is absent,
the report is unchanged.

Difficulty: Easy

Acceptance criteria: a sample file with a priority column shows
the breakdown with the correct counts; without the column no
breakdown appears; a test covers both cases; README documents
the column.
