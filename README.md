# calque

[![Build](https://github.com/agilezebra/calque/actions/workflows/build.yml/badge.svg)](https://github.com/agilezebra/calque/actions/workflows/build.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=agilezebra_calque&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=agilezebra_calque)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=agilezebra_calque&metric=coverage)](https://sonarcloud.io/summary/new_code?id=agilezebra_calque)

Mirrors events between calendars as **anonymized busy blocks**, using your **local macOS calendar store**.
Built for the case where your availability has to show up on calendars in different tenants (e.g. keeping a client Exchange calendar and a your company Google calendar in sync) without exposing undesirable event detail.

By design, this is **not** a cloud service. Because calendars are already subscribed in macOS, calque talks only to the local EventKit store. There is **no authentication** required against any of the calendar providers, and no use of their APIs. This makes it suitable for use with **government clients** and other sensitive tenants that **forbid third-party tool** access.

> [!TIP]
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
>   --title-to "Work.Calendar" "{account}: {title}" --dry-run      # preview the plan
> calque Work.Calendar Client.Calendar \
>   --title-to "Work.Calendar" "{account}: {title}"                # apply it once
> calque Work.Calendar Client.Calendar \
>   --title-to "Work.Calendar" "{account}: {title}" --install 120  # then every 120s
> ```

## What it does

- Reads events from the calendars you specify, in a configurable time window around the current time. The **first** calendar
  you list is the **primary**; the rest are mirrored against it.
- Mirrors only the events you've **accepted** (tentative, declined, and unanswered are skipped by default).
  The set of statuses that count as busy is configurable.
- Drops any event an **exclusion rule** rejects: by title pattern, time, or because the target
  calendar is already busy over that slot (see [Exclusions](#exclusions)).
- Writes one block per mirrored event with a **templated title**
  (default `Busy ({account} calendar)`); no attendees, no joining into, , no location, no notes beyond a hidden opaque marker.
- **Collects then fans out**: each calendar's events are mirrored into the primary, so the primary
  acts as a hub and holds the full picture, and the primary is then mirrored back out to each of the others, so time
  you've committed with one client shows as busy (anonymized) to the rest. Pass `--mute <CALENDAR>` to
  keep a calendar from *receiving* blocks while still reading it as a source.
- Re-runs are **idempotent**: each block carries a hidden marker linking it to its source event
  and origin calendar, so calque updates times that moved, removes blocks whose source disappeared,
  and never mirrors a block back to the calendar it came from.

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
the the terminal and will ask separately for permission.
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
  --mute "iCloud.Home" \
  --dry-run
```

This is a typical consultant setup. `Acme Consulting.Acme Consulting` is your company calendar (the
hub), `MoSW.Calendar` and `MoM.Calendar` are two client tenants, and `iCloud.Home` is your personal
calendar. It mirrors all three into your company calendar, then fans your company calendar's combined availability back out to the two clients:

- `--title-to "Acme Consulting.Acme Consulting" "{account}: {title}"`: in your *own* company
  diary, show the real source account and subject, so you and your colleagues can see what each block actually is and where you are busy.
- `--title-from "iCloud.Home" "Busy"`: anything originating from your **personal** calendar is
  labelled just `Busy` wherever it lands, so home detail never leaks — not even into your company
  diary, which the `--title-to` rule would otherwise make detailed (a source override wins over a
  target one).
- Client calendars (`MoSW.Calendar`, `MoM.Calendar`) see only the default opaque `Busy (Acme Consulting calendar)` blocks, so neither sees the other's events, your home detail, or anything beyond the fact that you're busy.
- `--mute "iCloud.Home"` — read your personal calendar as a source but never write blocks into it;
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
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" "MoM.Calendar" iCloud.Home \
  --title-to "Acme Consulting.Acme Consulting" "{account}: {title}" \
  --title-from "iCloud.Home" "Busy" \
  --mute "iCloud.Home" \
  --install 180          # run every 3 minutes
```

Remove it with:

```sh
calque --uninstall
```

## Options

- **`calendars`** (positional, two or more) — the calendars to sync, each a qualified name from
  `--list-calendars`. The **first** is your primary calendar: every other is mirrored into it,
  and it is then mirrored back out to each.
- **`--title TEMPLATE`** — default title template for every mirror block (default
  `Busy ({account} calendar)`). `{field}` placeholders are filled from the source event; see
  [Titles](#titles).
- **`--title-to NAME TEMPLATE`** — title template used when writing **into** NAME's calendar.
  Repeatable.
- **`--title-from NAME TEMPLATE`** — title template for events read **from** NAME's calendar,
  wherever they land; **wins over** `--title-to`. Repeatable.
- **`--mute NAME …`** — calendars to read as a source but never write blocks into.
- **`--lookback DAYS`** — days before now to keep mirrored (default `1`). With `--cleanup`, this
  instead bounds the window within which finished blocks are removed.
- **`--lookahead DAYS`** — days after now to mirror (default `60`).
- **`--cleanup`** / **`--no-cleanup`** — remove a mirror block once its event is over, instead of
  keeping it for the lookback window (default off).
- **`--exclude-pattern REGEX …`** — replace the default title-exclusion patterns (see
  [Exclusions](#exclusions)).
- **`--exclude-clashes`** / **`--no-exclude-clashes`** — skip a source event that overlaps a genuine
  event already on the target (default on).
- **`--exclude-all-day`** / **`--no-exclude-all-day`** — skip all-day events (default on).
- **`--exclude-out-of-hours`** / **`--no-exclude-out-of-hours`** — skip events that fall entirely
  outside working hours (default on).
- **`--dry-run`** — log the plan without writing any changes.
- **`--list-calendars`** — print every calendar's account-qualified name and exit.
- **`--install SECONDS`** — install a `launchd` agent that runs this same command every SECONDS,
  then exit.
- **`--uninstall`** — remove the installed `launchd` agent and exit.
- **`--logging LEVEL`** — logging level (default `info`; `debug` shows why each event was kept or
  excluded).
Be careful not to place variadic options (`--mute`, `--exclude-pattern`) immediately before the calendar arguments,
or they will swallow them.

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

- `--title-to NAME TEMPLATE` — the title used when writing *into* NAME's calendar ("when putting
  events into *this* diary, use this format").
- `--title-from NAME TEMPLATE` — the title used for events read *from* NAME's calendar, wherever
  they land. A title-from override wins over a title-to one.

Common use-cases:

`--title-to` lets your *own* diary show real subjects while every client calendar still sees only
opaque busy blocks (and so never sees detail of your own or other clients' events):

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

- **By status** — only events with a busy status are mirrored. The default busy status is only
  `accepted`, but you can override them on `Config`.
- **Cancelled** — events the organiser has cancelled (EventKit reports them as cancelled, shown
  struck through and greyed in Calendar.app) are never mirrored, so a meeting that's called off
  drops its busy block instead of lingering.
- **By title** — source events whose title matches any `--exclude-pattern` regular expression
  are skipped, so availability markers don't get mirrored as meetings. The default excludes a
  bare `Working` status block (`^Working$`) and any annual-leave marker (`\bA/L\b`). Pass one
  or more of your own patterns to replace the defaults.
- **All-day** — all-day events (out-of-office banners, leave, public holidays) are skipped so
  they don't blank out the whole day on the other calendar. On by default; `--no-exclude-all-day`.
- **Out of hours** — events that fall entirely outside working hours are skipped, so only your
  working day is mirrored. The window defaults to **Monday–Friday 08:00–18:00 local time**; an
  event that overlaps it at all (e.g. a 17:00–19:00 overrun) is still mirrored. On by default;
  `--no-exclude-out-of-hours`. The window itself (`work_days`, `work_start`, `work_end`) is set
  on `Config`.
- **By clash** — a source event is skipped when the target calendar already has a genuine event
  (not one of calque's own mirror blocks) overlapping any part of its slot, so calque never
  stacks a busy block on time you're already committed elsewhere. On by default; turn it off
  with `--no-exclude-clashes`.

Example: skip any event whose title is exactly `Working`, contains `A/L` as a whole word, or is `Lunch`, and don't skip events that clash with existing events on the target:

```sh
calque "Acme Consulting.Acme Consulting" "MoSW.Calendar" \
  --exclude-pattern "^Working$" "\bA/L\b" "\bLunch " --no-exclude-clashes
```

## Writing into every calendar

Availability is mirrored in both directions by default for every calendar you list.
If you want to read a calendar but not write into it, pass `--mute NAME` for that calendar.
Note that if you mute the primary calendar, it will mirror its events into the other calendars,
but will not not be able to mirror busy blocked between the other calendars - i.e. you have muted
the hub so it can't act as a hub for mirroring.

## Status filtering

Your response is read from the event's attendee list.
Only events you've accepted are mirrored by default (the busy statuses are configurable on
`Config`). Events with no attendees (blocks you created yourself) are treated as implicitly accepted.
