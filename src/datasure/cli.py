from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from datasure import __version__

app = typer.Typer(
    name="datasure",
    help="DataSure — automated QA/testing for data and analytics applications.",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@app.command()
def setup(
    port: int = typer.Option(8765, "--port", "-p", help="Local port for the setup wizard"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print URL instead of opening browser"),
) -> None:
    """Launch the interactive setup wizard to configure your Qlik connection."""
    from datasure.setup_wizard import run, CONFIG_FILE

    console.print(f"\n[bold]DataSure[/bold] v{__version__} — Setup Wizard")
    console.print(f"[dim]Opening browser at http://localhost:{port} …[/dim]\n")

    try:
        config_path = run(port=port, no_browser=no_browser)
        console.print(f"\n[green bold]Setup complete![/green bold]")
        console.print(f"Config saved to: [cyan]{config_path}[/cyan]\n")
        console.print("Run next:")
        console.print(f"  [bold]datasure list-apps[/bold]")
        console.print(f"  [bold]datasure validate <APP_ID>[/bold]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(0)


@app.command()
def validate(
    app_id: str = typer.Argument(..., help="Qlik Sense app ID to validate"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to datasure.yaml"),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Report output directory"),
    formats: str = typer.Option("html,json", "--formats", "-f", help="Comma-separated report formats"),
    fail_on_error: bool = typer.Option(False, "--fail-on-error", help="Exit 1 if any errors found"),
) -> None:
    """Validate a Qlik Sense app and generate a report."""
    from datasure.config.settings import load_settings
    from datasure.connectors.qlik_sense import QlikSenseConnector
    from datasure.core.validation_engine import ValidationEngine
    from datasure.reporting.generator import ReportGenerator

    settings = load_settings(config)
    _setup_logging(settings.log_level)

    if output_dir:
        settings.report.output_dir = output_dir

    console.print(f"[bold]DataSure[/bold] v{__version__} — validating app [cyan]{app_id}[/cyan]")

    connector = QlikSenseConnector(settings.qlik)

    with console.status("Fetching app objects..."):
        try:
            objects = connector.get_app_objects(app_id)
            data_model = connector.get_data_model(app_id)
            objects.append(data_model)
        except Exception as exc:
            console.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(code=2)

    console.print(f"Fetched [bold]{len(objects)}[/bold] objects")

    engine = ValidationEngine(settings)
    with console.status("Running validators..."):
        results = engine.run(objects)

    summary = engine.summary(results)
    _print_summary_table(summary)

    fmt_list = [f.strip() for f in formats.split(",")]
    generator = ReportGenerator(settings.report.output_dir)
    paths = generator.generate(results, summary, fmt_list, run_name=f"app-{app_id[:8]}")

    console.print("\nReports written:")
    for fmt, path in paths.items():
        console.print(f"  [green]{fmt}[/green]: {path}")

    if fail_on_error and summary["total_errors"] > 0:
        raise typer.Exit(code=1)


@app.command("test-connection")
def test_connection(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to datasure.yaml"),
) -> None:
    """Test connectivity and authentication to the configured Qlik environment."""
    from datasure.config.settings import load_settings
    from datasure.connectors.qlik_sense import QlikSenseConnector

    settings = load_settings(config)
    _setup_logging(settings.log_level)
    connector = QlikSenseConnector(settings.qlik)

    with console.status("Testing connection..."):
        result = connector.test_connection()

    if result["ok"]:
        console.print(f"[green bold]Connection successful[/green bold]")
        for k, v in result.items():
            if k != "ok":
                console.print(f"  [dim]{k}:[/dim] {v}")
    else:
        console.print(f"[red bold]Connection failed[/red bold]")
        console.print(f"  {result['error']}")
        raise typer.Exit(code=1)


@app.command("list-apps")
def list_apps(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """List all Qlik Sense apps available on the configured server."""
    from datasure.config.settings import load_settings
    from datasure.connectors.qlik_sense import QlikSenseConnector

    settings = load_settings(config)
    _setup_logging(settings.log_level)
    connector = QlikSenseConnector(settings.qlik)

    with console.status("Fetching apps..."):
        try:
            apps = connector.list_apps()
        except Exception as exc:
            console.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(code=2)

    table = Table("ID", "Name", "Stream", "Published", "Owner")
    for a in apps:
        table.add_row(a["id"], a["name"], a["stream"], str(a["published"]), a["owner"])
    console.print(table)


@app.command()
def demo(
    output_dir: Optional[Path] = typer.Option(Path("/tmp/datasure-demo"), "--output", "-o"),
    formats: str = typer.Option("html,json,junit", "--formats", "-f"),
) -> None:
    """Run a full validation pass against built-in dummy data (no server required)."""
    from datasure.config.settings import Settings
    from datasure.core.validation_engine import ValidationEngine
    from datasure.reporting.generator import ReportGenerator

    settings = Settings()
    settings.report.output_dir = output_dir
    _setup_logging(settings.log_level)

    console.print(f"[bold]DataSure[/bold] v{__version__} — [yellow]demo mode[/yellow] (no server)")

    objects = _dummy_objects()
    console.print(f"Loaded [bold]{len(objects)}[/bold] dummy objects\n")

    engine = ValidationEngine(settings)
    results = engine.run(objects)
    summary = engine.summary(results)
    _print_summary_table(summary)

    _print_issues_table(results)

    fmt_list = [f.strip() for f in formats.split(",")]
    generator = ReportGenerator(output_dir)
    paths = generator.generate(results, summary, fmt_list, run_name="demo-run", objects=objects)

    console.print("\n[bold]Reports written:[/bold]")
    for fmt, path in paths.items():
        console.print(f"  [green]{fmt}[/green]: {path}")


def _dummy_objects() -> list:
    return [
        # ── Apps ──────────────────────────────────────────────────────────────
        {"type": "app", "id": "app-001", "name": "Sales Dashboard", "description": "Monthly sales KPIs"},
        {"type": "app", "id": "app-002", "name": "HR Overview", "description": ""},       # warning: no description
        {"type": "app", "id": "app-003", "name": "", "description": ""},                  # error: no name

        # ── Variables (used by field_integrity & duplicate expansion) ─────────
        {"type": "variable", "id": "var-001", "name": "vSalesExpr", "definition": "Sum(Revenue)"},
        {"type": "variable", "id": "var-002", "name": "vCurrYear",  "definition": "Year(Today())"},

        # ── Sheets ────────────────────────────────────────────────────────────
        {"type": "sheet", "id": "sheet-001", "name": "Overview", "title": "Executive Overview",
         "cells": [{"type": "barchart"}, {"type": "kpi"}]},
        {"type": "sheet", "id": "sheet-002", "name": "Empty Sheet", "title": "Work In Progress",
         "cells": []},                                                                     # warning: no viz

        # ── Master items ──────────────────────────────────────────────────────
        {"type": "measure", "id": "master-001", "name": "Total Revenue (Master)",
         "expression": "Sum(Revenue)", "label": "Total Revenue", "is_master": True,
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},

        # ── Measures ──────────────────────────────────────────────────────────
        # Good
        {"type": "measure", "id": "meas-001", "name": "Total Revenue",
         "expression": "Sum(Revenue)", "label": "Total Revenue",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        # Duplicate of meas-001 (DUP001)
        {"type": "measure", "id": "meas-001b", "name": "Revenue Copy",
         "expression": "Sum(Revenue)", "label": "Revenue Copy",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        # Uses variable — expands to Sum(Revenue) — third duplicate
        {"type": "measure", "id": "meas-001c", "name": "Revenue via Var",
         "expression": "$(vSalesExpr)", "label": "Revenue (var)",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        # No label (warning)
        {"type": "measure", "id": "meas-002", "name": "Avg Order Value",
         "expression": "Avg(OrderValue)", "label": "", "number_format": {}, "expected_type": "numeric"},
        # Empty expression (error)
        {"type": "measure", "id": "meas-003", "name": "Broken Measure",
         "expression": "   ", "label": "Broken", "number_format": {}, "expected_type": "numeric"},
        # References a non-existent field GhostField (FI001)
        {"type": "measure", "id": "meas-005", "name": "Ghost Metric",
         "expression": "Sum(GhostField)", "label": "Ghost",
         "number_format": {}, "expected_type": "numeric"},
        # Set analysis with unknown field (FI003)
        {"type": "measure", "id": "meas-006", "name": "Set Analysis Bad",
         "expression": "Sum({<DeletedStatus={'Active'}>} Revenue)", "label": "Bad Set",
         "number_format": {}, "expected_type": "numeric"},
        # Uses key field directly (FI002 warning)
        {"type": "measure", "id": "meas-007", "name": "Count by Key",
         "expression": "Count(CustomerID)", "label": "Cust Count",
         "number_format": {}, "expected_type": "numeric"},
        # References deleted master item (FI010)
        {"type": "measure", "id": "meas-008", "name": "Ref Deleted Master",
         "expression": "Sum(Revenue)", "label": "Old Master Ref",
         "master_item_id": "master-deleted-999",
         "number_format": {}, "expected_type": "numeric"},

        # ── Dimensions ────────────────────────────────────────────────────────
        {"type": "dimension", "id": "dim-001", "name": "Region", "field_def": "Region", "tags": ["$ascii"]},
        {"type": "dimension", "id": "dim-002", "name": "Empty Dim", "field_def": "", "tags": []},  # error

        # ── Visualizations ────────────────────────────────────────────────────
        {"type": "visualization", "id": "viz-001", "name": "Revenue Bar",
         "visualization_type": "barchart", "properties": {"title": "Revenue by Region"}},
        {"type": "visualization", "id": "viz-002", "name": "Mystery Chart",
         "visualization_type": "", "properties": {"title": ""}},                          # error: no type

        # ── Data model — triggers DM001/DM002 (synthetic key risk), DM020/DM021 ──
        {"type": "data_model", "id": "app-001",
         "used_fields": {"revenue", "ordervalue", "orderdate", "region", "customerid"},
         "tables": [
            {"name": "FactSales", "fields": [
                {"name": "Revenue",    "tags": ["$numeric"],           "is_key": False},
                {"name": "OrderValue", "tags": ["$numeric"],           "is_key": False},
                {"name": "OrderDate",  "tags": ["$date", "$numeric"],  "is_key": False},
                {"name": "CustomerID", "tags": ["$numeric"],           "is_key": True},
                # Shared with DimProduct on TWO fields → triggers DM002
                {"name": "ProductID",  "tags": ["$numeric"],           "is_key": True},
                {"name": "Category",   "tags": [],                     "is_key": False},  # unused: DM021
                {"name": "LoadBatch",  "tags": ["$numeric"],           "is_key": False},  # unused: DM021
            ]},
            {"name": "DimCustomer", "fields": [
                {"name": "CustomerID", "tags": ["$numeric"], "is_key": True},
                {"name": "Region",     "tags": ["$ascii"],  "is_key": False},
            ]},
            {"name": "DimProduct", "fields": [
                {"name": "ProductID",   "tags": ["$numeric"], "is_key": True},
                # Sharing a second key with FactSales triggers potential synthetic key
                {"name": "CustomerID",  "tags": ["$numeric"], "is_key": True},
                {"name": "ProductName", "tags": ["$ascii"],   "is_key": False},  # unused: DM021
            ]},
            # Isolated table — no fields used anywhere → DM020
            {"name": "StagingTemp", "fields": [
                {"name": "TempID",  "tags": ["$numeric"], "is_key": False},
                {"name": "TempVal", "tags": ["$ascii"],   "is_key": False},
            ]},
        ]},
    ]


def _print_issues_table(results) -> None:
    from datasure.validators.base import Severity
    issues_found = [i for r in results for i in r.issues]
    if not issues_found:
        return

    table = Table(title="Issues Found", show_header=True, show_lines=True)
    table.add_column("Rule", style="dim", width=8)
    table.add_column("Severity", width=9)
    table.add_column("Object", width=12)
    table.add_column("ID", width=12)
    table.add_column("Message")

    sev_color = {Severity.ERROR: "red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}
    for issue in issues_found:
        color = sev_color.get(issue.severity, "white")
        table.add_row(
            issue.rule_id,
            f"[{color}]{issue.severity.value.upper()}[/{color}]",
            issue.object_type,
            issue.object_id,
            issue.message,
        )
    console.print(table)


@app.command()
def version() -> None:
    """Show DataSure version."""
    console.print(f"DataSure v{__version__}")


def _print_summary_table(summary: dict) -> None:
    table = Table(title="Validation Summary", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    for k, v in summary.items():
        color = "green" if k == "passed" else ("red" if k in ("failed", "total_errors") else "white")
        table.add_row(k.replace("_", " ").title(), f"[{color}]{v}[/{color}]")
    console.print(table)


if __name__ == "__main__":
    app()