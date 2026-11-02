#!/usr/bin/env bash
# Load the synthetic CSVs into BigQuery.
# Usage: PROJECT_ID=my-project ./scripts/load_bigquery.sh [data_dir] [dataset]
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
DATA_DIR="${1:-data/sample}"
DATASET="${2:-retail_demo}"

for table in stores products inventory_counts pnl_monthly; do
  echo "Loading ${table}..."
  bq --project_id="${PROJECT_ID}" load \
    --replace \
    --source_format=CSV \
    --skip_leading_rows=1 \
    --autodetect \
    "${DATASET}.${table}" \
    "${DATA_DIR}/${table}.csv"
done

echo "Done. Tables in ${PROJECT_ID}:${DATASET}"
