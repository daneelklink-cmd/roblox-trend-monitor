from pathlib import Path
import pandas as pd
from app.config import ROOT
from app.database.session import utcnow
from app.analytics.queries import load_data, build_market, entrants


def fmt(value, percentage=False):
    if value is None or pd.isna(value):
        return "insufficient history"
    return f"{value:+.1f}%" if percentage else f"{value:,.0f}"


def generate_reports(settings=None, output=None):
    games, snapshots, appearances, runs = load_data(settings)
    now = utcnow()
    market = build_market(games, snapshots, appearances, now)
    output = Path(output or ROOT / "reports")
    paths = []
    for folder, hours, label in (("daily", 24, "24h"), ("3day", 72, "72h"), ("weekly", 168, "7d")):
        lines = [f"# Roblox Market Report — {now:%Y-%m-%d} ({folder})", "", f"Generated {now.isoformat()} UTC. Window: {hours} hours. Public tracked sample, not the full platform.", "", "## BIGGEST BREAKOUTS", ""]
        if market.empty:
            lines.append("No observations. Run python -m app.collect.")
        else:
            fresh = market[~market.stale]
            ranked = fresh[fresh.breakout_score.notna() & fresh[f"pct_{label}"].notna()].nlargest(10, "breakout_score")
            if ranked.empty:
                lines.append("Insufficient history for this report window; no breakout claims yet.")
            for _, row in ranked.iterrows():
                safe_name = str(row["name"]).replace("\n", " ").replace("\r", " ")
                lines += [f"- **{safe_name}** ({row.universe_id})", f"  - Current CCU: {fmt(row.ccu)} | Score: {row.breakout_score}", f"  - 24h: {fmt(row.pct_24h, True)} | 72h: {fmt(row.pct_72h, True)} | 7d: {fmt(row.pct_7d, True)}"]
            events = entrants(snapshots, games)
            recent = events[(events.kind == "observed upward crossing") & (events.timestamp >= now - pd.Timedelta(hours=hours))]
            lines += ["", "## NEW ENTRANTS", ""]
            if recent.empty:
                lines.append("No new threshold crossings observed in this window. Games first seen above a threshold are excluded.")
            for _, event in recent.iterrows():
                lines.append(f"- {event['name']} crossed {event.threshold:,} CCU; first observed {event.timestamp} UTC.")
            lines += ["", "## COOLING GAMES", ""]
            cooling = fresh[fresh[f"pct_{label}"] <= -10].nsmallest(10, f"delta_{label}")
            if cooling.empty:
                lines.append("No qualifying observed declines, or insufficient history.")
            for _, row in cooling.iterrows():
                lines.append(f"- {row['name']}: {fmt(row.ccu)} CCU, {fmt(row[f'pct_{label}'], True)} over {label}.")
            lines += ["", "## INTERESTING SIGNALS", ""]
            lines.append(f"- {len(games)} tracked games; {len(fresh)} have observations from the last two hours.")
            for threshold in (1000, 5000, 10000, 50000):
                count = int((recent.threshold == threshold).sum())
                lines.append(f"- {count} games observed crossing {threshold:,} CCU in this window.")
            first = appearances[appearances.source == "top-trending"].groupby("universe_id").timestamp.min()
            lines.append(f"- {int((first >= now - pd.Timedelta(hours=hours)).sum())} games first observed in Trending in this window (may reflect initial sampling).")
            sustained = fresh[(fresh.pct_24h > 20) & (fresh.pct_72h > 20) & (fresh.pct_7d > 0)]
            lines.append(f"- {len(sustained)} games have >20% 24h and 72h growth plus positive 7d growth. This does not imply every intervening day grew.")
            lines += ["", "No inferred genre/mechanic/trend claims: classification fields are unpopulated."]
        path = output / folder / f"{now:%Y-%m-%d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    for path in generate_reports():
        print(path)
