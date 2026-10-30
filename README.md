# calque

[![Build](https://github.com/agilezebra/calque/actions/workflows/build.yml/badge.svg)](https://github.com/agilezebra/calque/actions/workflows/build.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=agilezebra_calque&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=agilezebra_calque)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=agilezebra_calque&metric=coverage)](https://sonarcloud.io/summary/new_code?id=agilezebra_calque)

Mirrors events between calendars as **anonymized busy blocks**, using your **local macOS calendar store**.
Built for the case where your availability has to show up on calendars in different tenants (e.g. keeping a client Exchange calendar and your company Google calendar in sync) without exposing undesirable event detail.

By design, this is **not** a cloud service. Because calendars are already subscribed in macOS, calque talks only to the local EventKit store. There is **no authentication** required against any of the calendar providers, and no use of their APIs. This makes it suitable for use with **government clients** and other sensitive tenants that **forbid third-party tool** access.

> [!TIP]
>
> ## TL;DR
>
> Get running on macOS in a few commands (see [Getting started](#getting-started) for the detail):
>
> (Assuming you have [brew](https://brew.sh) and Python 3.13+ installed)
>
> ```sh
> brew install uv          # skip if you already have uv
> uv tool install calque   # install from PyPI, isolated and on your PATH
> calque --list-calendars  # find your calendars' account-qualified names
>
> # Mirror your work and client calendars against each other, showing the real
> # subject in your own work diary while the client sees only opaque busy blocks.
> # Replace Work.Calendar and Client.Calendar with your names from --list-calendars.
> calque Work.Calendar Client.Calendar \
>   --title-to Work.Calendar "{account}: {title}" --dry-run      # preview the plan
> calque Work.Calendar Client.Calendar \
>   --title-to Work.Calendar "{account}: {title}"                # apply it once
> calque Work.Calendar Client.Calendar \
>   --title-to Work.Calendar "{account}: {title}" --install 120  # then every 120s
> ```

## What it does

- Reads events from the calendars you specify, in a configurable time window around the current time. The **first** calendar
  you list is the **primary**; the rest are mirrored against it.
- Mirrors only the events you've **accepted** (or that have an unknown response); tentative, declined, and
  pending are skipped by default. The set of statuses that count as busy is configurable with `--statuses`.
- Drops any event an **exclusion rule** rejects: by title pattern, time, or because the target
  calendar is already busy over that slot (see [Exclusions](#exclusions)).
- Writes one block per mirrored event with a **templated title**
  (default `Busy ({account} calendar)`); no attendees, no joining info, no location, no notes beyond a hidden opaque marker.
- **Collects then fans out**: each calendar's events are mirrored into the primary, so the primary
  acts as a hub and holds the full picture, and the primary is then mirrored back out to each of the others, so time
  you've committed with one client shows as busy (anonymized) to the rest. Pass `--mute <CALENDAR>` to
  keep a calendar from *receiving* blocks while still reading it as a source.
- Re-runs are **idempotent**: each block carries a hidden marker linking it to its source event
  and origin calendar, so calque updates times that moved, removes blocks whose source disappeared
  (unless that would exceed `--max-deletes`), and never mirrors a block back to the calendar it came from.

## Getting started

### Prerequisites

- macOS
- every calendar you want to sync already subscribed in Calendar.app.
- Python 3.13 or later.
- Something to install Python packages: calque is a standard Python package — `uv`, `pipx` or `pip` all install it.

[`uv`](https://uv.io) or [`pipx`](https://pipx.pypa.io/) is recommended for a command-line tool,
as it puts calque in an isolated environment on your `PATH`:

```sh
uv tool install calque
# or
pipx install calque
```

To install from a checkout of this repository, point any of them at the directory, e.g. `uv tool install .`

### Grant Access and View Calendars

EventKit is gated by macOS privacy controls. Run calque with `--list-calendars` once interactively: the first
run triggers a permission prompt; you grant access via a Ui dialog which is thereafter managed under
**System Settings → Privacy & Security → Calendars** for the app running calque.
In the first instance, this is your terminal. If you install calque as a `launchd` agent, the agent will not run under
the terminal and will ask separately for permission.
Once granted, you can list every calendar's **account-qualified name** with:

```sh
calque --list-calendars
```

The output is every calendar's **account-qualified name** (`Account.Calendar`). This is an example of the output you might see:

```text
Acme Consulting.Acme Consulting
Acme Consulting.Holidays in the United Kingdom
MoM.Calendar
MoSW.Birthdays
MoSW.Calendar
MoSW.United Kingdom holidays
Other.Birthdays
Subscribed Calendars.UK Holidays
iCloud.Home
iCloud.Personal
```

These qualified names are the form calque accepts: use them exactly as printed wherever a
calendar is named, quoting any that contain spaces.

### Dry Run

Always dry-run first: calque logs the exact plan (what it would create, update, and delete in each
calendar) and writes nothing. The first calendar is the primary; the rest are mirrored
against it.

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" "MoM.Calendar" "iCloud.Home" \
  --title-to "Acme Consulting.Acme Consulting" "{account}: {title}" \
  --title-from "iCloud.Home" "Busy" \
  --calendar-include-patterns "iCloud.Home" "\bGraham busy\n" \
  --mute "iCloud.Home" \
  --dry-run
```

This is a typical consultant setup. `Acme Consulting.Acme Consulting` is your company calendar (the
hub), `MoSW.Calendar` and `MoM.Calendar` are two client tenants, and `iCloud.Home` is your personal
calendar you share with your partner. It mirrors all three into your company calendar, then fans your company calendar's combined availability back out to the two clients:

- `--title-to "Acme Consulting.Acme Consulting" "{account}: {title}"`: in your company
  diary, show the real source account and subject, so you and your colleagues can see what each block is and where you are busy.
- `--title-from "iCloud.Home" "Busy"`: anything originating from your **personal** calendar is
  labelled just `Busy` wherever it lands, so home detail never leaks — not even into your company
  diary, which the `--title-to` rule would otherwise make detailed (a source `--title-from` override wins over a
  target `--title-to` one).
- `--calendar-include-patterns "iCloud.Home" "\bGraham busy\n"`: treat the shared personal calendar as a
  whitelist-only calendar, so only its events whose title carries the `Graham busy` marker (e.g.
  `House Viewing (Graham busy)`) are mirrored at all. Day-to-day home entries stay out of your work
  diary; just the few commitments you've deliberately flagged show as busy. Without this, *every*
  accepted home event would mirror across.
- Client calendars (`MoSW.Calendar`, `MoM.Calendar`) see only the default opaque `Busy (Acme Consulting calendar)` blocks, so neither sees the other's events, your home detail, or anything beyond the fact that you're busy.
- `--mute "iCloud.Home"`: read your personal calendar as a source but never write blocks into it;
  it stays untouched.

The two clients (`MoSW.Calendar`, `MoM.Calendar`) receive only the default opaque `Busy (…)` blocks,
so neither sees the other's events, your home detail, or anything beyond the fact that you're busy.

When the plan looks right, drop `--dry-run` to apply it once, or install it as an agent to keep both
sides in sync (next step).

### Install Agent

Schedule calque to run automatically with `launchd`. calque installs its own lanunchd agent:
pass `--install SECONDS` with the same arguments you previously (dry-)ran, and it writes and loads the
agent for you (no plist to edit):

When the agent first runs from launchd, it will prompt for calendar access via a system dialog.
This will show up as `python3.x` this time, instead of terminal.
You will also get a notification of Managed Login Items Added to indicate that the agent has been installed; this will show as `calque` in System Settings → General → Login Items.

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" "MoM.Calendar" "iCloud.Home" \
  --title-to "Acme Consulting.Acme Consulting" "{account}: {title}" \
  --title-from "iCloud.Home" "Busy" \
  --mute "iCloud.Home" \
  --install 180          # run every 3 minutes
```

The agent logs to `~/Library/Logs/calque.log`. calque rotates that file itself at 1 MB and keeps
3 backups (`calque.log.1` to `calque.log.3`), so the log stays under about 4 MB. Passes with no
changes are logged at debug level, so idle runs barely grow the log at the default `info` level.
Output from before logging starts, such as a startup traceback, goes to
`~/Library/Logs/calque.launchd.log`. To log somewhere else, pass `--log-file` with `--install`.
The path must be absolute, because the agent doesn't run from your current directory. If the log
file can't be opened, calque logs to `calque.launchd.log` and the sync still runs.

An agent installed by an earlier version of calque still writes to an unrotated log. Run the
same `--install` command again to replace it.

Remove it with:

```sh
calque --uninstall
```

### Failure alerts

By default, a failed agent run shows up only in the agent's log (`~/Library/Logs/calque.log`, or
the `--log-file` you set). To be alerted as well, use one or both of the options below. They apply to a sync run, and
`--install` passes them on to the agent.
A run counts as failed when calque reports an error (a calendar not found, a write EventKit refuses,
a pass skipped by `--max-deletes`) or hits an unexpected one, which is also logged with its traceback.

`--notify-on-failure` posts a macOS notification with the failure message:

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" \
  --notify-on-failure \
  --install 180
```

The notification comes from the Python interpreter running calque, so on first use it appears
under that name (e.g. `python3.x`) in **System Settings → Notifications**, where you can allow it or
change how it's shown.

`--on-failure COMMAND` runs a command you choose, in place of the notification or alongside it. calque appends the failure
message as the command's last argument, so tools that take the message last work directly.
`--install` records your shell's `PATH` in the agent, so a command found by name when you install
(such as one from Homebrew) is found by the scheduled runs too:

```sh
# a notification with terminal-notifier (brew install terminal-notifier)
calque ... --on-failure "terminal-notifier -title calque -message"

# a push to your phone via ntfy
calque ... --on-failure "ntfy publish my-calque-alerts"

# your own script, which receives the message as $1
calque ... --on-failure "$HOME/bin/calque-failed.sh"
```

```sh
#!/bin/sh
# ~/bin/calque-failed.sh
echo "$(date): $1" >> "$HOME/calque-failures.txt"
```

The command is split into words like a shell would, but it is **not** run through a shell, so
pipes, redirects and `$VARIABLES` inside it are not expanded; put anything like that in a script.
Your own shell still expands variables in a double-quoted value before calque sees it, as with
`"$HOME/bin/…"` above, so don't single-quote a value that relies on one. A command calque can't
split (an unclosed quote) or a blank one is rejected when you run or `--install` it.
If the alert itself fails (the command is missing, exits non-zero or takes longer than 30 seconds),
calque logs a warning and still exits non-zero for the original failure.

## Options

- **`calendars`** (positional, two or more): the calendars to sync, each a qualified name from
  `--list-calendars`. The **first** is your primary calendar: every other is mirrored into it,
  and it is then mirrored back out to each.
- **`--title TEMPLATE`**: default title template for every mirror block (default
  `Busy ({account} calendar)`). `{field}` placeholders are filled from the source event; see
  [Titles](#titles).
- **`--title-to NAME TEMPLATE`**: title template used when writing **into** NAME's calendar.
  Repeatable.
- **`--title-from NAME TEMPLATE`**: title template for events read **from** NAME's calendar,
  wherever they land; **wins over** `--title-to`. Repeatable.
- **`--mute NAME …`**: calendars to read as a source but never write blocks into.
- **`--lookback DAYS`**: days before now to keep mirrored (default `1`). With `--cleanup`, this
  instead bounds the window within which finished blocks are removed.
- **`--lookahead DAYS`**: days after now to mirror (default `60`).
- **`--cleanup`** / **`--no-cleanup`**: remove a mirror block once its event is over, instead of
  keeping it for the lookback window (default off).
- **`--statuses STATUS …`**: participation responses that count as busy and get mirrored, from
  `accepted`, `tentative`, `declined`, `pending`, `unknown` (default `accepted unknown`).
- **`--exclude-patterns REGEX …`**: replace the default title-exclusion patterns (see
  [Exclusions](#exclusions)).
- **`--calendar-include-patterns NAME REGEX …`**: whitelist NAME's calendar: mirror **only** its
  events whose title matches one of the given patterns, dropping every other event from that one
  calendar. Give several patterns after a calendar to allow several markers, and repeat the option to
  whitelist several calendars. A calendar with no include pattern is unaffected. See
  [Exclusions](#exclusions).
- **`--exclude-clashes`** / **`--no-exclude-clashes`**: skip a source event that overlaps a genuine
  event already on the target (default on).
- **`--exclude-all-day`** / **`--no-exclude-all-day`**: skip all-day events (default on).
- **`--exclude-out-of-hours`** / **`--no-exclude-out-of-hours`**: skip events that fall entirely
  outside working hours (default on).
- **`--max-deletes N`**: skip any mirror pass that would delete more than N blocks (default: no
  limit). N must be 0 or more; `0` skips any pass that would delete anything. Deletes from `--cleanup` count too. A source that suddenly loses that many events can't be
  trusted for its creates or updates either, so the whole pass is skipped, not just the deletes. The
  other passes still run, and then the run exits non-zero so the problem gets noticed, firing any
  [failure alert](#failure-alerts) you've configured. To apply a
  deliberate large clean-up, run once by hand without the option. With `--dry-run`, the skip is
  logged but the run doesn't fail. For agent runs, the warning and the failure are written to the
  agent's log (`~/Library/Logs/calque.log` by default).
- **`--dry-run`**: log the plan without writing any changes.
- **`--list-calendars`**: print every calendar's account-qualified name and exit.
- **`--install SECONDS`**: install a `launchd` agent that runs this same command every SECONDS,
  then exit.
- **`--uninstall`**: remove the installed `launchd` agent and exit.
- **`--notify-on-failure`**: post a macOS notification when a sync run fails (see
  [Failure alerts](#failure-alerts)).
- **`--on-failure COMMAND`**: run COMMAND when a sync run fails, with the failure message appended
  as its last argument (see [Failure alerts](#failure-alerts)).
- **`--logging LEVEL`**: logging level (default `info`). `debug` adds why each event was kept or
  excluded, and passes with nothing to change, which outside `--dry-run` are logged only at debug.
- **`--log-file PATH`**: write the log to PATH instead of stderr, rotating it at 1 MB and keeping
  3 backups. The parent directory is created if missing, and a leading `~` is expanded. If the file
  can't be opened, calque logs to stderr instead. With `--install`, PATH must be absolute; `--install`
  adds `--log-file ~/Library/Logs/calque.log` unless you give one. The file is for the agent's runs:
  the `--install` command itself still reports to your terminal.

Be careful not to place variadic options (`--mute`, `--exclude-patterns`, `--calendar-include-patterns`,
`--statuses`) immediately before the calendar arguments, or they will swallow them.

## Titles

The mirror-block title is a template. Placeholders are filled from the source event,
so `{account}` is the source account and `{title}` is the event's real subject. The default,
`Busy ({account} calendar)`, doesn't include `{title}` and so keeps the details opaque.
{account} is always the source of the current event, so when mirroring events from the primary calendar
into a client calendar, {account} is the primary calendar's account (even if the busy block originated
from a different client calendar). This ensures that, if using `{account}`, auxiliary calendars never see the
names of calendars other than the primary (which we assume they already know).

In addition to `--title`, two overrides control the title used for a calendar, both repeatable and
both keyed on a calendar's qualified name:

- `--title-to NAME TEMPLATE`: the title used when writing *into* NAME's calendar ("when putting
  events into *this* diary, use this format").
- `--title-from NAME TEMPLATE`: the title used for events read *from* NAME's calendar, wherever
  they land. A title-from override wins over a title-to one.

Common use-cases:

`--title-to` lets your company diary show real subjects while every client calendar sees only
opaque busy blocks, with no detail of your events or other clients' events.

`--title-from` pins how one source always appears, regardless of the target. For example, feed a
personal calendar into the company diary to block out home commitments, but keep those entries
fully opaque even if a `--title-to` on that calendar would otherwise make them detailed:

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" "MoM.Calendar" "iCloud.Home" \
  --title-to "Acme Consulting.Acme Consulting" "{account}: {title}" \
  --title-from "iCloud.Home" "Busy"
```

## Exclusions

Before mirroring, every source event runs through a set of **exclusion rules**; if any rule
rejects it, no busy block is written. The rules are assembled per run in
[`exclusions.py`](src/calque/exclusions.py), so adding a new kind is a matter of writing one
builder and wiring it into `rules`.

Current rules:

- **By status**: only events with a busy status are mirrored. The default busy statuses are
  `accepted` and `unknown`; change them with `--statuses` (see [Status filtering](#status-filtering)).
- **Cancelled**: events the organiser has cancelled (EventKit reports them as cancelled, shown
  struck through and greyed in Calendar.app) are never mirrored, so a meeting that's called off
  loses its busy block.
- **By title**: source events whose title matches any `--exclude-patterns` regular expression
  are skipped, so availability markers don't get mirrored as meetings. The default excludes a
  bare `Working` status block (`^Working$`) and any annual-leave marker (`\bA/L\b`). Pass one
  or more of your own patterns to replace the defaults.
- **All-day**: all-day events (out-of-office banners, leave, public holidays) are skipped so
  they don't blank out the whole day on the other calendar. On by default; `--no-exclude-all-day`.
- **Out of hours**: events that fall entirely outside working hours are skipped, so only your
  working day is mirrored. The window defaults to **Monday–Friday 08:00–18:00 local time**; an
  event that overlaps it at all (e.g. a 17:00–19:00 overrun) is still mirrored. On by default;
  `--no-exclude-out-of-hours`. The window itself (`work_days`, `work_start`, `work_end`) is set
  on `Config`.
- **By clash**: a source event is skipped when the target calendar already has a genuine event
  (not one of calque's own mirror blocks) overlapping any part of its slot, so calque never
  stacks a busy block on time you're already committed elsewhere. On by default; turn it off
  with `--no-exclude-clashes`.
- **Unlisted**: the inverse of *by title*, scoped to a calendar. Where a calendar is given
  `--calendar-include-patterns`, only its events whose title matches one of those patterns are
  mirrored and every other event is dropped, turning that calendar into a whitelist. Calendars
  without an include pattern are unaffected. The whitelist is keyed on the **source** calendar, so
  it filters that calendar's events as they're read; a target's genuine events still count as
  busy for clash detection.

Example: skip any event whose title is exactly `Working`, contains `A/L` as a whole word, or is `Lunch`, and don't skip events that clash with existing events on the target:

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" \
  --exclude-patterns "^Working$" "\bA/L\b" "\bLunch " --no-exclude-clashes
```

## Writing into every calendar

Availability is mirrored in both directions by default for every calendar you list.
If you want to read a calendar but not write into it, pass `--mute NAME` for that calendar.
Note that if you mute the primary calendar, it will mirror its events into the other calendars,
but will not be able to mirror busy blocks between the other calendars - i.e. you have muted
the hub so it can't act as a hub for mirroring.

## Status filtering

Your response is read from the event's attendee list.
By default, events you've **accepted** and events with no clear response (`unknown`) are mirrored; tentative,
declined, and pending invitations are skipped. Choose the responses that count as busy with `--statuses`,
e.g. `--statuses accepted tentative`. Events with no attendees (blocks you created yourself) are treated as
implicitly accepted.
