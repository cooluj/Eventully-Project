from urllib.parse import quote_plus, urlencode

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_ORDER = {d: i for i, d in enumerate(WEEKDAYS)}


def build_calendar_link(event):
    title = f"{event.name} \u00b7 {event.club.name}"
    details = f"{event.description}\n\nClub: {event.club.name}\nLocation: {event.location}"
    params = {"action": "TEMPLATE", "text": title, "details": details, "location": event.location}
    return f"https://calendar.google.com/calendar/u/0/r/eventedit?{urlencode(params, quote_via=quote_plus)}"


def build_ics(event):
    """A minimal weekly-recurring iCalendar file for an event."""
    from datetime import date, timedelta

    weekday_idx = WEEKDAY_ORDER.get(event.weekday, 0)
    today = date.today()
    days_ahead = (weekday_idx - today.weekday()) % 7
    first = today + timedelta(days=days_ahead)
    hour, minute = (event.time.split(":") + ["00"])[:2]
    start = f"{first:%Y%m%d}T{int(hour):02d}{int(minute):02d}00"
    byday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][weekday_idx]

    def esc(text):
        return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Eventully//UW Club Events//EN",
        "BEGIN:VEVENT",
        f"UID:eventully-event-{event.id}@eventully",
        f"DTSTART;TZID=America/Los_Angeles:{start}",
        f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
        f"SUMMARY:{esc(event.name)} · {esc(event.club.name)}",
        f"DESCRIPTION:{esc(event.description or '')}",
        f"LOCATION:{esc(event.location)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])
