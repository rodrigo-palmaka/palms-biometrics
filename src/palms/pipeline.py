from datetime import date, timedelta
from pathlib import Path

import click

from palms.config import settings
from palms.db import get_connection, log_ingestion, upsert_daily_hr, upsert_sleep_records
from palms.sources import oura


@click.command()
@click.option("--days", default=settings.default_lookback_days, show_default=True,
              help="Number of days to look back (API only).")
@click.option("--source", default="all",
              type=click.Choice(["all", "oura", "oura-csv"]),
              help="Which source to ingest. Use oura-csv to load from exported CSVs.")
def ingest(days: int, source: str) -> None:
    """Pull health data from connected sources and store in SQLite."""
    conn = get_connection(settings.db_path)
    end = date.today()
    start = end - timedelta(days=days)

    if source == "oura-csv":
        _ingest_oura_csv(conn)
    elif source in ("all", "oura"):
        _ingest_oura(conn, start, end)

    click.echo("Done.")


def _ingest_oura(conn, start: date, end: date) -> None:
    if not settings.oura_client_id:
        click.echo("Oura credentials not configured — skipping.", err=True)
        return
    raw_dir = Path(settings.raw_data_path) / "oura"
    try:
        sleep_records, hr_records = oura.fetch_and_normalize(
            settings.oura_client_id, settings.oura_client_secret, start, end, raw_dir
        )
        n_sleep = upsert_sleep_records(conn, sleep_records)
        n_hr = upsert_daily_hr(conn, hr_records)
        log_ingestion(conn, "oura", start, end, n_sleep + n_hr, "success")
        click.echo(f"Oura API: {n_sleep} sleep records, {n_hr} HR records.")
    except Exception as exc:
        log_ingestion(conn, "oura", start, end, 0, "failed", str(exc))
        click.echo(f"Oura API ingestion failed: {exc}", err=True)


def _ingest_oura_csv(conn) -> None:
    raw_dir = Path(settings.raw_data_path) / "oura"
    csv_files = list(raw_dir.glob("*.csv"))
    if not csv_files:
        click.echo(f"No CSV files found in {raw_dir}. Export from Oura Membership Hub and drop files there.", err=True)
        return
    click.echo(f"Found {len(csv_files)} CSV file(s) in {raw_dir}.")
    try:
        sleep_records, hr_records = oura.load_from_csv(raw_dir)
        n_sleep = upsert_sleep_records(conn, sleep_records)
        n_hr = upsert_daily_hr(conn, hr_records)
        today = date.today()
        log_ingestion(conn, "oura", today, today, n_sleep + n_hr, "success")
        click.echo(f"Oura CSV: {n_sleep} sleep records, {n_hr} HR records.")
    except Exception as exc:
        log_ingestion(conn, "oura", date.today(), date.today(), 0, "failed", str(exc))
        click.echo(f"Oura CSV ingestion failed: {exc}", err=True)


@click.command()
@click.option("--dry-run", is_flag=True, help="Print HTML instead of sending email.")
def report(dry_run: bool) -> None:
    """Generate and email the weekly health report."""
    from palms.report import build_email, send_email

    conn = get_connection(settings.db_path)
    html = build_email(conn)

    if dry_run:
        click.echo(html)
        return

    if not settings.smtp_user:
        click.echo("SMTP not configured. Use --dry-run to preview.", err=True)
        return

    send_email(
        html,
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
        settings.report_recipient or settings.smtp_user,
    )
    click.echo(f"Report sent to {settings.report_recipient or settings.smtp_user}.")
