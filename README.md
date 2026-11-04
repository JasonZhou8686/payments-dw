# payments-dw

A small, production-shaped payments data warehouse built with **BigQuery + dbt**, developed with an
AI coding agent whose conventions live in `CLAUDE.md` and `.claude/skills/`.

Domain: a fictional card-payments processor. Merchants sign up, take card transactions, issue
refunds, receive chargebacks, and get paid out.

## Architecture

```
scripts/generate_data.py          synthetic data (Faker) ──► BigQuery  raw.*
                                                                   │
dbt  models/staging/   stg_*      one per raw table, rename + type cast, views
     models/intermediate/ int_*   business logic joins, ephemeral/views
     models/marts/     fct_* dim_*  partitioned incremental facts, dimensions
     snapshots/        SCD2 history of merchants
```

## Setup

See `docs/SETUP.md` for the full walkthrough. Short version:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp profiles.yml.example ~/.dbt/profiles.yml   # then edit project id + keyfile path
export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/dbt-runner.json
export GCP_PROJECT=<your-project-id>

python scripts/generate_data.py --merchants 500 --days 90   # loads raw.* into BigQuery
dbt deps
dbt debug
dbt build
```

## Conventions

All modelling conventions, naming rules and test standards are in `CLAUDE.md`. They are written for
both humans and the coding agent. The agent skills in `.claude/skills/` automate the repetitive parts
(`/new-source`, `/add-tests`, `/review-model`).

## Design decisions

See `docs/decisions/` for short ADRs (why incremental facts, why snapshots, cost choices).
