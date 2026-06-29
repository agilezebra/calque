"""Drive a synchronisation run: reconcile events between calendars and mirror them between primary and auxiliaries.

The reconciliation core (:func:`to_mirrors`, :func:`reconcile`) stays pure; the impure edges —
reading the clock and opening the calendar store — live in :func:`synchronise`, the process entry.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from calque.config import Config
from calque.exclusions import included, rules
from calque.model import Event, Mirror, Plan, Window
from calque.store import Calendar, CalendarStore


def to_mirrors(events: Iterable[Event], title: str, origin: str) -> dict[str, Mirror]:
    """Transform events into anonymised mirror blocks from ``origin``, titled via ``title``, keyed by source id."""
    return {
        event.identifier: Mirror(
            source=event.identifier,
            window=event.window,
            title=title.format(**asdict(event)),
            original=event.title,
            origin=origin,
        )
        for event in events
    }


def reconcile(desired: Mapping[str, Mirror], existing: Mapping[str, Mirror]) -> Plan:
    """Diff the blocks we want against the ones already present to produce a change set."""
    return Plan(
        create=tuple(mirror for source, mirror in desired.items() if source not in existing),
        update=tuple(mirror for source, mirror in desired.items() if source in existing and mirror != existing[source]),
        delete=tuple(mirror for source, mirror in existing.items() if source not in desired),
    )


def mirror(source: Calendar, target: Calendar, config: Config, window: Window) -> None:
    """Run one mirror pass: read the source, reconcile against the target, and apply the plan."""
    exclusions = rules(config, target.busy(window), source.qualified, target.qualified)
    title = config.title_for_calendar(source, target)
    plan = reconcile(
        to_mirrors(included(source.events(window), exclusions), title, source.qualified),
        target.mirrors(window, source.qualified),
    )
    logging.info("%s -> %s: %s", source.qualified, target.qualified, plan)

    if config.dry_run:
        plan.log()
        logging.info("dry run: no changes written")
        return

    target.apply(plan, window)


def synchronise(config: Config, calendars: list[str]) -> None:
    """Collect every calendar's events into the primary, then fan the primary's combined busy time back out to the rest.

    The first calendar listed is the primary: each of the others is mirrored into it, so it holds every calendar's
    events, and it is then mirrored back out to each of the others. So a consultant's time with one client also
    shows as busy to the rest. A calendar named in ``config.muted`` is still read as a source but never written
    to, keeping its viewers from seeing the other commitments.
    """
    now = datetime.now(UTC)
    window = Window(now - timedelta(days=config.lookback), now + timedelta(days=config.lookahead))
    store = CalendarStore()
    resolved = {title: store.calendar(title) for title in calendars}
    primary, *auxiliaries = calendars
    if primary not in config.muted:
        for auxiliary in auxiliaries:
            mirror(resolved[auxiliary], resolved[primary], config, window)
    for auxiliary in auxiliaries:
        if auxiliary not in config.muted:
            mirror(resolved[primary], resolved[auxiliary], config, window)
