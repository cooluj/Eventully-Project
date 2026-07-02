from urllib.parse import quote_plus, urlencode

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_calendar_link(event):
    title = f"{event.name} \u00b7 {event.club.name}"
    details = f"{event.description}\n\nClub: {event.club.name}\nLocation: {event.location}"
    params = {"action": "TEMPLATE", "text": title, "details": details, "location": event.location}
    return f"https://calendar.google.com/calendar/u/0/r/eventedit?{urlencode(params, quote_via=quote_plus)}"
