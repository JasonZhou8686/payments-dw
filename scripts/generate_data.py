"""
Generate synthetic card-payments data and load it into BigQuery dataset `raw`.

Tables produced:
  raw.merchants       one row per merchant (current state; re-run with --day-offset to move state forward
                      so dbt snapshots have something to capture)
  raw.transactions    card transactions; nested STRUCT `card` and ARRAY<STRUCT> `line_items`
                      partitioned by DATE(created_at), clustered by merchant_id
  raw.refunds
  raw.chargebacks
  raw.payouts         daily settlement per merchant

Usage:
  export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/dbt-runner.json
  export GCP_PROJECT=<project-id>
  python scripts/generate_data.py --merchants 500 --days 90
  python scripts/generate_data.py --merchants 500 --days 90 --day-offset 7   # a week later: some merchants change status

Money is stored as INT64 cents, as a real processor would. All timestamps are UTC.
"""

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from faker import Faker
from google.cloud import bigquery

fake = Faker("en_CA")

INDUSTRIES = ["restaurant", "retail", "salon", "contractor", "professional_services", "ecommerce", "fitness"]
PLANS = ["starter", "growth", "enterprise"]
CARD_BRANDS = {"visa": 0.55, "mastercard": 0.32, "amex": 0.10, "discover": 0.03}
TXN_STATUS = {"approved": 0.955, "declined": 0.04, "error": 0.005}
MERCHANT_STATUS = {"active": 0.85, "paused": 0.08, "churned": 0.05, "under_review": 0.02}
CHARGEBACK_REASONS = ["fraud", "product_not_received", "duplicate", "not_as_described", "other"]
PROVINCES = ["AB", "BC", "ON", "QC", "SK", "MB", "NS"]

RAW_SCHEMAS = {
    "merchants": [
        bigquery.SchemaField("merchant_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("business_name", "STRING"),
        bigquery.SchemaField("industry", "STRING"),
        bigquery.SchemaField("plan", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("province", "STRING"),
        bigquery.SchemaField("signup_date", "DATE"),
        bigquery.SchemaField("monthly_fee_cents", "INT64"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ],
    "transactions": [
        bigquery.SchemaField("transaction_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("merchant_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("amount_cents", "INT64"),
        bigquery.SchemaField("fee_cents", "INT64"),
        bigquery.SchemaField("currency", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("channel", "STRING"),
        bigquery.SchemaField(
            "card",
            "RECORD",
            fields=[
                bigquery.SchemaField("brand", "STRING"),
                bigquery.SchemaField("last4", "STRING"),
                bigquery.SchemaField("funding", "STRING"),
                bigquery.SchemaField("country", "STRING"),
            ],
        ),
        bigquery.SchemaField(
            "line_items",
            "RECORD",
            mode="REPEATED",
            fields=[
                bigquery.SchemaField("sku", "STRING"),
                bigquery.SchemaField("description", "STRING"),
                bigquery.SchemaField("quantity", "INT64"),
                bigquery.SchemaField("unit_price_cents", "INT64"),
            ],
        ),
        bigquery.SchemaField("metadata_json", "STRING"),
    ],
    "refunds": [
        bigquery.SchemaField("refund_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("transaction_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("merchant_id", "STRING"),
        bigquery.SchemaField("amount_cents", "INT64"),
        bigquery.SchemaField("reason", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
    ],
    "chargebacks": [
        bigquery.SchemaField("chargeback_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("transaction_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("merchant_id", "STRING"),
        bigquery.SchemaField("amount_cents", "INT64"),
        bigquery.SchemaField("reason_code", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("opened_at", "TIMESTAMP"),
        bigquery.SchemaField("resolved_at", "TIMESTAMP"),
    ],
    "payouts": [
        bigquery.SchemaField("payout_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("merchant_id", "STRING"),
        bigquery.SchemaField("payout_date", "DATE"),
        bigquery.SchemaField("gross_cents", "INT64"),
        bigquery.SchemaField("fees_cents", "INT64"),
        bigquery.SchemaField("refunds_cents", "INT64"),
        bigquery.SchemaField("net_cents", "INT64"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
    ],
}


def weighted(choices: dict):
    return random.choices(list(choices), weights=list(choices.values()), k=1)[0]


def ts(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def gen_merchants(n: int, start: datetime, end: datetime, day_offset: int):
    random.seed(42)  # stable merchant set across runs so snapshots see *changes*, not new rows
    rows = []
    for i in range(n):
        signup = fake.date_between(start_date=start - timedelta(days=365), end_date=end)
        plan = weighted({"starter": 0.6, "growth": 0.3, "enterprise": 0.1})
        rows.append(
            {
                "merchant_id": f"m_{i:05d}",
                "business_name": fake.company(),
                "industry": random.choice(INDUSTRIES),
                "plan": plan,
                "status": weighted(MERCHANT_STATUS),
                "province": random.choice(PROVINCES),
                "signup_date": signup.isoformat(),
                "monthly_fee_cents": {"starter": 0, "growth": 2900, "enterprise": 9900}[plan],
                "updated_at": ts(end),
            }
        )
    # With a day offset, flip a few statuses/plans so SCD2 snapshots have history to capture.
    if day_offset:
        random.seed(1000 + day_offset)
        for r in random.sample(rows, k=max(1, n // 25)):
            r["status"] = weighted(MERCHANT_STATUS)
            r["updated_at"] = ts(end + timedelta(days=day_offset))
        for r in random.sample(rows, k=max(1, n // 50)):
            r["plan"] = random.choice(PLANS)
            r["monthly_fee_cents"] = {"starter": 0, "growth": 2900, "enterprise": 9900}[r["plan"]]
            r["updated_at"] = ts(end + timedelta(days=day_offset))
    random.seed()
    return rows


def gen_transactions(merchants, start: datetime, days: int, avg_per_merchant_day: float):
    txns, refunds, chargebacks = [], [], []
    as_of = start + timedelta(days=days)  # snapshot time: nothing may be dated on or after this
    active = [m for m in merchants if m["status"] in ("active", "paused")]
    for d in range(days):
        day = start + timedelta(days=d)
        # weekend lift for retail/restaurant, mild overall weekly seasonality
        dow_mult = 1.25 if day.weekday() >= 5 else 1.0
        for m in active:
            size_mult = {"starter": 0.5, "growth": 1.0, "enterprise": 3.0}[m["plan"]]
            n = max(0, int(random.gauss(avg_per_merchant_day * size_mult * dow_mult, 2)))
            for _ in range(n):
                created = day + timedelta(seconds=random.randint(8 * 3600, 22 * 3600))
                amount = int(abs(random.gauss(6500, 4500))) + 200
                brand = weighted(CARD_BRANDS)
                fee_bps = 290 if brand == "amex" else 200
                fee = (amount * fee_bps) // 10000 + 30
                status = weighted(TXN_STATUS)
                n_items = random.choice([1, 1, 1, 2, 3])
                items = [
                    {
                        "sku": f"sku_{random.randint(100, 999)}",
                        "description": fake.word(),
                        "quantity": random.randint(1, 3),
                        "unit_price_cents": random.randint(300, 15000),
                    }
                    for _ in range(n_items)
                ]
                t = {
                    "transaction_id": f"txn_{uuid.uuid4().hex[:16]}",
                    "merchant_id": m["merchant_id"],
                    "created_at": ts(created),
                    "amount_cents": amount,
                    "fee_cents": fee if status == "approved" else 0,
                    "currency": "CAD",
                    "status": status,
                    "channel": weighted({"card_present": 0.6, "online": 0.3, "invoice": 0.1}),
                    "card": {
                        "brand": brand,
                        "last4": f"{random.randint(0, 9999):04d}",
                        "funding": weighted({"credit": 0.7, "debit": 0.28, "prepaid": 0.02}),
                        "country": weighted({"CA": 0.9, "US": 0.09, "GB": 0.01}),
                    },
                    "line_items": items,
                    "metadata_json": json.dumps({"terminal_id": f"term_{random.randint(1, 20)}", "tip_cents": random.choice([0, 0, 0, 300, 500])}),
                }
                txns.append(t)
                if status == "approved":
                    if random.random() < 0.03:
                        refunded = created + timedelta(days=random.randint(0, 14))
                        if refunded < as_of:
                            refunds.append(
                                {
                                    "refund_id": f"rf_{uuid.uuid4().hex[:12]}",
                                    "transaction_id": t["transaction_id"],
                                    "merchant_id": m["merchant_id"],
                                    "amount_cents": amount if random.random() < 0.8 else amount // 2,
                                    "reason": random.choice(["requested_by_customer", "duplicate", "fraudulent"]),
                                    "created_at": ts(refunded),
                                }
                            )
                    if random.random() < 0.006:
                        opened = created + timedelta(days=random.randint(5, 60))
                        if opened < as_of:
                            resolution = opened + timedelta(days=random.randint(10, 45))
                            resolved = random.random() < 0.7 and resolution < as_of
                            chargebacks.append(
                                {
                                    "chargeback_id": f"cb_{uuid.uuid4().hex[:12]}",
                                    "transaction_id": t["transaction_id"],
                                    "merchant_id": m["merchant_id"],
                                    "amount_cents": amount,
                                    "reason_code": random.choice(CHARGEBACK_REASONS),
                                    "status": weighted({"won": 0.55, "lost": 0.45}) if resolved else "pending",
                                    "opened_at": ts(opened),
                                    "resolved_at": ts(resolution) if resolved else None,
                                }
                            )
    return txns, refunds, chargebacks


def gen_payouts(txns, refunds):
    df = pd.DataFrame([t for t in txns if t["status"] == "approved"])
    df["payout_date"] = pd.to_datetime(df["created_at"]).dt.date
    g = df.groupby(["merchant_id", "payout_date"]).agg(gross_cents=("amount_cents", "sum"), fees_cents=("fee_cents", "sum")).reset_index()
    if refunds:
        rf = pd.DataFrame(refunds)
        rf["payout_date"] = pd.to_datetime(rf["created_at"]).dt.date
        rg = rf.groupby(["merchant_id", "payout_date"])["amount_cents"].sum().rename("refunds_cents").reset_index()
        g = g.merge(rg, on=["merchant_id", "payout_date"], how="left")
    else:
        g["refunds_cents"] = 0
    g["refunds_cents"] = g["refunds_cents"].fillna(0).astype(int)
    g["net_cents"] = g["gross_cents"] - g["fees_cents"] - g["refunds_cents"]
    rows = []
    for _, r in g.iterrows():
        pd_ = r["payout_date"]
        rows.append(
            {
                "payout_id": f"po_{r['merchant_id']}_{pd_.isoformat()}",
                "merchant_id": r["merchant_id"],
                "payout_date": pd_.isoformat(),
                "gross_cents": int(r["gross_cents"]),
                "fees_cents": int(r["fees_cents"]),
                "refunds_cents": int(r["refunds_cents"]),
                "net_cents": int(r["net_cents"]),
                "status": weighted({"paid": 0.97, "pending": 0.02, "failed": 0.01}),
                "created_at": ts(datetime.combine(pd_, datetime.min.time()) + timedelta(days=1, hours=6)),
            }
        )
    return rows


def write_jsonl(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load_table(client: bigquery.Client, dataset: str, table: str, path: Path):
    table_ref = f"{client.project}.{dataset}.{table}"
    cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=RAW_SCHEMAS[table],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    if table == "transactions":
        cfg.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="created_at")
        cfg.clustering_fields = ["merchant_id"]
    with path.open("rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=cfg)
    job.result()
    print(f"  loaded {job.output_rows:>8,} rows -> {table_ref}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merchants", type=int, default=500)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--avg-txn", type=float, default=4.0, help="avg transactions per growth-plan merchant per day")
    ap.add_argument("--day-offset", type=int, default=0, help="simulate a later load; mutates some merchants")
    ap.add_argument("--dataset", default="raw")
    ap.add_argument("--out", default="data", help="local folder for the generated JSONL")
    ap.add_argument("--no-load", action="store_true", help="only write local files")
    args = ap.parse_args()

    end = datetime(2026, 10, 1)
    start = end - timedelta(days=args.days)
    out = Path(args.out)

    print("generating...")
    merchants = gen_merchants(args.merchants, start, end, args.day_offset)
    txns, refunds, chargebacks = gen_transactions(merchants, start, args.days, args.avg_txn)
    payouts = gen_payouts(txns, refunds)

    tables = {"merchants": merchants, "transactions": txns, "refunds": refunds, "chargebacks": chargebacks, "payouts": payouts}
    for name, rows in tables.items():
        write_jsonl(rows, out / f"{name}.jsonl")
        print(f"  {name:<13} {len(rows):>8,} rows")

    if args.no_load:
        return

    project = os.environ.get("GCP_PROJECT")
    if not project:
        raise SystemExit("set GCP_PROJECT=<your project id>")
    client = bigquery.Client(project=project)
    ds = bigquery.Dataset(f"{project}.{args.dataset}")
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)
    print(f"loading into {project}.{args.dataset} ...")
    for name in tables:
        load_table(client, args.dataset, name, out / f"{name}.jsonl")
    print("done")


if __name__ == "__main__":
    main()
