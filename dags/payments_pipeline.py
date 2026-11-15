"""Daily payments pipeline.

Each run loads one day of raw data for its logical date ({{ ds }}) with scripts/generate_data.py --date,
then runs dbt build. The load overwrites that day's partitions, so rerunning a day is safe.
Runs one at a time, in date order (max_active_runs=1), because the incremental models' lookback
windows are measured from the latest partition already built.
"""
from datetime import datetime, timedelta
from pathlib import Path

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.timetables.interval import CronDataIntervalTimetable

PROJECT_DIR = Path(__file__).resolve().parents[1] # repo root: this file lives in <repo>/dags/
VENV_BIN = PROJECT_DIR / ".venv" / "bin"          # the dbt environment, not Airflow's

with DAG(
    dag_id="payments_pipeline",
    description="Load raw payments data, then dbt build",
    schedule=CronDataIntervalTimetable("@daily", timezone="UTC"),                      # runs daily
    start_date=datetime(2026, 7, 3),
    end_date=datetime(2026, 9, 30),    # temporary: no scheduled runs past the backfilled range
    catchup=False,
    max_active_runs=1,
    tags=["payments", "dbt"],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
) as dag:

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=f"{VENV_BIN}/python -u scripts/generate_data.py --date {{{{ ds }}}}",
        cwd=str(PROJECT_DIR),
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{VENV_BIN}/dbt build ",
        cwd=str(PROJECT_DIR),
    )

    load_raw >> dbt_build