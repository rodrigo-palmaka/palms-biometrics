import base64
import io
import smtplib
import sqlite3
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Template

from palms.analytics import get_resting_hr_stats, get_resting_hr_trend, get_sleep_stats, get_sleep_trend

matplotlib.use("Agg")


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


def build_hr_chart(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(df["date"], df["resting_hr_bpm"], alpha=0.35, s=18, color="#90CAF9")
    rolling = df.set_index("date")["resting_hr_bpm"].rolling(7, min_periods=3).mean()
    ax.plot(rolling.index, rolling.values, color="#1565C0", linewidth=2, label="7-day avg")
    mean_val = df["resting_hr_bpm"].mean()
    ax.axhline(mean_val, color="#9E9E9E", linewidth=1, linestyle="--", label=f"avg {mean_val:.0f} bpm")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.set_ylabel("Resting HR (bpm)")
    ax.set_title("Resting Heart Rate — Last 90 Days")
    ax.legend(framealpha=0.5)
    fig.tight_layout()
    return _fig_to_b64(fig)


def build_sleep_chart(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(10, 4))
    colors = ["#EF9A9A" if h < 6 else "#FFF59D" if h < 7 else "#A5D6A7" for h in df["sleep_hours"]]
    ax.bar(df["date"], df["sleep_hours"], color=colors, width=0.8)
    mean_val = df["sleep_hours"].mean()
    ax.axhline(7, color="#43A047", linewidth=1, linestyle="--", label="7h target")
    ax.axhline(mean_val, color="#9E9E9E", linewidth=1, linestyle=":", label=f"avg {mean_val:.1f}h")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.set_ylabel("Sleep (hours)")
    ax.set_title("Sleep Duration — Last 30 Days")
    ax.set_ylim(0, max(df["sleep_hours"].max() + 1, 9))
    ax.legend(framealpha=0.5)
    fig.tight_layout()
    return _fig_to_b64(fig)


_EMAIL_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 700px; margin: 0 auto; padding: 24px; color: #212121; }
  h1 { color: #1565C0; border-bottom: 2px solid #E3F2FD; padding-bottom: 8px; }
  h2 { color: #1976D2; font-size: 1.1rem; margin-top: 32px; }
  .stat { display: inline-block; margin: 0 16px 8px 0; }
  .stat-val { font-size: 1.6rem; font-weight: 700; color: #1565C0; }
  .stat-lbl { font-size: 0.75rem; color: #757575; display: block; }
  img { max-width: 100%; border-radius: 4px; margin: 12px 0; }
  .footer { margin-top: 40px; font-size: 0.75rem; color: #9E9E9E; border-top: 1px solid #EEE; padding-top: 12px; }
  .trend-up { color: #E53935; } .trend-down { color: #43A047; } .trend-flat { color: #757575; }
</style></head>
<body>
<h1>Palms Biometrics &mdash; Week of {{ week_of }}</h1>

<h2>Resting Heart Rate (last 30 days)</h2>
{% if hr %}
<div>
  <span class="stat"><span class="stat-val">{{ hr.mean }}</span><span class="stat-lbl">avg bpm</span></span>
  <span class="stat"><span class="stat-val">{{ hr.min }}</span><span class="stat-lbl">min bpm</span></span>
  <span class="stat"><span class="stat-val">{{ hr.max }}</span><span class="stat-lbl">max bpm</span></span>
  <span class="stat"><span class="stat-val trend-{{ hr.trend }}">{{ hr.trend }}</span><span class="stat-lbl">trend</span></span>
</div>
{% if hr_chart %}<img src="data:image/png;base64,{{ hr_chart }}" alt="Resting HR chart">{% endif %}
{% else %}<p>No resting heart rate data available yet.</p>{% endif %}

<h2>Sleep Duration (last 30 days)</h2>
{% if sleep %}
<div>
  <span class="stat"><span class="stat-val">{{ sleep.avg_hours }}h</span><span class="stat-lbl">avg sleep</span></span>
  <span class="stat"><span class="stat-val">{{ sleep.min_hours }}h</span><span class="stat-lbl">min</span></span>
  <span class="stat"><span class="stat-val">{{ sleep.max_hours }}h</span><span class="stat-lbl">max</span></span>
  {% if sleep.bedtime_consistency_min is defined %}
  <span class="stat"><span class="stat-val">±{{ sleep.bedtime_consistency_min }}m</span><span class="stat-lbl">bedtime consistency</span></span>
  {% endif %}
</div>
{% if sleep_chart %}<img src="data:image/png;base64,{{ sleep_chart }}" alt="Sleep chart">{% endif %}
{% else %}<p>No sleep data available yet.</p>{% endif %}

<div class="footer">
  Generated {{ generated_at }} &bull; Sources: Oura Ring
</div>
</body></html>""")


def build_email(conn: sqlite3.Connection) -> str:
    hr_stats = get_resting_hr_stats(conn, days=30)
    sleep_stats = get_sleep_stats(conn, days=30)

    hr_df = get_resting_hr_trend(conn, days=90)
    sleep_df = get_sleep_trend(conn, days=30)

    hr_chart = build_hr_chart(hr_df) if not hr_df.empty else None
    sleep_chart = build_sleep_chart(sleep_df) if not sleep_df.empty else None

    from datetime import datetime
    return _EMAIL_TEMPLATE.render(
        week_of=date.today().strftime("%B %d, %Y"),
        hr=hr_stats or None,
        sleep=sleep_stats or None,
        hr_chart=hr_chart,
        sleep_chart=sleep_chart,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def send_email(html: str, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, recipient: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Palms Biometrics — {date.today().strftime('%b %d, %Y')}"
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, recipient, msg.as_string())
