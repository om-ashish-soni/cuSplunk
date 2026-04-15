"""
normalize/cef.py — ArcSight Common Event Format (CEF) parser (CPU path).

CEF format:
  CEF:Version|Device Vendor|Device Product|Device Version|Signature ID|Name|Severity|[Extension]

Extension is key=value pairs (space-separated, values may be escaped with \\).
"""

from __future__ import annotations

import re
import time

from cusplunk.normalize.normalizer import NormalizedEvent

# CEF header regex
_HEADER_RE = re.compile(
    r"^CEF:(?P<version>\d+)\|"
    r"(?P<vendor>[^|]*)\|"
    r"(?P<product>[^|]*)\|"
    r"(?P<dev_version>[^|]*)\|"
    r"(?P<sig_id>[^|]*)\|"
    r"(?P<name>[^|]*)\|"
    r"(?P<severity>[^|]*)\|?"
    r"(?P<extension>.*)$",
    re.DOTALL,
)

# Extension tokeniser: split on "key=" boundaries (handles unescaped spaces in values)
# Strategy: find all key= positions, value is everything up to the next key= or end of string.
_KEY_RE = re.compile(r"(\w+)=")

# CEF → ECS field mapping
_CEF_FIELD_MAP: dict[str, str] = {
    "src": "src_ip",
    "dst": "dst_ip",
    "spt": "src_port",
    "dpt": "dst_port",
    "suser": "user",
    "duser": "target_user",
    "shost": "host",
    "dhost": "host",
    "msg": "message",
    "act": "action",
    "outcome": "status",
    "rt": "_time",         # receipt time (epoch ms)
    "end": "_time",
    "start": "_time",
    "sproc": "process",
    "dproc": "process",
    "spid": "pid",
    "dpid": "pid",
}


class CEFParser:

    def parse(self, raw: str) -> NormalizedEvent:
        event = NormalizedEvent(_raw=raw, sourcetype="cef")
        event._time = time.time()
        event.source = "cef"
        event.index = "cef"

        m = _HEADER_RE.match(raw.strip())
        if not m:
            event.message = raw
            return event

        event.device_vendor = m.group("vendor") or None
        event.device_product = m.group("product") or None
        event.device_version = m.group("dev_version") or None
        event.signature_id = m.group("sig_id") or None
        event.name = m.group("name") or None

        sev_str = m.group("severity").strip()
        event.severity = self._map_severity(sev_str)

        ext = m.group("extension") or ""
        for key, val in self._parse_extension(ext).items():

            mapped = _CEF_FIELD_MAP.get(key)
            if mapped == "src_ip":
                event.src_ip = val
            elif mapped == "dst_ip":
                event.dst_ip = val
            elif mapped == "src_port":
                try:
                    event.src_port = int(val)
                except ValueError:
                    pass
            elif mapped == "dst_port":
                try:
                    event.dst_port = int(val)
                except ValueError:
                    pass
            elif mapped == "user":
                event.user = val
            elif mapped == "target_user":
                event.target_user = val
            elif mapped == "host":
                event.host = val
            elif mapped == "message":
                event.message = val
            elif mapped == "action":
                event.action = val
            elif mapped == "status":
                event.status = val
            elif mapped == "_time":
                try:
                    ts = float(val)
                    # CEF rt is epoch milliseconds
                    event._time = ts / 1000.0 if ts > 1e10 else ts
                except ValueError:
                    pass
            elif mapped == "process":
                event.process = val
            elif mapped == "pid":
                try:
                    event.pid = int(val)
                except ValueError:
                    pass
            else:
                event.extra[key] = val

        return event

    @staticmethod
    def _parse_extension(ext: str) -> dict[str, str]:
        """
        Parse CEF extension key=value pairs.

        Values may contain spaces (non-standard but common). We split on
        'key=' boundaries: a new key starts wherever \\w+= appears after whitespace.
        Escaped sequences \\= and \\ (space) are unescaped.
        """
        result: dict[str, str] = {}
        keys = list(_KEY_RE.finditer(ext))
        for i, km in enumerate(keys):
            key = km.group(1)
            val_start = km.end()
            val_end = keys[i + 1].start() if i + 1 < len(keys) else len(ext)
            raw_val = ext[val_start:val_end].rstrip()
            val = raw_val.replace(r"\=", "=").replace(r"\ ", " ")
            result[key] = val
        return result

    @staticmethod
    def _map_severity(sev: str) -> str:
        """Map CEF 0-10 numeric or label to cuSplunk severity."""
        try:
            n = int(sev)
            if n <= 3:
                return "low"
            if n <= 6:
                return "medium"
            if n <= 8:
                return "high"
            return "critical"
        except ValueError:
            s = sev.lower()
            if s in ("low", "informational", "info"):
                return "low"
            if s in ("medium", "moderate"):
                return "medium"
            if s in ("high",):
                return "high"
            if s in ("critical", "very-high"):
                return "critical"
            return "medium"
