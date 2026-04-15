"""
normalize/windows.py — Windows Event Log field extractor (regex-based CPU path).

Handles the flat key=value format produced by cuSplunk's fixture generator
and also the standard Windows XML-to-text format used by Splunk forwarders.
"""

from __future__ import annotations

import re
import time

from cusplunk.normalize.normalizer import LogFormat, NormalizedEvent


class WindowsEventParser:
    """
    Extract structured fields from Windows Security Event Log strings.

    Supported input formats:
      1. Key=Value pairs: "EventCode=4624 ComputerName=WS001 AccountName=user ..."
      2. Splunk XML-flattened: "EventID=4624\nComputerName=WS001\n..."

    Output: NormalizedEvent with Windows-specific fields populated.
    """

    # Common Windows Security event fields
    _FIELD_RE = re.compile(r"(\w+)=([^\s]+)")

    # EventCode → (name, severity)
    _EVENT_SEVERITY: dict[int, str] = {
        4624: "low",      # Successful logon
        4625: "medium",   # Failed logon
        4634: "low",      # Logoff
        4648: "medium",   # Logon with explicit credentials
        4663: "low",      # Object access
        4672: "medium",   # Special privileges
        4688: "low",      # Process creation
        4720: "low",      # User account created
        4768: "low",      # Kerberos TGT request
        4769: "low",      # Kerberos service ticket
        4776: "medium",   # NTLM auth
    }

    def parse(self, raw: str) -> NormalizedEvent:
        event = NormalizedEvent(_raw=raw, sourcetype="WinEventLog:Security")
        event._time = time.time()

        fields = dict(self._FIELD_RE.findall(raw))

        # EventCode / EventID
        event_id_str = fields.get("EventCode") or fields.get("EventID")
        if event_id_str:
            try:
                event.event_id = int(event_id_str)
                event.severity = self._EVENT_SEVERITY.get(event.event_id, "low")
            except ValueError:
                pass

        event.computer_name = fields.get("ComputerName")
        event.host = (event.computer_name or "").lower() or None

        # Account information
        event.target_user = fields.get("AccountName") or fields.get("TargetUserName")
        event.subject_user = fields.get("SubjectUserName")
        event.domain = fields.get("AccountDomain") or fields.get("TargetDomainName")
        event.user = event.target_user

        # Logon type
        lt = fields.get("LogonType")
        if lt:
            try:
                event.logon_type = int(lt)
            except ValueError:
                pass

        # Network info
        event.src_ip = fields.get("IpAddress") or fields.get("src_ip")
        if event.src_ip in ("-", "::1", "127.0.0.1", ""):
            event.src_ip = None

        port_str = fields.get("IpPort") or fields.get("src_port")
        if port_str and port_str not in ("-", "0"):
            try:
                event.src_port = int(port_str)
            except ValueError:
                pass

        event.workstation_name = fields.get("WorkstationName")

        # Process info
        event.process = fields.get("ProcessName") or fields.get("NewProcessName")
        pid_str = fields.get("ProcessId") or fields.get("NewProcessId")
        if pid_str:
            try:
                event.pid = int(pid_str, 0)  # may be hex e.g. 0x1234
            except ValueError:
                pass

        event.source = "WinEventLog:Security"
        event.index = "windows"
        event.extra = {k: v for k, v in fields.items()
                       if k not in self._KNOWN_FIELDS}

        return event

    _KNOWN_FIELDS = frozenset([
        "EventCode", "EventID", "ComputerName", "AccountName", "TargetUserName",
        "SubjectUserName", "AccountDomain", "TargetDomainName", "LogonType",
        "IpAddress", "src_ip", "IpPort", "src_port", "WorkstationName",
        "ProcessName", "NewProcessName", "ProcessId", "NewProcessId",
    ])
