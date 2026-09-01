from datetime import datetime, timedelta
from urllib.parse import quote_plus, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_ORDER = {d: i for i, d in enumerate(WEEKDAYS)}

# Single-campus product: event times are stored as naive Pacific wall time,
# and DB timestamps (created_at etc.) are naive UTC.
CAMPUS_TZ = ZoneInfo("America/Los_Angeles")


def campus_now():
    """Naive campus-local (Pacific) now, comparable to Event.starts_at."""
    return datetime.now(CAMPUS_TZ).replace(tzinfo=None)


def utc_to_campus(dt):
    """Convert a naive-UTC DB timestamp to naive campus-local time."""
    if dt is None:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(CAMPUS_TZ).replace(tzinfo=None)


def event_sort_key(event):
    """Soonest next occurrence first; one-off past events sink to the end."""
    now = campus_now()
    occ = event.next_occurrence(now)
    return (event.is_past(now), occ, event.name or "")


def split_upcoming(events, now=None):
    """(upcoming_sorted, past_sorted_desc) for a mixed list of events."""
    now = now or campus_now()
    upcoming = [e for e in events if not e.is_past(now)]
    past = [e for e in events if e.is_past(now)]
    upcoming.sort(key=lambda e: (e.next_occurrence(now), e.name or ""))
    past.sort(key=lambda e: e.starts_at, reverse=True)
    return upcoming, past


def day_label(day, today):
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%A")


def group_events_by_day(events, now=None):
    """Luma-style timeline grouping: ordered [(date, label, sublabel, events)].

    Weekly events materialize on their next occurrence date. Input should
    already be upcoming-only and sorted (see split_upcoming).
    """
    now = now or campus_now()
    today = now.date()
    groups = []
    for event in events:
        day = event.next_occurrence(now).date()
        if groups and groups[-1][0] == day:
            groups[-1][3].append(event)
        else:
            sub = day.strftime("%b %d").replace(" 0", " ")
            groups.append((day, day_label(day, today), sub, [event]))
    return groups


def is_safe_next_url(target, host_url):
    """Return True only for same-origin redirects."""
    if not target:
        return False
    ref = urlparse(host_url)
    test = urlparse(urljoin(host_url, target))
    return test.scheme in {"http", "https"} and ref.netloc == test.netloc


def parse_page(raw, maximum=10000):
    """Defensive ?page= parsing: bad or negative input becomes page 0."""
    try:
        return max(0, min(int(raw), maximum))
    except (TypeError, ValueError):
        return 0


def _gcal_stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def build_calendar_link(event):
    title = f"{event.name} \u00b7 {event.club.name}"
    details = f"{event.description}\n\nClub: {event.club.name}\nLocation: {event.location}"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "details": details,
        "location": event.location,
        "ctz": "America/Los_Angeles",
    }
    start = event.next_occurrence()
    end = event.ends_at if (not event.is_recurring and event.ends_at) else start + timedelta(hours=1)
    params["dates"] = f"{_gcal_stamp(start)}/{_gcal_stamp(end)}"
    if event.is_recurring:
        byday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][WEEKDAY_ORDER.get(event.weekday, 0)]
        params["recur"] = f"RRULE:FREQ=WEEKLY;BYDAY={byday}"
    return f"https://calendar.google.com/calendar/u/0/r/eventedit?{urlencode(params, quote_via=quote_plus)}"


def build_ics(event):
    """iCalendar file: real one-off dates, or a bounded weekly recurrence."""

    def esc(text):
        return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    start = event.next_occurrence()
    end = event.ends_at if (not event.is_recurring and event.ends_at) else start + timedelta(hours=1)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Eventully//UW Club Events//EN",
        "BEGIN:VEVENT",
        f"UID:eventully-event-{event.id}@eventully",
        f"DTSTART;TZID=America/Los_Angeles:{_gcal_stamp(start)}",
        f"DTEND;TZID=America/Los_Angeles:{_gcal_stamp(end)}",
    ]
    if event.is_recurring:
        byday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][WEEKDAY_ORDER.get(event.weekday, 0)]
        # COUNT instead of UNTIL: UNTIL must be UTC when DTSTART has a TZID,
        # and COUNT sidesteps that entirely. 26 weeks ≈ two quarters.
        lines.append(f"RRULE:FREQ=WEEKLY;BYDAY={byday};COUNT=26")
    lines += [
        f"SUMMARY:{esc(event.name)} · {esc(event.club.name)}",
        f"DESCRIPTION:{esc(event.description or '')}",
        f"LOCATION:{esc(event.location)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)
