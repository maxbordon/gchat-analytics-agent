# Google Chat Analytics Agent

Ask your business data questions in plain language, right inside Google Chat.

> "Which 5 stores have the highest shrinkage rate?"
> → a short answer, a data table and a chart, posted back in the conversation.

The bot runs on **Cloud Run** and delegates the hard part (understanding the
question, writing SQL against **BigQuery**, choosing a chart) to Google's
**Gemini Conversational Analytics API**. This repo is the production glue around
it: secure request handling, async replies, multi-turn context, chart rendering
and infrastructure as code.

![CI](https://github.com/<your-user>/gchat-analytics-agent/actions/workflows/ci.yml/badge.svg)

---

## Why this exists

Business teams ask the same data questions every week and wait on an analyst
or a dashboard change. Putting a conversational agent where they already work
(Google Chat) removes that queue. The same codebase can serve different
domains (finance, inventory, sales) by swapping a YAML profile.

## Architecture

```
 Google Chat ──HTTPS + OIDC token──▶ Cloud Run (Flask)
     ▲                                  │ 1. verify token (audience, issuer)
     │                                  │ 2. reply "working on it" immediately
     │                                  │ 3. background thread:
     │                                  ▼
     │                   Gemini Data Analytics API ──SQL──▶ BigQuery
     │                                  │  text + rows + Vega-Lite spec
     │                                  ▼
     │                   render PNG ──▶ Cloud Storage (private, 5-day TTL)
     │                                  │  V4 signed URL
     └──── Chat REST API (Card v2) ◀────┘
```

## Highlights

| Concern | How it's handled |
|---|---|
| **Security** | Public ingress, but every request's OIDC token is verified (signature, audience, verified email, issuer). Least-privilege service account. Private bucket with signed URLs, no key files. |
| **Latency** | Chat needs a fast response; the agent may take longer. The bot acks instantly and posts the answer asynchronously via the Chat API. |
| **Context** | One agent conversation per Chat space, expired after 30 min idle so stale questions don't pollute new ones. Thread-safe, behind a store interface (swap in Firestore/Redis to scale out). |
| **Rich answers** | Agent output is parsed into text / table / chart; Markdown is converted to Chat syntax; tables are truncated sensibly; Vega-Lite specs are rendered server-side to PNG. Falls back to plain text if a card fails. |
| **Reusability** | Domain wording lives in `config/*.yaml`, so one codebase serves many bots. |
| **Developer experience** | `AGENT_MODE=mock` answers from a synthetic dataset: run and demo everything with no cloud account. 40+ unit tests, CI with lint, tests, `terraform validate` and secret scanning. |

## Quick start (local, no cloud needed)

```bash
git clone https://github.com/<your-user>/gchat-analytics-agent.git
cd gchat-analytics-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env            # mock mode by default
pytest -q                       # run the tests

# Start the server in mock mode
AGENT_MODE=mock SKIP_AUTH=true python -m app.main

# In another terminal: ask a question and see the exact Chat payload
curl -s localhost:8080/dev/ask -H 'Content-Type: application/json' \
  -d '{"question": "Which 5 stores have the highest shrinkage rate?"}'
```

In mock mode, charts are rendered to `out/charts/`.

## Synthetic dataset

`data/generate_data.py` creates a fictional retail chain: stores, products,
monthly inventory counts and a monthly P&L. Distributions are designed so the
data has a story (a few stores with abnormal shrinkage, regional margin
differences, seasonality).

```bash
python data/generate_data.py --stores 120 --months 24 --out data/full
```

| Table | Grain | Key columns |
|---|---|---|
| `stores` | store | region, format, opened_year |
| `products` | SKU | department, unit_cost, unit_price |
| `inventory_counts` | store × month × department | expected_units, counted_units, shrink_value |
| `pnl_monthly` | store × month | revenue, cogs, shrink_cost, staff_cost, rent, ebit |

## Deploy to GCP

```bash
# 1. Infrastructure
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id
terraform init && terraform apply

# 2. Data
cd ..
PROJECT_ID=<project> ./scripts/load_bigquery.sh

# 3. Data agent (check the request first)
python scripts/create_data_agent.py --project <project> --dry-run
python scripts/create_data_agent.py --project <project>

# 4. Build and deploy the image
REPO=$(terraform -chdir=terraform output -raw docker_repository)
gcloud builds submit --tag "$REPO/bot:latest"
URL=$(terraform -chdir=terraform output -raw service_url)
gcloud run services update gchat-analytics-agent-dev --region us-central1 \
  --image "$REPO/bot:latest" \
  --update-env-vars GOOGLE_CHAT_AUDIENCE="$URL"
```

5. In the Google Cloud console, configure the **Google Chat API** app with the
   Cloud Run URL as the HTTP endpoint.

## Project structure

```
app/
  main.py             Flask routes + wiring (app factory)
  bot.py              Event handling: sync ack, async answer, fallbacks
  auth.py             Google Chat OIDC token verification
  agent_client.py     Gemini Data Analytics client + offline mock
  conversations.py    Space → conversation mapping with idle TTL
  response_parser.py  Agent response → text / table / chart
  chat_formatter.py   Markdown → Chat, Cards v2 builder
  chat_client.py      Posting to Chat (with SA impersonation)
  charts.py           Vega-Lite → PNG → GCS signed URL
config/agent.yaml     Default bot profile
examples/             Alternative profiles (finance, shrinkage)
data/                 Synthetic data generator + small sample
scripts/              BigQuery load, data agent creation
terraform/            Cloud Run, IAM, Artifact Registry, GCS, BigQuery
tests/                Unit tests (no network)
```

## Roadmap

- [ ] Firestore-backed conversation store for multi-instance deployments
- [ ] Slash commands (`/reset`, `/help`)
- [ ] Per-user row-level security
- [ ] Cloud Tasks instead of threads for retries and back-pressure

## License

MIT
