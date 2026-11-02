"""Create (or show the request for) the Conversational Analytics data agent.

The agent points at the BigQuery tables and carries the business context
(definitions, how to compute rates) as a system instruction.

NOTE: The Data Analytics API is evolving (v1beta). Check the field names
against the current docs before running:
https://cloud.google.com/gemini/docs/conversational-analytics-api/overview

Usage:
    python scripts/create_data_agent.py --project my-project --dry-run
    python scripts/create_data_agent.py --project my-project
"""
from __future__ import annotations

import argparse
import json

SYSTEM_INSTRUCTION = """
You are a retail analytics assistant. Answer concisely in the user's language.

Definitions:
- Shrinkage rate = SUM(shrink_value) / SUM(expected_value) from inventory_counts.
- EBIT margin = SUM(ebit) / SUM(revenue) from pnl_monthly.
- "Last month" means the most recent month present in the data.
Join tables on store_id. Always state the period you used.
Prefer a bar chart for rankings and a line chart for trends.
""".strip()

TABLES = ["stores", "products", "inventory_counts", "pnl_monthly"]


def build_body(project: str, dataset: str) -> dict:
    return {
        "description": "Answers questions about synthetic retail store performance.",
        "dataAnalyticsAgent": {
            "publishedContext": {
                "systemInstruction": SYSTEM_INSTRUCTION,
                "datasourceReferences": {
                    "bq": {
                        "tableReferences": [
                            {"projectId": project, "datasetId": dataset, "tableId": t} for t in TABLES
                        ]
                    }
                },
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="retail_demo")
    parser.add_argument("--agent-id", default="retail-analytics-agent")
    parser.add_argument("--location", default="global")
    parser.add_argument("--dry-run", action="store_true", help="Print the request instead of sending it")
    args = parser.parse_args()

    url = (
        f"https://geminidataanalytics.googleapis.com/v1beta/projects/{args.project}"
        f"/locations/{args.location}/dataAgents?dataAgentId={args.agent_id}"
    )
    body = build_body(args.project, args.dataset)

    if args.dry_run:
        print("POST", url)
        print(json.dumps(body, indent=2))
        return

    import google.auth
    import google.auth.transport.requests
    import requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    resp = requests.post(url, headers={"Authorization": f"Bearer {creds.token}"}, json=body, timeout=60)
    print(resp.status_code, resp.text[:2000])
    resp.raise_for_status()


if __name__ == "__main__":
    main()
