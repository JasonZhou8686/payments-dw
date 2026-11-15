"""
Generate synthetic card-payments data and load it into BigQuery dataset `raw`, one day at a time.
See docs/decisions/0002-daily-loads.md.

Tables produced:
  raw.merchants       one row per merchant, state as of the run date (replaced whole on every run)
  raw.transactions    card transactions; nested STRUCT `card` and ARRAY<STRUCT> `line_items`
                      partitioned by DATE(created_at), clustered by merchant_id
  raw.refunds         partitioned by DATE(created_at)
  raw.chargebacks     state as of the run date (replaced whole on every run: status/resolved_at change)
  raw.payouts         daily settlement per merchant, partitioned by payout_date

Generation is deterministic. The simulation starts at SIM_START, and every draw for one merchant on one day
(transactions, their refunds and chargebacks, and that day's payout status) comes from its own generator seeded
from (merchant_id, day). Day D's rows are identical whether you generate up to D or up to D + 30.

A run for --date D is the data as of the end of D (as_of = D + 1 day): nothing dated on or after as_of exists.
It overwrites partition D of transactions, refunds and payouts (WRITE_TRUNCATE on the partition decorator, so
reruns are idempotent), and replaces chargebacks and merchants whole.

Usage:
  export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/dbt-runner.json
  export GCP_PROJECT=<project-id>
  python scripts/generate_data.py --init                          # once: drop and recreate the empty raw tables
  python scripts/generate_data.py --date 2026-09-30               # load one day (what Airflow runs)
  python scripts/generate_data.py --date 2026-09-30 --no-load     # only write local JSONL files

Money is stored as INT64 cents, as a real processor would. All timestamps are UTC.
"""

import argparse
import hashlib
import json
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
from faker import Faker
from google.cloud import bigquery

fake = Faker("en_CA")

SIM_START = datetime(2026, 7, 3)
SIGNUP_START = (SIM_START - timedelta(days=365)).date()
SIGNUP_END = date(2026, 10, 1)

INDUSTRIES = ["restaurant", "retail", "salon", "contractor", "professional_services", "ecommerce", "fitness"]
PLANS = ["starter", "growth", "enterprise"]
CARD_BRANDS = {"visa": 0.55, "mastercard": 0.32, "amex": 0.10, "discover": 0.03}
TXN_STATUS = {"approved": 0.955, "declined": 0.04, "error": 0.005}
MERCHANT_STATUS = {"active": 0.85, "paused": 0.08, "churned": 0.05, "under_review": 0.02}
PAYOUT_STATUS = {"paid": 0.97, "pending": 0.02, "failed": 0.01}
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

# Day-partitioned event tables -> partition column. Tables not listed are replaced whole on every run.
PARTITION_FIELDS = {"transactions": "created_at", "refunds": "created_at", "payouts": "payout_date"}
CLUSTER_FIELDS = {"transactions": ["merchant_id"]}


def seed_for(*parts) -> int:
    """Stable 64-bit seed from any key parts (unlike hash(), it doesn't change between Python processes)."""
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def weighted(rng: random.Random, choices: dict):
    return rng.choices(list(choices), weights=list(choices.values()), k=1)[0]


def ts(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def gen_merchants(n: int):
    """The full, fixed merchant set. Each merchant's attributes come from a generator seeded by its id."""
    rows = []
    for i in range(n):
        merchant_id = f"m_{i:05d}"
        seed = seed_for("merchant", merchant_id)
        rng = random.Random(seed)
        fake.seed_instance(seed)
        signup = fake.date_between(start_date=SIGNUP_START, end_date=SIGNUP_END)
        plan = weighted(rng, {"starter": 0.6, "growth": 0.3, "enterprise": 0.1})
        rows.append(
            {
                "merchant_id": merchant_id,
                "business_name": fake.company(),
                "industry": rng.choice(INDUSTRIES),
                "plan": plan,
                "status": weighted(rng, MERCHANT_STATUS),
                "province": rng.choice(PROVINCES),
                "signup_date": signup.isoformat(),
                "monthly_fee_cents": {"starter": 0, "growth": 2900, "enterprise": 9900}[plan],
                "updated_at": ts(datetime.combine(signup, time.min)),
            }
        )
    return rows


def gen_events(merchants, as_of: datetime, avg_per_merchant_day: float):
    """Simulate every day from SIM_START up to (not including) as_of.

    All draws for one merchant-day happen in the same order whatever as_of is; as_of only decides which of the
    drawn rows exist yet. That keeps day D identical across runs with different --date.
    """
    txns, refunds, chargebacks = [], [], []
    payout_status = {}
    active = [m for m in merchants if m["status"] in ("active", "paused")]
    for d in range((as_of - SIM_START).days):
        day = SIM_START + timedelta(days=d)
        # weekend lift for retail/restaurant, mild overall weekly seasonality
        dow_mult = 1.25 if day.weekday() >= 5 else 1.0
        for m in active:
            if day.date().isoformat() < m["signup_date"]:
                continue  # no sales before the merchant signed up
            seed = seed_for(m["merchant_id"], day.date().isoformat())
            rng = random.Random(seed)
            fake.seed_instance(seed)
            payout_status[(m["merchant_id"], day.date())] = weighted(rng, PAYOUT_STATUS)
            size_mult = {"starter": 0.5, "growth": 1.0, "enterprise": 3.0}[m["plan"]]
            n = max(0, int(rng.gauss(avg_per_merchant_day * size_mult * dow_mult, 2)))
            for _ in range(n):
                created = day + timedelta(seconds=rng.randint(8 * 3600, 22 * 3600))
                amount = int(abs(rng.gauss(6500, 4500))) + 200
                brand = weighted(rng, CARD_BRANDS)
                fee_bps = 290 if brand == "amex" else 200
                fee = (amount * fee_bps) // 10000 + 30
                status = weighted(rng, TXN_STATUS)
                n_items = rng.choice([1, 1, 1, 2, 3])
                items = [
                    {
                        "sku": f"sku_{rng.randint(100, 999)}",
                        "description": fake.word(),
                        "quantity": rng.randint(1, 3),
                        "unit_price_cents": rng.randint(300, 15000),
                    }
                    for _ in range(n_items)
                ]
                t = {
                    "transaction_id": f"txn_{rng.getrandbits(64):016x}",
                    "merchant_id": m["merchant_id"],
                    "created_at": ts(created),
                    "amount_cents": amount,
                    "fee_cents": fee if status == "approved" else 0,
                    "currency": "CAD",
                    "status": status,
                    "channel": weighted(rng, {"card_present": 0.6, "online": 0.3, "invoice": 0.1}),
                    "card": {
                        "brand": brand,
                        "last4": f"{rng.randint(0, 9999):04d}",
                        "funding": weighted(rng, {"credit": 0.7, "debit": 0.28, "prepaid": 0.02}),
                        "country": weighted(rng, {"CA": 0.9, "US": 0.09, "GB": 0.01}),
                    },
                    "line_items": items,
                    "metadata_json": json.dumps({"terminal_id": f"term_{rng.randint(1, 20)}", "tip_cents": rng.choice([0, 0, 0, 300, 500])}),
                }
                txns.append(t)
                if status == "approved":
                    if rng.random() < 0.03:
                        refunded = created + timedelta(days=rng.randint(0, 14))
                        refund = {
                            "refund_id": f"rf_{rng.getrandbits(48):012x}",
                            "transaction_id": t["transaction_id"],
                            "merchant_id": m["merchant_id"],
                            "amount_cents": amount if rng.random() < 0.8 else amount // 2,
                            "reason": rng.choice(["requested_by_customer", "duplicate", "fraudulent"]),
                            "created_at": ts(refunded),
                        }
                        if refunded < as_of:
                            refunds.append(refund)
                    if rng.random() < 0.006:
                        opened = created + timedelta(days=rng.randint(5, 60))
                        resolution = opened + timedelta(days=rng.randint(10, 45))
                        resolved_draw = rng.random() < 0.7
                        outcome = weighted(rng, {"won": 0.55, "lost": 0.45})
                        chargeback_id = f"cb_{rng.getrandbits(48):012x}"
                        reason_code = rng.choice(CHARGEBACK_REASONS)
                        if opened < as_of:
                            resolved = resolved_draw and resolution < as_of
                            chargebacks.append(
                                {
                                    "chargeback_id": chargeback_id,
                                    "transaction_id": t["transaction_id"],
                                    "merchant_id": m["merchant_id"],
                                    "amount_cents": amount,
                                    "reason_code": reason_code,
                                    "status": outcome if resolved else "pending",
                                    "opened_at": ts(opened),
                                    "resolved_at": ts(resolution) if resolved else None,
                                }
                            )
    return txns, refunds, chargebacks, payout_status


def gen_payouts(txns, refunds, payout_status, payout_date: date):
    """One payout per merchant with approved sales on payout_date (refunds created that day are deducted)."""
    day_txns = [t for t in txns if t["status"] == "approved" and t["created_at"][:10] == payout_date.isoformat()]
    if not day_txns:
        return []
    df = pd.DataFrame(day_txns)
    g = df.groupby("merchant_id").agg(gross_cents=("amount_cents", "sum"), fees_cents=("fee_cents", "sum")).reset_index()
    day_refunds = [r for r in refunds if r["created_at"][:10] == payout_date.isoformat()]
    if day_refunds:
        rg = pd.DataFrame(day_refunds).groupby("merchant_id")["amount_cents"].sum().rename("refunds_cents").reset_index()
        g = g.merge(rg, on="merchant_id", how="left")
    else:
        g["refunds_cents"] = 0
    g["refunds_cents"] = g["refunds_cents"].fillna(0).astype(int)
    g["net_cents"] = g["gross_cents"] - g["fees_cents"] - g["refunds_cents"]
    rows = []
    for _, r in g.iterrows():
        rows.append(
            {
                "payout_id": f"po_{r['merchant_id']}_{payout_date.isoformat()}",
                "merchant_id": r["merchant_id"],
                "payout_date": payout_date.isoformat(),
                "gross_cents": int(r["gross_cents"]),
                "fees_cents": int(r["fees_cents"]),
                "refunds_cents": int(r["refunds_cents"]),
                "net_cents": int(r["net_cents"]),
                "status": payout_status[(r["merchant_id"], payout_date)],
                # end-of-day settlement batch: must stay before as_of (payout_date + 1 day)
                "created_at": ts(datetime.combine(payout_date, time(23, 0))),
            }
        )
    return rows


def write_jsonl(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def init_tables(client: bigquery.Client, dataset: str):
    """Drop and recreate the five raw tables, empty, with their partitioning."""
    ds = bigquery.Dataset(f"{client.project}.{dataset}")
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)
    for name, schema in RAW_SCHEMAS.items():
        table_ref = f"{client.project}.{dataset}.{name}"
        client.delete_table(table_ref, not_found_ok=True)
        table = bigquery.Table(table_ref, schema=schema)
        if name in PARTITION_FIELDS:
            table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field=PARTITION_FIELDS[name])
        if name in CLUSTER_FIELDS:
            table.clustering_fields = CLUSTER_FIELDS[name]
        client.create_table(table)
        print(f"  created {table_ref}")


def load_table(client: bigquery.Client, dataset: str, table: str, path: Path, run_date: date):
    """WRITE_TRUNCATE partition run_date of a partitioned table, or the whole table otherwise."""
    table_ref = f"{client.project}.{dataset}.{table}"
    if table in PARTITION_FIELDS:
        table_ref += f"${run_date:%Y%m%d}"
    cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=RAW_SCHEMAS[table],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with path.open("rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=cfg)
    job.result()
    print(f"  loaded {job.output_rows:>8,} rows -> {table_ref}")


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="drop and recreate the five raw tables, empty (run once)")
    mode.add_argument("--date", type=date.fromisoformat, help="load one day, YYYY-MM-DD (data as of the end of that day)")
    ap.add_argument("--merchants", type=int, default=500)
    ap.add_argument("--avg-txn", type=float, default=4.0, help="avg transactions per growth-plan merchant per day")
    ap.add_argument("--dataset", default="raw")
    ap.add_argument("--out", default="data", help="local folder for the generated JSONL")
    ap.add_argument("--no-load", action="store_true", help="only write local files")
    args = ap.parse_args()

    if args.init and args.no_load:
        raise SystemExit("--init only touches BigQuery; nothing to do with --no-load")

    if args.date:
        if args.date < SIM_START.date():
            raise SystemExit(f"--date must be on or after SIM_START ({SIM_START.date()})")
        as_of = datetime.combine(args.date + timedelta(days=1), time.min)
        out = Path(args.out)

        print(f"generating {SIM_START.date()} .. {args.date} (as_of {as_of.isoformat()}) ...")
        all_merchants = gen_merchants(args.merchants)
        txns, refunds, chargebacks, payout_status = gen_events(all_merchants, as_of, args.avg_txn)
        day = args.date.isoformat()
        tables = {
            "merchants": [m for m in all_merchants if m["signup_date"] <= day],
            "transactions": [t for t in txns if t["created_at"][:10] == day],
            "refunds": [r for r in refunds if r["created_at"][:10] == day],
            "chargebacks": chargebacks,
            "payouts": gen_payouts(txns, refunds, payout_status, args.date),
        }
        for name, rows in tables.items():
            write_jsonl(rows, out / f"{name}.jsonl")
            scope = f"partition {day}" if name in PARTITION_FIELDS else "whole table"
            print(f"  {name:<13} {len(rows):>8,} rows  ({scope})")

        if args.no_load:
            return

    project = os.environ.get("GCP_PROJECT")
    if not project:
        raise SystemExit("set GCP_PROJECT=<your project id>")
    client = bigquery.Client(project=project)

    if args.init:
        print(f"initialising {project}.{args.dataset} ...")
        init_tables(client, args.dataset)
    else:
        print(f"loading into {project}.{args.dataset} ...")
        for name in tables:
            load_table(client, args.dataset, name, out / f"{name}.jsonl", args.date)
    print("done")


if __name__ == "__main__":
    main()
