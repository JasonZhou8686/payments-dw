"""Load raw payments data, then build and test the dbt project."""
from datetime import datetime
from pathlib import Path

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

PROJECT_DIR = Path(__file__).resolve().parents[1] # repo root: this file lives in <repo>/dags/
VENV_BIN = PROJECT_DIR / ".venv" / "bin"          # the dbt environment, not Airflow's

with DAG(
    dag_id="payments_pipeline",
    description="Load raw payments data, then dbt build",
    schedule=None,                      # no schedule yet, runs only when triggered by hand
    start_date=datetime(2026, 11, 1),
    catchup=False,
    tags=["payments", "dbt"]
) as dag:

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=f"{VENV_BIN}/python -u scripts/generate_data.py --merchants 500 --days 90",
        cwd=str(PROJECT_DIR),
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{VENV_BIN}/dbt build --full-refresh",
        cwd=str(PROJECT_DIR),
    )

    load_raw >> dbt_build