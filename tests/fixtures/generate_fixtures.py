#!/usr/bin/env python3
"""
generate_fixtures.py — Generate test fixture data for cuSplunk tests.

Usage:
    python tests/fixtures/generate_fixtures.py

Outputs:
    tests/fixtures/events/windows_event_log_1000.json  (1,000 events)
    tests/fixtures/events/firewall_100k.json           (100,000 events)
    tests/fixtures/events/firewall_sample.json         (100 events, fast CI)

All outputs are deterministic given SEED.
"""

import json
import math
import random
import time
from pathlib import Path

SEED = 42
BASE_TS = 1_700_000_000  # 2023-11-14 22:13:20 UTC

rng = random.Random(SEED)

FIXTURES = Path(__file__).parent


# ── Windows Event Log ─────────────────────────────────────────────

WIN_EVENT_IDS = [4624, 4625, 4634, 4648, 4663, 4672, 4688, 4720, 4768, 4769, 4776]
WIN_SOURCES = [
    "Microsoft-Windows-Security-Auditing",
    "Microsoft-Windows-Sysmon/Operational",
    "Microsoft-Windows-PowerShell/Operational",
]
WIN_COMPUTERS = [f"WORKSTATION-{i:03d}" for i in range(1, 31)]
WIN_USERS = [f"user{i:03d}" for i in range(1, 20)] + ["SYSTEM", "NETWORK SERVICE", "LOCAL SERVICE"]
WIN_DOMAINS = ["CORP", "ACME", "CONTOSO"]
WIN_LOGON_TYPES = {2: "Interactive", 3: "Network", 4: "Batch", 5: "Service", 10: "RemoteInteractive"}


def _win_event(idx: int) -> dict:
    ts = BASE_TS + idx * rng.randint(1, 30)
    event_id = rng.choice(WIN_EVENT_IDS)
    computer = rng.choice(WIN_COMPUTERS)
    user = rng.choice(WIN_USERS)
    domain = rng.choice(WIN_DOMAINS)
    source = rng.choice(WIN_SOURCES)
    logon_type = rng.choice(list(WIN_LOGON_TYPES.keys()))

    raw = (
        f"EventID={event_id} ComputerName={computer} "
        f"AccountName={user} AccountDomain={domain} "
        f"LogonType={logon_type} "
        f"IpAddress={_random_ip()} IpPort={rng.randint(1024, 65535)}"
    )

    return {
        "_time": ts,
        "_raw": raw,
        "host": computer.lower(),
        "source": "WinEventLog:Security",
        "sourcetype": "WinEventLog:Security",
        "index": "windows",
        "EventCode": str(event_id),
        "ComputerName": computer,
        "AccountName": user,
        "AccountDomain": domain,
        "LogonType": str(logon_type),
        "src_ip": _random_ip(),
    }


# ── Firewall events ───────────────────────────────────────────────

FW_ACTIONS = ["allow", "deny", "drop"]
FW_PROTOCOLS = ["tcp", "udp", "icmp"]
FW_POLICIES = ["inbound-default", "outbound-default", "web-allow", "ssh-restrict"]
INTERNAL_SUBNETS = ["10.0.", "192.168.1.", "172.16."]


def _random_ip(internal: bool = False) -> str:
    if internal or rng.random() < 0.3:
        subnet = rng.choice(INTERNAL_SUBNETS)
        return subnet + f"{rng.randint(1, 254)}.{rng.randint(1, 254)}"
    return f"{rng.randint(1, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


WELL_KNOWN_PORTS = [22, 80, 443, 3389, 8080, 8443, 3306, 5432, 6379, 9997, 8088]


def _fw_event(idx: int) -> dict:
    ts = BASE_TS + idx * rng.randint(1, 10)
    action = rng.choice(FW_ACTIONS)
    protocol = rng.choice(FW_PROTOCOLS)
    src_ip = _random_ip()
    dst_ip = _random_ip(internal=rng.random() < 0.6)
    src_port = rng.randint(1024, 65535)
    dst_port = rng.choice(WELL_KNOWN_PORTS) if rng.random() < 0.7 else rng.randint(1, 65535)
    bytes_sent = rng.randint(40, 65000)
    policy = rng.choice(FW_POLICIES)

    raw = (
        f"date={time.strftime('%Y-%m-%d', time.gmtime(ts))} "
        f"time={time.strftime('%H:%M:%S', time.gmtime(ts))} "
        f"action={action} protocol={protocol} "
        f"src={src_ip} src_port={src_port} "
        f"dst={dst_ip} dst_port={dst_port} "
        f"bytes={bytes_sent} policy={policy}"
    )

    return {
        "_time": ts,
        "_raw": raw,
        "host": f"fw-{rng.randint(1, 4):02d}",
        "source": "firewall",
        "sourcetype": "paloalto:traffic",
        "index": "firewall",
        "action": action,
        "protocol": protocol,
        "src_ip": src_ip,
        "src_port": str(src_port),
        "dst_ip": dst_ip,
        "dst_port": str(dst_port),
        "bytes": str(bytes_sent),
        "policy": policy,
    }


# ── Generate + write ──────────────────────────────────────────────

def generate(n: int, fn) -> list[dict]:
    return [fn(i) for i in range(n)]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    size_kb = path.stat().st_size // 1024
    print(f"  wrote {len(data):>7,} events → {path}  ({size_kb} KB)")


def main():
    print("Generating fixtures...")

    write_json(
        FIXTURES / "events/windows_event_log_1000.json",
        generate(1000, _win_event),
    )

    fw_100k = generate(100_000, _fw_event)
    write_json(FIXTURES / "events/firewall_100k.json", fw_100k)
    write_json(FIXTURES / "events/firewall_sample.json", fw_100k[:100])

    print("Done.")


if __name__ == "__main__":
    main()
