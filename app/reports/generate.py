from pathlib import Path
import pandas as pd
from app.config import ROOT
from app.database.session import utcnow
from app.analytics.queries import load_data, build_market, entrants
from app.analytics.opportunities import enrich_market, niche_metrics


def research_sections(market, games, hours, label, now):
    lines = ["", "## RESEARCH OBSERVATIONS", "", "Creation is not verified public launch. All rankings below describe our selected tracked sample."]
    if market.empty:
        return lines + ["No observations; research hypotheses require collected evidence."]
    enriched = enrich_market(market, games)
    fresh = enriched[~enriched.stale]
    for title, subset in (("Five emerging smaller/newer games", fresh[(fresh.ccu < 1000) | (fresh.age_days <= 90)]),
                          ("Five fastest-growing recently created games", fresh[fresh.age_days <= 90])):
        lines += ["", f"### {title}", ""]
        ranked = subset[subset[f"pct_{label}"].notna() & (subset[f"pct_{label}"] > 0)].nlargest(5, f"delta_{label}")
        if ranked.empty:
            lines.append("Insufficient history or no qualifying positive growth; no winners inferred.")
        for _, row in ranked.iterrows():
            lines.append(f"- Universe {int(row.universe_id)}: {fmt(row.ccu)} CCU, {fmt(row[f'pct_{label}'], True)} / {label}, +{fmt(row[f'delta_{label}'])} CCU; creation age {fmt(row.age_days)} days.")
    lines += ["", "### Categories, declining trends and concentration", ""]
    niches = niche_metrics(enriched, "primary_genre", label, now)
    if niches.empty:
        lines.append("No inferred genre/mechanic/trend claims: classification fields are unpopulated.")
    else:
        for _, row in niches.iterrows():
            lines.append(f"- {row.niche}: {row.tracked_games} tracked, {row.matched_games} comparable ({row.history_coverage_pct:.0f}% coverage), {row.aggregate_current_ccu:,} current CCU; matched growth {fmt(row.matched_aggregate_growth_pct, True)}; HHI {fmt(row.hhi)}, matched HHI change {fmt(row.matched_hhi_change)}. Supporting universe IDs: {row.dominant_game_ids}. Classification: {row.classification_sources}.")
    newcomers = fresh[fresh.first_seen_at >= now - pd.Timedelta(hours=hours)].nlargest(5, "ccu")
    lines += ["", "### Interesting newly observed competitors", "", "Newly observed does not mean newly launched."]
    for _, row in newcomers.iterrows():
        lines.append(f"- Universe {int(row.universe_id)}: {fmt(row.ccu)} CCU; creation age {fmt(row.age_days)} days; first tracked {row.first_seen_at} UTC.")
    if newcomers.empty:
        lines.append("No fresh newly observed competitors in this window.")
    lines += ["", "### Three manual research hypotheses", ""]
    candidates = fresh[(fresh.ccu < 1000) | (fresh.age_days <= 90)].nlargest(3, "ccu")
    for index in range(3):
        if index >= len(candidates):
            lines.append(f"{index+1}. Missing evidence: not enough fresh smaller/newer candidates for another supported hypothesis.")
        else:
            row = candidates.iloc[index]
            lines.append(f"{index+1}. Hypothesis for manual investigation: study Universe {int(row.universe_id)} ({fmt(row.ccu)} observed CCU, creation age {fmt(row.age_days)} days) to identify its core loop and acquisition source. Validate differentiation, retention and observed monetization before considering a prototype. Missing evidence: verified launch, retention, acquisition costs and profitability; current popularity alone does not establish an opportunity.")
    return lines + ["", "Observed metrics are not modeled revenue. Discovery is relevance/ranking biased; missing history is never backfilled."]


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
        lines += research_sections(market, games, hours, label, now)
        path = output / folder / f"{now:%Y-%m-%d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    from app.reports.research import generate_research_report
    generate_research_report(settings,output)
    return paths


if __name__ == "__main__":
    for path in generate_reports():
        print(path)
