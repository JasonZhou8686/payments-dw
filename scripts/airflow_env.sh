# Usage: source scripts/airflow_env.sh
source .venv-airflow/bin/activate
export AIRFLOW_HOME=$HOME/airflow
export AIRFLOW__CORE__DAGS_FOLDER=$PWD/dags
export AIRFLOW__CORE__LOAD_EXAMPLES=False