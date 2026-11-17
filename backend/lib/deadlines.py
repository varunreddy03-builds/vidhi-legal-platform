"""Dates that matter (hearings, filing dates, meetings): time zones, calendar files and reminder planning. Pure logic, no database.

Important honesty rule: every date here was ENTERED by a person. VIDHI does not look up courts, does not calculate limitation periods
and does not know whether a date is right; reminders and calendar files say so.

Time zones: a date is typed as a local time plus an IANA zone name (default Asia/Kolkata), stored in UTC and shown back in the same zone.
A local time that does not exist (the hour skipped when clocks go forward) is refused. A local time that happens twice (clocks go back)
means its FIRST occurrence."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Kolkata"
KINDS = ("hearing", "deadline", "filing", "meeting", "other")
ALLOWED_OFFSETS = (10080, 4320, 1440, 120, 60, 15)  # minutes before: a week, three days, a day, two hours, an hour, a quarter hour
DEFAULT_OFFSETS = [1440, 60]
UTC = timezone.utc
LABEL = {10080: "in one week", 4320: "in three days", 1440: "in one day", 120: "in two hours", 60: "in one hour", 15: "in fifteen minutes"}
DISCLAIMER = "This date was entered by you or a colleague. VIDHI does not check it against any court record and it is not legal advice."


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("That time zone is not recognised. Use a name such as Asia/Kolkata or Europe/London.") from exc


def to_utc(local_text: str, tz_name: str) -> datetime:
    """'2026-11-05T10:30' in zone tz_name -> an aware UTC datetime. Raises ValueError with a plain message."""
    tz = zone(tz_name)
    try:
        naive = datetime.fromisoformat(local_text.strip())
    except ValueError as exc:
        raise ValueError("Enter the date and time like 2026-11-05T10:30.") from exc
    if naive.tzinfo is not None:  # an explicit offset was typed: honour it, the zone is then only for display
        return naive.astimezone(UTC)
    local = naive.replace(tzinfo=tz, fold=0)
    as_utc = local.astimezone(UTC)
    if as_utc.astimezone(tz).replace(tzinfo=None) != naive:  # round trip differs: that wall-clock time was skipped by a clock change
        raise ValueError("That local time does not exist in that time zone (the clocks change then). Pick a nearby time.")
    return as_utc


def local_text(when_utc: datetime, tz_name: str) -> str:
    """The same moment as local wall-clock text, minute precision."""
    aware = when_utc if when_utc.tzinfo else when_utc.replace(tzinfo=UTC)
    return aware.astimezone(zone(tz_name)).strftime("%Y-%m-%dT%H:%M")


def pretty(when_utc: datetime, tz_name: str) -> str:
    aware = when_utc if when_utc.tzinfo else when_utc.replace(tzinfo=UTC)
    return aware.astimezone(zone(tz_name)).strftime("%d %b %Y, %H:%M") + f" ({tz_name})"


def clean_offsets(values) -> list[int]:
    out = sorted({int(v) for v in (values or [])}, reverse=True)
    if any(v not in ALLOWED_OFFSETS for v in out):
        raise ValueError(f"Reminders can be set {', '.join(str(a) for a in ALLOWED_OFFSETS)} minutes before.")
    return out


def initial_sent(starts_at: datetime, offsets: list[int], now: datetime) -> dict:
    """Reminders whose moment has already passed when the date is saved are marked skipped, so saving a date for tomorrow
    does not immediately fire a 'one week before' reminder."""
    return {str(m): "skipped" for m in offsets if starts_at - timedelta(minutes=m) <= now}


def due_offsets(deadline: dict, now: datetime) -> list[int]:
    """Reminder offsets (minutes) that should be sent now: their moment has come, the date is still ahead, and they were not sent."""
    starts = deadline["starts_at"]
    starts = starts if starts.tzinfo else starts.replace(tzinfo=UTC)
    if deadline.get("status") != "OPEN" or starts <= now:
        return []
    sent = deadline.get("sent") or {}
    return [m for m in deadline.get("reminders", []) if str(m) not in sent and starts - timedelta(minutes=m) <= now]


# ---- calendar file (RFC 5545) ----

def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 bytes are continued on the next line after a space, never in the middle of a character."""
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(current)
            current, size = " " + ch, 1 + n
        else:
            current += ch
            size += n
    out.append(current)
    return "\r\n".join(out)


def _stamp(when: datetime) -> str:
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def ics(deadlines: list[dict], now: datetime, host: str = "vidhi") -> bytes:
    """A calendar file any calendar app can import. Times are in UTC (no zone definitions needed), with the local time in the description."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//VIDHI//Dates//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for d in deadlines:
        starts = d["starts_at"]
        starts = starts if starts.tzinfo else starts.replace(tzinfo=UTC)
        tz_name = d.get("tz") or DEFAULT_TZ
        notes = [f"Local time: {pretty(starts, tz_name)}"] + ([d["notes"]] if d.get("notes") else []) + [DISCLAIMER]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{d['id']}@{host}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(starts)}",
            f"DTEND:{_stamp(starts + timedelta(minutes=int(d.get('duration_minutes') or 60)))}",
            f"SUMMARY:{_esc(d['title'])}",
            f"DESCRIPTION:{_esc(chr(10).join(notes))}",
            f"CATEGORIES:{_esc(d.get('kind', 'other'))}",
        ]
        for m in d.get("reminders", []):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(d['title'])}", f"TRIGGER:-PT{int(m)}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(x) for x in lines) + "\r\n").encode("utf-8")