# Setup

1. GCP project with billing or sandbox, BigQuery enabled. Service account `dbt-runner` with BigQuery Admin (personal
   project only — prefer Data Editor + Job User in a real org). Key saved at `~/.gcp/dbt-runner.json`, `chmod 600`.
2. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. `mkdir -p ~/.dbt && cp profiles.yml.example ~/.dbt/profiles.yml` — edit `project` and `keyfile`.
4. Add to `~/.zshrc`:
   ```
   export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/dbt-runner.json
   export GCP_PROJECT=<your-project-id>
   ```
5. `dbt deps && dbt debug` — all `[OK]`.
6. `python scripts/generate_data.py --merchants 500 --days 90` — creates dataset `raw` and five tables.
7. `dbt build` — builds the example staging model, snapshot, and runs tests.
8. In BigQuery, open `raw.transactions` → Details: note it's partitioned and clustered. Run
   `select count(*) from raw.transactions where date(created_at) = '2026-09-15'` and compare bytes processed with the
   same query without the `where`.

Optional: install the Google Cloud SDK (`brew install google-cloud-sdk`) so the agent skills can use `bq show --schema`.
Then `gcloud auth activate-service-account --key-file ~/.gcp/dbt-runner.json` and `gcloud config set project $GCP_PROJECT`.
