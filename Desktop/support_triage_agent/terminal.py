"""
STIS Terminal — Rich operator console with live risk visualization.
Run: python src/terminal.py
     python src/terminal.py --input data/support_issues.csv
"""

import sys, os, csv, json, time, argparse, textwrap
from pathlib import Path
from datetime import datetime

# ── Optional rich import ───────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.layout import Layout
    from rich.text import Text
    from rich.rule import Rule
    from rich.align import Align
    from rich import box
    RICH = True
except ImportError:
    RICH = False

sys.path.insert(0, str(Path(__file__).parent))
from engine import process, TriageDecision, OUT_FILE, LOG_FILE

console = Console(highlight=False) if RICH else None

# ── Color / style maps ─────────────────────────────────────────────────────────
RISK_STYLE = {
    "LOW":      ("green",  "✦ LOW"),
    "MEDIUM":   ("yellow", "◈ MEDIUM"),
    "HIGH":     ("red",    "⚠ HIGH"),
    "CRITICAL": ("bold red on black", "☠ CRITICAL"),
}

STATUS_STYLE = {
    "replied":   ("bright_green", "REPLIED"),
    "escalated": ("bright_yellow", "ESCALATED"),
}

def print_banner():
    if not RICH:
        print("\n=== STIS — Support Triage Intelligence System ===\n")
        return
    console.print()
    console.print(Panel.fit(
        Align.center(
            "[bold white]STIS[/]\n"
            "[dim]Support Triage Intelligence System[/]\n"
            "[dim]HackerRank · Claude · Visa[/]"
        ),
        border_style="bright_blue",
        padding=(1, 4),
    ))
    console.print()

def print_result(ticket_id: str, dec: TriageDecision):
    if not RICH:
        print(f"\n[{dec.status.upper()}] {dec.product_area} | {dec.risk.level} | {dec.intent.primary}")
        print(f"Response: {dec.response[:200]}")
        return

    risk_style, risk_label = RISK_STYLE.get(dec.risk.level, ("white", dec.risk.level))
    status_style, status_label = STATUS_STYLE.get(dec.status, ("white", dec.status))

    # ── Header row ──
    console.print(Rule(f"[dim]Ticket {ticket_id}[/]", style="bright_blue"))

    # ── Meta table ──
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("k", style="dim", width=18)
    t.add_column("v")
    t.add_row("Domain",        f"[cyan]{dec.domain.title()}[/]")
    t.add_row("Status",        f"[{status_style}]{status_label}[/]")
    t.add_row("Risk",          f"[{risk_style}]{risk_label}[/]  score={dec.risk.score}")
    t.add_row("Product Area",  dec.product_area)
    t.add_row("Request Type",  dec.request_type)
    t.add_row("Confidence",    _conf_bar(dec.confidence))
    t.add_row("Coverage",      _conf_bar(dec.grounding.coverage_score))
    t.add_row("Intent",        f"[italic]{dec.intent.primary[:80]}[/]")
    if dec.risk.triggers:
        t.add_row("Risk Triggers", f"[red]{', '.join(dec.risk.triggers[:5])}[/]")
    if dec.intent.hidden_flags and dec.intent.hidden_flags != ["none"]:
        t.add_row("Hidden Flags",  f"[magenta]{', '.join(dec.intent.hidden_flags)}[/]")
    t.add_row("Processing",    f"{dec.processing_ms} ms")
    console.print(t)

    # ── Response ──
    border = "red" if dec.status == "escalated" else "green"
    wrapped = textwrap.fill(dec.response, width=80)
    console.print(Panel(wrapped, title="[bold]Response[/]", border_style=border, padding=(0,2)))

    # ── Justification ──
    if dec.justification:
        console.print(f"  [dim]⟶ {dec.justification}[/]\n")

def _conf_bar(val: float) -> str:
    if not RICH:
        return f"{val:.0%}"
    filled = int(val * 10)
    bar = "█" * filled + "░" * (10 - filled)
    color = "green" if val > 0.6 else ("yellow" if val > 0.3 else "red")
    return f"[{color}]{bar}[/] {val:.0%}"

# ── Batch CSV mode ─────────────────────────────────────────────────────────────
OUTPUT_FIELDS = [
    "ticket_id","subject","company","issue",
    "status","product_area","request_type","domain",
    "risk_level","risk_score","risk_triggers","malicious",
    "coverage","confidence","primary_intent","hidden_flags",
    "justification","response","processing_ms",
]

def run_batch(input_path: Path):
    import csv as _csv
    print_banner()

    with open(input_path, newline="", encoding="utf-8") as f:
        tickets = list(_csv.DictReader(f))

    if RICH:
        console.print(f"[bright_blue]Loaded[/] [bold]{len(tickets)}[/] tickets from [dim]{input_path}[/]\n")

    rows = []

    if RICH:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        )
        task = progress.add_task("Processing tickets…", total=len(tickets))
        progress.start()
    else:
        progress = None

    for tk in tickets:
        tid     = tk.get("ticket_id") or tk.get("id") or str(tickets.index(tk)+1)
        issue   = tk.get("issue") or tk.get("description") or ""
        subject = tk.get("subject", "")
        company = tk.get("company", "")

        if progress and RICH:
            progress.update(task, description=f"[dim]#{tid}[/] {subject[:40]}")

        try:
            dec = process(tid, issue, subject, company)
        except Exception as e:
            dec = TriageDecision()
            dec.justification = f"Processing error: {e}"

        print_result(tid, dec)

        rows.append({
            "ticket_id":     tid,
            "subject":       subject,
            "company":       company,
            "issue":         issue,
            "status":        dec.status,
            "product_area":  dec.product_area,
            "request_type":  dec.request_type,
            "domain":        dec.domain,
            "risk_level":    dec.risk.level,
            "risk_score":    dec.risk.score,
            "risk_triggers": "|".join(dec.risk.triggers),
            "malicious":     dec.risk.malicious,
            "coverage":      dec.grounding.coverage_score,
            "confidence":    dec.confidence,
            "primary_intent":dec.intent.primary,
            "hidden_flags":  "|".join(dec.intent.hidden_flags),
            "justification": dec.justification,
            "response":      dec.response,
            "processing_ms": dec.processing_ms,
        })

        if progress and RICH:
            progress.advance(task)
        time.sleep(0.3)

    if progress and RICH:
        progress.stop()

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        w.writerows(rows)

    # ── Summary ──
    replied   = sum(1 for r in rows if r["status"] == "replied")
    escalated = sum(1 for r in rows if r["status"] == "escalated")
    malicious = sum(1 for r in rows if r["malicious"])

    if RICH:
        st = Table(box=box.ROUNDED, title="[bold]Batch Summary[/]", border_style="bright_blue")
        st.add_column("Metric",  style="dim")
        st.add_column("Value",   style="bold")
        st.add_row("Total Tickets",   str(len(tickets)))
        st.add_row("Replied",         f"[green]{replied}[/]")
        st.add_row("Escalated",       f"[yellow]{escalated}[/]")
        st.add_row("Malicious/Injections", f"[red]{malicious}[/]")
        st.add_row("Output CSV",      str(OUT_FILE))
        st.add_row("Log File",        str(LOG_FILE))
        console.print(st)
    else:
        print(f"\nDone. replied={replied} escalated={escalated} malicious={malicious}")
        print(f"Output: {OUT_FILE}")


# ── Interactive mode ───────────────────────────────────────────────────────────
def run_interactive():
    print_banner()
    if RICH:
        console.print("[dim]Type [bold]quit[/] to exit.[/]\n")
    else:
        print("Type 'quit' to exit.\n")

    idx = 1
    while True:
        if RICH:
            console.rule("[dim]New Ticket[/]")
            company = console.input("[cyan]Company[/] (hackerrank/claude/visa): ").strip()
        else:
            company = input("Company: ").strip()

        if company.lower() == "quit":
            break

        if RICH:
            subject = console.input("[cyan]Subject[/]: ").strip()
        else:
            subject = input("Subject: ").strip()

        if RICH:
            console.print("[cyan]Issue[/] (blank line to submit):")
        else:
            print("Issue (blank line to submit):")

        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        issue = "\n".join(lines)

        if not issue:
            continue

        tid = f"LIVE-{idx:04d}"
        idx += 1

        if RICH:
            with console.status("[bold blue]Analyzing ticket…[/]", spinner="dots"):
                dec = process(tid, issue, subject, company)
        else:
            dec = process(tid, issue, subject, company)

        print_result(tid, dec)


# ── Entry ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="STIS Terminal")
    ap.add_argument("--input", "-i", type=Path, help="Input CSV")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    if args.input:
        if not args.input.exists():
            print(f"File not found: {args.input}")
            sys.exit(1)
        run_batch(args.input)
    else:
        run_interactive()

if __name__ == "__main__":
    main()
