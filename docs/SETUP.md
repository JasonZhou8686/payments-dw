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
python scripts/generate_data.py --merchants 500 --days 90
dbt build
```

The loader creates the `raw` dataset with five tables. `dbt build` creates the staging, intermediate and marts
datasets (prefixed with the dev dataset name, for example `dbt_jason_marts`), takes the merchant snapshot and
runs all tests.

After every reload of the raw data, rebuild from scratch:

```bash
dbt build --full-refresh
```

The transaction data is random on each load, and the incremental facts only rebuild the partitions inside their
lookback window.

To see the snapshot record changes, load again with an offset, which changes the plan or status of some merchants:

```bash
python scripts/generate_data.py --merchants 500 --days 90 --day-offset 7
dbt build --full-refresh
```

## CI
The workflow in `.github/workflows/dbt_ci.yml` runs on every pull request. It needs two repository secrets:

- `GCP_PROJECT`: the project ID
- `GCP_SA_KEY`: the full contents of the service account key file

## Coding agent (optional)
Install Claude Code and start it from the repo root so it loads `CLAUDE.md` and the skills in `.claude/skills/`.
The skills run `dbt` commands, so activate the virtual environment first.
