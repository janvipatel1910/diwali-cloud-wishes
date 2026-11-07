"""
Diwali Cloud Wishes - data analysis
-----------------------------------
Reads the wishes saved in DynamoDB (or an exported CSV) and produces:
  1. A short summary in the terminal
  2. Charts saved in analysis/output/

Usage
  # Option A: read straight from DynamoDB (needs AWS CLI credentials set up)
  python analysis/analyse_wishes.py --table diwali_wishes --region eu-west-2

  # Option B: read from a CSV you exported
  python analysis/analyse_wishes.py --csv wishes_export.csv

Install first:
  pip install pandas matplotlib boto3
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "output"


def load_from_dynamodb(table_name, region):
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


def prepare(df):
    if df.empty:
        raise SystemExit("No wishes found yet. Share the link and try again later.")
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["created_at_uk"] = df["created_at"].dt.tz_convert("Europe/London")
    df["date"] = df["created_at_uk"].dt.date
    df["hour"] = df["created_at_uk"].dt.hour
    df["city"] = df["city"].fillna("Unknown").str.strip().str.title()
    return df


def summarise(df):
    print("\n=== Diwali Cloud Wishes: summary ===")
    print(f"Total wishes deployed : {len(df)}")
    print(f"Unique cities         : {df.loc[df.city != 'Unknown', 'city'].nunique()}")
    print(f"First wish (UK time)  : {df.created_at_uk.min():%d %b %Y %H:%M}")
    print(f"Latest wish (UK time) : {df.created_at_uk.max():%d %b %Y %H:%M}")
    busiest = df.groupby("hour").size().idxmax()
    print(f"Busiest hour (UK)     : {busiest:02d}:00 - {busiest:02d}:59")
    print("\nTop cities:")
    print(df["city"].value_counts().head(10).to_string())


def charts(df):
    OUTPUT_DIR.mkdir(exist_ok=True)

    by_city = df["city"].value_counts().head(10).sort_values()
    ax = by_city.plot(kind="barh", color="#ff9f1c", figsize=(8, 5))
    ax.set_title("Wishes by city (top 10)")
    ax.set_xlabel("Number of wishes")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "wishes_by_city.png", dpi=150)
    plt.close()

    by_hour = df.groupby("hour").size().reindex(range(24), fill_value=0)
    ax = by_hour.plot(kind="bar", color="#7b5ea7", figsize=(9, 4))
    ax.set_title("When people opened their wishes (UK time)")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Number of wishes")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "wishes_by_hour.png", dpi=150)
    plt.close()

    by_day = df.groupby("date").size().cumsum()
    ax = by_day.plot(marker="o", color="#2a9d8f", figsize=(8, 4))
    ax.set_title("Cumulative wishes over time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Total wishes")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "wishes_cumulative.png", dpi=150)
    plt.close()

    print(f"\nCharts saved in: {OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Analyse Diwali Cloud Wishes data")
    parser.add_argument("--table", help="DynamoDB table name")
    parser.add_argument("--region", default="eu-west-2", help="AWS region")
    parser.add_argument("--csv", help="Path to an exported CSV file")
    args = parser.parse_args()

    if args.csv:
        df = pd.read_csv(args.csv)
    elif args.table:
        df = load_from_dynamodb(args.table, args.region)
    else:
        raise SystemExit("Give either --table or --csv")

    df = prepare(df)
    summarise(df)
    charts(df)

    # Names are personal data: the export used for sharing drops them.
    df.drop(columns=["name"], errors="ignore").to_csv(
        OUTPUT_DIR / "wishes_anonymised.csv", index=False
    )


if __name__ == "__main__":
    main()
