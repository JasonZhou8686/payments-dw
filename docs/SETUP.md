# Setup

## Google Cloud
1. Create a GCP project with BigQuery enabled. Note the project ID.
2. Create a service account `dbt-runner` with two roles: **BigQuery Data Editor** and **BigQuery Job User**.
3. Create a JSON key for it and save it outside the repo:
   ```bash
   mkdir -p ~/.gcp
   mv ~/Downloads/<key-file>.json ~/.gcp/dbt-runner.json
   chmod 600 ~/.gcp/dbt-runner.json
   ```

## Local environment
Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p ~/.dbt
cp profiles.yml.example ~/.dbt/profiles.yml     # then edit project and keyfile in the dev target
```

Add to `~/.zshrc`, then open a new terminal:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/dbt-runner.json
export GCP_PROJECT=<your-project-id>
```

Check the connection:

```bash
dbt deps
dbt debug
```

Every check should say `OK`.

## Load data and build
```bash
python scripts/generate_data.py --init                 # once: drop and recreate the five raw tables, empty
python scripts/generate_data.py --date 2026-07-03      # load one day
dbt build --full-refresh
```

`--init` creates the `raw` dataset with five empty tables. `--date D` loads one day as of the end of D, and only
accepts a day that has already ended in UTC. Loading the same day twice gives the same rows, so reruns are safe.
`dbt build` creates the staging, intermediate and marts datasets (prefixed with the dev dataset name, for
example `dbt_jason_marts`), takes the merchant snapshot and runs all tests.

After every `--init`, rebuild from scratch with `dbt build --full-refresh`. The incremental facts only rebuild
the partitions inside their lookback window.

Add `--no-load` to write the JSONL files to `data/` without touching BigQuery.

## Airflow
Airflow gets its own virtual environment, because its dependencies clash with dbt's. Install it with the
constraints file for your Python version:

```bash
python3 -m venv .venv-airflow
source .venv-airflow/bin/activate
pip install "apache-airflow==3.4.0" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.4.0/constraints-3.12.txt"
deactivate
```

In every terminal you use for `airflow` commands, run this from the repo root first:

```bash
source scripts/airflow_env.sh
```

It activates `.venv-airflow` and points Airflow at `dags/`. Then start Airflow and leave it running in its own tab:

```bash
airflow standalone
```

The UI is at http://localhost:8080. The `admin` password is in
`~/airflow/simple_auth_manager_passwords.json.generated`.

The DAG runs every day at midnight UTC for the day that just ended. To load history, set `end_date` in the DAG
to the last day you want, so the scheduler does not create runs past it, unpause the DAG and backfill:

```bash
airflow dags unpause payments_pipeline
airflow backfill create --dag-id payments_pipeline --from-date 2026-07-04 --to-date 2026-09-30 --max-active-runs 1
```

Each run takes about a minute and a half. On a Mac, run `caffeinate -i` in another tab so the laptop does not
sleep, and keep the lid open. When the backfill is done, move `start_date` to the next day, remove `end_date`
and run `airflow dags reserialize`.

Airflow reads the DAG from your working copy. Run it from `main`, because switching branches changes the live DAG.

## CI
The workflow in `.github/workflows/dbt_ci.yml` runs on every pull request. It needs two repository secrets:

- `GCP_PROJECT`: the project ID
- `GCP_SA_KEY`: the full contents of the service account key file

## Coding agent (optional)
Install Claude Code and start it from the repo root so it loads `CLAUDE.md` and the skills in `.claude/skills/`.
The skills run `dbt` commands, so activate the virtual environment first.
