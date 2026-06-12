#!/usr/bin/env python3
"""Render the ops dashboard markdown + overall status.

Inputs (file paths via argv):
    1. metrics file  — KEY=VALUE lines from scripts/ops_metrics.sh
    2. deploy JSON   — `gh run list` output for the deploy workflow (array)
    3. ci JSON       — `gh run list` output for CI (array)

Writes the dashboard body to ``dashboard.md`` and prints two lines to stdout:
    status=<ok|warn|crit>
    alert=<one-line summary for Discord, empty if ok>

No third-party deps — stdlib only.
"""
import json
import sys

# Emit UTF-8 regardless of platform locale (Windows defaults to cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def read_metrics(path):
    m = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if "=" in line:
                    k, _, v = line.partition("=")
                    m[k] = v
    except FileNotFoundError:
        pass
    return m


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def main():
    metrics_path = sys.argv[1] if len(sys.argv) > 1 else "metrics.env"
    deploy_path = sys.argv[2] if len(sys.argv) > 2 else "deploy.json"
    ci_path = sys.argv[3] if len(sys.argv) > 3 else "ci.json"

    m = read_metrics(metrics_path)
    deploys = read_json(deploy_path)
    ci = read_json(ci_path)

    mem_total = _int(m.get("MEM_TOTAL"))
    mem_avail = _int(m.get("MEM_AVAIL"))
    swap_total = _int(m.get("SWAP_TOTAL"))
    swap_used = _int(m.get("SWAP_USED"))
    disk_pct = _int(m.get("DISK_USED_PCT"))
    oom = _int(m.get("OOM_24H"))
    load1 = m.get("LOAD1", "?")
    nproc = _int(m.get("NPROC"), 1)
    services = {
        "Gunicorn (web)": m.get("SVC_GUNICORN", "unknown"),
        "RQ worker": m.get("SVC_WORKER", "unknown"),
        "Redis": m.get("SVC_REDIS", "unknown"),
        "Caddy": m.get("SVC_CADDY", "unknown"),
    }

    crit, warn = [], []

    # Memory
    if mem_total and mem_avail < 100:
        crit.append(f"RAM critically low ({mem_avail} MB available)")
    elif mem_total and mem_avail < 200:
        warn.append(f"RAM low ({mem_avail} MB available)")
    if oom > 0:
        crit.append(f"{oom} OOM kill(s) in last 24h")
    # Disk
    if disk_pct >= 90:
        crit.append(f"Disk {disk_pct}% full")
    elif disk_pct >= 80:
        warn.append(f"Disk {disk_pct}% full")
    # Services
    down = [name for name, st in services.items() if st != "active" and st != "unknown"]
    if down:
        crit.append("service down: " + ", ".join(down))
    unknown = [name for name, st in services.items() if st == "unknown"]
    if unknown:
        warn.append("service status unknown: " + ", ".join(unknown))
    # Load
    if nproc and load1 not in ("?", "") and float(load1) > nproc * 2:
        warn.append(f"high load ({load1} on {nproc} cpu)")

    status = "crit" if crit else ("warn" if warn else "ok")
    dot = {"ok": "🟢", "warn": "🟡", "crit": "🔴"}[status]

    def svc_badge(st):
        return {"active": "🟢 active", "inactive": "🔴 inactive",
                "failed": "🔴 failed", "unknown": "⚪ unknown"}.get(st, f"⚪ {st}")

    def mem_bar(used_pct):
        filled = round(used_pct / 10)
        return "█" * filled + "░" * (10 - filled)

    mem_used = mem_total - mem_avail if mem_total else 0
    mem_pct = round(mem_used / mem_total * 100) if mem_total else 0
    swap_pct = round(swap_used / swap_total * 100) if swap_total else 0

    lines = []
    lines.append(f"## {dot} CWA Ops Dashboard — TEST")
    lines.append("")
    lines.append(f"_Auto-updated by the `ops-dashboard` workflow • last check `{m.get('COLLECTED_AT', 'n/a')}`_")
    lines.append("")
    if crit:
        lines.append("> 🔴 **Issues:** " + "; ".join(crit))
        lines.append("")
    elif warn:
        lines.append("> 🟡 **Watch:** " + "; ".join(warn))
        lines.append("")

    # Resources
    lines.append("### Resources")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Memory | `{mem_bar(mem_pct)}` {mem_used}/{mem_total} MB ({mem_pct}%) — **{mem_avail} MB free** |")
    lines.append(f"| Swap | {swap_used}/{swap_total} MB ({swap_pct}%) |")
    lines.append(f"| Disk (/) | {disk_pct}% used — {m.get('DISK_AVAIL', '?')} free |")
    lines.append(f"| Load (1m) | {load1} on {nproc} cpu |")
    lines.append(f"| OOM kills (24h) | {'🔴 ' if oom else ''}{oom} |")
    lines.append(f"| RQ queue (default / high) | {m.get('RQ_DEFAULT', '?')} / {m.get('RQ_HIGH', '?')} |")
    lines.append("")

    # Services
    lines.append("### Services")
    lines.append("| Service | Status |")
    lines.append("|---|---|")
    for name, st in services.items():
        lines.append(f"| {name} | {svc_badge(st)} |")
    lines.append("")

    # Last deploy
    lines.append("### Last test deploy")
    if deploys:
        d = deploys[0]
        concl = d.get("conclusion") or d.get("status") or "?"
        emoji = {"success": "🟢", "failure": "🔴", "cancelled": "⚪"}.get(concl, "⚪")
        lines.append(f"{emoji} **{concl}** — {d.get('displayTitle', '')[:80]}")
        lines.append(f"`{d.get('headSha', '')[:7]}` • {d.get('createdAt', '')} • [run]({d.get('url', '')})")
    else:
        lines.append("_No deploy runs found._")
    lines.append("")

    # Recent CI failures
    fails = [r for r in ci if r.get("conclusion") == "failure"][:5]
    lines.append("### Recent CI failures (test)")
    if fails:
        for r in fails:
            lines.append(f"- 🔴 [{r.get('displayTitle', '')[:70]}]({r.get('url', '')}) — {r.get('createdAt', '')}")
    else:
        lines.append("_None in the recent window._ 🟢")
    lines.append("")
    lines.append("---")
    lines.append("<sub>Edit thresholds in `scripts/render_ops_dashboard.py`. This issue is rewritten automatically — don't edit by hand.</sub>")

    with open("dashboard.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    alert = ""
    if status == "crit":
        alert = "🔴 CWA TEST ops: " + "; ".join(crit)
    print(f"status={status}")
    print("alert=" + alert)


if __name__ == "__main__":
    main()
