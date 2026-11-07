"""
Diwali Cloud Wishes - data analysis and BI export
-------------------------------------------------
Reads the data saved in DynamoDB and produces:
  1. A short summary in the terminal (opens, wishes, conversion rate)
  2. Charts saved in analysis/output/
  3. Two ANONYMISED CSV files for Tableau / Power BI (no names):
       analysis/output/wishes_anonymised.csv   one row per wish
       analysis/output/visits_by_day.csv       page opens and wishes per day

Usage
  # read straight from DynamoDB (needs AWS CLI credentials set up)
  python analysis/analyse_wishes.py --region eu-west-2

  # or read wishes from a CSV you exported
  python analysis/analyse_wishes.py --csv wishes_export.csv

Install first:
  pip install pandas matplotlib boto3
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "output"


def scan_table(table_name, region):
    import boto3

    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return pd.DataFrame(items)


def prepare_wishes(df):
    if df.empty:
        raise SystemExit("No wishes found yet. Share the link and try again later.")
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["created_at_uk"] = df["created_at"].dt.tz_convert("Europe/London")
    df["date"] = df["created_at_uk"].dt.date
    df["hour"] = df["created_at_uk"].dt.hour
    df["weekday"] = df["created_at_uk"].dt.day_name()
    df["city"] = df["city"].fillna("Unknown").str.strip().str.title()
    return df


def prepare_visits(metrics_df):
    """Turn the counter rows (visits#YYYY-MM-DD) into a per-day table."""
    if metrics_df.empty or "metric" not in metrics_df:
        return pd.DataFrame(columns=["date", "page_opens"]), 0
    m = metrics_df.copy()
    m["count"] = m["count"].astype(int)
    total = int(m.loc[m.metric == "visits#total", "count"].sum())
    daily = m[m.metric.str.match(r"^visits#\d{4}-\d{2}-\d{2}$")].copy()
    daily["date"] = pd.to_datetime(daily.metric.str.split("#").str[1]).dt.date
    daily = daily.rename(columns={"count": "page_opens"})[["date", "page_opens"]]
    return daily.sort_values("date"), total


def summarise(wishes, visits_total):
    n = len(wishes)
    print("\n=== Diwali Cloud Wishes: summary ===")
    print(f"Page opens (tracked)  : {visits_total}")
    print(f"Wishes submitted      : {n}")
    if visits_total:
        print(f"Conversion rate       : {n / visits_total:.0%}")
    print(f"Unique cities         : {wishes.loc[wishes.city != 'Unknown', 'city'].nunique()}")
    busiest = wishes.groupby("hour").size().idxmax()
    print(f"Busiest hour (UK)     : {busiest:02d}:00 - {busiest:02d}:59")
    print("\nTop cities:")
    print(wishes["city"].value_counts().head(10).to_string())


def charts(wishes, daily):
    by_city = wishes["city"].value_counts().head(10).sort_values()
    ax = by_city.plot(kind="barh", color="#ff9f1c", figsize=(8, 5))
    ax.set_title("Wishes by city (top 10)")
    ax.set_xlabel("Number of wishes")
    plt.tight_layout(); plt.savefig(OUTPUT_DIR / "wishes_by_city.png", dpi=150); plt.close()

    by_hour = wishes.groupby("hour").size().reindex(range(24), fill_value=0)
    ax = by_hour.plot(kind="bar", color="#7b5ea7", figsize=(9, 4))
    ax.set_title("When people submitted their wish (UK time)")
    ax.set_xlabel("Hour of day"); ax.set_ylabel("Number of wishes")
    plt.tight_layout(); plt.savefig(OUTPUT_DIR / "wishes_by_hour.png", dpi=150); plt.close()

    if not daily.empty:
        ax = daily.set_index("date")[["page_opens", "wishes"]].plot(kind="bar", figsize=(8, 4), color=["#5ec8f2", "#ff9f1c"])
        ax.set_title("Page opens vs wishes per day")
        ax.set_xlabel("Date"); ax.set_ylabel("Count")
        plt.tight_layout(); plt.savefig(OUTPUT_DIR / "opens_vs_wishes.png", dpi=150); plt.close()

    print(f"\nCharts saved in: {OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Analyse Diwali Cloud Wishes data")
    parser.add_argument("--table", default="diwali_wishes", help="Wishes table name")
    parser.add_argument("--metrics-table", default="diwali_metrics", help="Page-open counters table")
    parser.add_argument("--region", default="eu-west-2", help="AWS region")
    parser.add_argument("--csv", help="Read wishes from this CSV instead of DynamoDB")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)

    wishes = pd.read_csv(args.csv) if args.csv else scan_table(args.table, args.region)
    wishes = prepare_wishes(wishes)

    try:
        metrics_df = pd.DataFrame() if args.csv else scan_table(args.metrics_table, args.region)
    except Exception as err:
        print(f"Could not read {args.metrics_table}: {err}")
        metrics_df = pd.DataFrame()
    daily, visits_total = prepare_visits(metrics_df)

    wishes_per_day = wishes.groupby("date").size().rename("wishes").reset_index()
    daily = pd.merge(daily, wishes_per_day, on="date", how="outer").fillna(0).sort_values("date")
    daily[["page_opens", "wishes"]] = daily[["page_opens", "wishes"]].astype(int)

    summarise(wishes, visits_total)
    charts(wishes, daily)

    # BI exports: names are personal data, so they are never written to these files.
    wishes[["wish_id", "city", "created_at_uk", "date", "hour", "weekday"]].to_csv(
        OUTPUT_DIR / "wishes_anonymised.csv", index=False)
    daily.to_csv(OUTPUT_DIR / "visits_by_day.csv", index=False)
    print(f"Tableau / Power BI files saved in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
