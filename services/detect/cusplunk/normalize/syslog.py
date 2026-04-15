"""
normalize/syslog.py — RFC 3164 + RFC 5424 syslog parser (CPU path).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from cusplunk.normalize.normalizer import LogFormat, NormalizedEvent

# RFC 3164 months
_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# RFC 3164: <PRI>Mon DD HH:MM:SS host tag: message
_RFC3164_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<tag>[^:\[]+?)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<msg>.*)$",
    re.DOTALL,
)

# RFC 5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [SD] MSG
_RFC5424_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<ver>\d)\s+"
    r"(?P<ts>\S+)\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<app>\S+)\s+"
    r"(?P<proc>\S+)\s+"
    r"(?P<msgid>\S+)\s+"
    r"(?P<sd>-|\[.*?\](?:\[.*?\])*)\s*"
    r"(?P<msg>.*)$",
    re.DOTALL,
)


class SyslogParser:

    def parse(self, raw: str) -> NormalizedEvent:
        fmt = _detect(raw)
        if fmt == LogFormat.SYSLOG_RFC5424:
            return self._parse_5424(raw)
        return self._parse_3164(raw)

    def _parse_3164(self, raw: str) -> NormalizedEvent:
        event = NormalizedEvent(_raw=raw, sourcetype="syslog")
        m = _RFC3164_RE.match(raw.strip())
        if not m:
            event.message = raw
            return event

        pri = int(m.group("pri"))
        event.facility = pri >> 3
        event.priority = pri & 0x7
        event.host = m.group("host")
        event.app_name = m.group("tag").strip()
        if m.group("pid"):
            try:
                event.pid = int(m.group("pid"))
                event.proc_id = m.group("pid")
            except ValueError:
                pass
        event.message = m.group("msg").strip()
        event.source = "syslog"
        event.index = "syslog"

        # Parse timestamp (no year in RFC3164 — use current year)
        month = _MONTHS.get(m.group("month"), 1)
        day = int(m.group("day"))
        h, mi, s = (int(x) for x in m.group("time").split(":"))
        year = datetime.now(tz=timezone.utc).year
        try:
            dt = datetime(year, month, day, h, mi, s, tzinfo=timezone.utc)
            event._time = dt.timestamp()
        except ValueError:
            event._time = time.time()

        return event

    def _parse_5424(self, raw: str) -> NormalizedEvent:
        event = NormalizedEvent(_raw=raw, sourcetype="syslog")
        m = _RFC5424_RE.match(raw.strip())
        if not m:
            event.message = raw
            return event

        pri = int(m.group("pri"))
        event.facility = pri >> 3
        event.priority = pri & 0x7
        event.host = _nil(m.group("host"))
        event.app_name = _nil(m.group("app"))
        event.proc_id = _nil(m.group("proc"))
        event.msg_id = _nil(m.group("msgid"))
        event.message = m.group("msg").strip()
        event.source = "syslog"
        event.index = "syslog"

        ts_str = m.group("ts")
        if ts_str and ts_str != "-":
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                event._time = dt.timestamp()
            except ValueError:
                event._time = time.time()
        else:
            event._time = time.time()

        # Extract structured data key-value pairs
        sd_str = m.group("sd")
        if sd_str and sd_str != "-":
            for sd_match in re.finditer(r'\[([^\]]+)\]', sd_str):
                parts = sd_match.group(1).split()
                for part in parts[1:]:
                    if "=" in part:
                        k, _, v = part.partition("=")
                        event.extra[k] = v.strip('"')

        return event


def _detect(raw: str) -> LogFormat:
    stripped = raw.strip()
    if not stripped.startswith("<"):
        return LogFormat.SYSLOG_RFC3164
    close = stripped.find(">")
    if close == -1:
        return LogFormat.SYSLOG_RFC3164
    after_pri = stripped[close + 1:]
    if after_pri and after_pri[0].isdigit():
        return LogFormat.SYSLOG_RFC5424
    return LogFormat.SYSLOG_RFC3164


def _nil(val: str | None) -> str | None:
    return None if val == "-" else val
