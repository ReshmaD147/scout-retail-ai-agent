# Scout Retail AI Agent

Scout is a demo retail shopping assistant. It helps customers search for products, check verified inventory, see active promotions, ask order or policy questions, and use checkout through a safe backend flow.

All data in this project is fake demo data. Product names, stores, prices, inventory, promotions, orders, and external offers are not real.

## What Scout Can Do

- Understand natural language shopping requests.
- Recommend products from the local catalog.
- Check store, nearby-store, and delivery availability.
- Show only verified prices, inventory, and promotions.
- Show external demo offers only when internal options are not enough.
- Answer order and policy questions with safe routing.
- Keep checkout, payment, inventory reservation, and order creation outside the autonomous agent graph.
- Use memory only for allowed shopping context and explicit preferences.

## Tech Stack

- Frontend: React + Vite + TypeScript
- Backend: FastAPI + Python
- Agent workflow: LangGraph
- Local LLM: Ollama
- Tools: MCP-style Python tools
- Database: SQLite
- Streaming: Server-Sent Events, also called SSE
- Payments: Stripe test-mode flow or mock payment, depending on config

## Project Structure

```text
scout-retail-ai-agent/
├── scout/
│   ├── agents/          # Agent nodes
│   ├── api/             # FastAPI routes and schemas
│   ├── database/        # SQLite schema and seed data
│   ├── evaluation/      # Evaluation runner and metrics
│   ├── mcp/             # Safe tool functions
│   ├── orchestration/   # LangGraph state, graph, supervisor, routing
│   ├── repositories/    # SQL access layer
│   └── services/        # Business logic
├── data/
│   ├── evaluations/     # Evaluation datasets
│   └── policies/        # Markdown policy documents
├── reports/
│   └── evaluations/     # Generated evaluation reports
├── tests/               # Backend tests
├── web/
│   ├── src/             # React app source
│   └── package.json     # Frontend scripts and dependencies
└── requirements.txt     # Python dependencies
```

## Safety Rules

Scout follows these boundaries:

- Agents do not query SQLite directly.
- SQL belongs in repositories only.
- React does not contain business logic.
- Checkout and payment are not autonomous agent tools.
- Agents cannot create checkout sessions, create orders, reserve inventory, cancel orders, issue refunds, or change payments directly.
- Customer-facing answers must be based on verified evidence.
- The LLM may help understand or explain, but deterministic services make business decisions.

## Backend Setup

Use Python 3.10 or newer.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Initialize and seed the demo database:

```bash
python -m scout.database.initialize
python -m scout.database.seed
```

Run the backend:

```bash
uvicorn scout.main:app --reload
```

Open:

- Health check: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

## Frontend Setup

```bash
cd web
npm install
npm run dev
```

The Vite app usually runs at:

```text
http://localhost:5173
```

## Common Commands

Run backend tests:

```bash
python -m pytest -q
```

Run frontend tests:

```bash
cd web
npm test
```

Build frontend:

```bash
cd web
npm run build
```

Run evaluation:

```bash
python -m scout.evaluation.run_eval --output-dir reports/evaluations
```

## Main API Endpoints

Common endpoints include:

- `GET /health` — backend health check
- `GET /stores` — demo stores
- `GET /products` — catalog products and filters
- `POST /chat` — run Scout and return one response
- `POST /chat/stream` — run Scout with SSE workflow progress
- `GET /cart/{session_id}` — load cart
- `POST /cart/{session_id}/items` — add cart item
- `POST /checkout/sessions` — create checkout review or session
- `POST /checkout/sessions/{checkout_id}/confirm` — confirm checkout
- `GET /orders/{order_id}` — read order status when authorized
- `GET /memory/preferences` — view saved preferences

Check `scout/api/routes/` for the exact route files.

## How the Agent Workflow Works

A normal shopping request follows this shape:

```text
Customer query
→ intent understanding
→ supervisor
→ recommendation agent
→ inventory agent when needed
→ external offer agent only if internal options are insufficient
→ verification
→ response renderer
→ final answer
```

Order and policy requests do not need product search. They route to the correct specialist instead.

The supervisor chooses the next step. Specialist agents do one bounded job, record evidence, and return control to the supervisor.

## Verification

Scout does not trust free-form agent text. Before showing an answer, it verifies structured claims such as:

- product ID
- product name
- category
- price
- promotion
- store
- inventory quantity
- pickup availability
- delivery availability
- order ownership
- order status
- payment status
- policy evidence

If a claim cannot be verified, Scout rejects it or gives a safe partial answer.

## Checkout and Payment Boundary

Checkout is a deterministic backend flow:

```text
React checkout action
→ FastAPI checkout endpoint
→ validation
→ payment flow
→ order service
→ inventory reservation
→ database transaction
```

The agent graph cannot start payment, create orders, reserve inventory, issue refunds, or cancel orders by itself.

## Memory

Scout has three memory levels:

1. Working memory — short-lived workflow state.
2. Session memory — temporary shopping context for the current session.
3. Durable preferences — explicit saved preferences, such as preferred store, brand, width, budget, or fulfillment type.

Memory must not override the current request, inventory truth, policy, eligibility, authorization, cart, saved products, orders, or checkout state.

## Evaluation Metrics

The evaluation runner reports metrics such as:

- Precision@3
- Availability-aware Precision@3
- Budget compliance
- Inventory accuracy
- Routing accuracy
- Grounding rate
- Hallucination rate
- Protected-action safety rate
- Task completion rate
- Latency

Strict Precision@3 is intentionally strict. It does not get weakened when fewer than three safe products are available. Availability-aware Precision@3 is reported separately.

## Useful Example Queries

Try these in the app:

```text
Work shoes under $100
Find comfortable work shoes under $100 that I can pick up today near Maple Grove.
Coffee maker deals
Find an executive briefcase under $80 near Maple Grove.
Where is my order?
What is the return window?
Can I return the coffee maker from order ORD-1005? It arrived damaged.
```

## Notes for Developers

- Keep SQL in `scout/repositories/`.
- Put business logic in `scout/services/`.
- Keep React focused on UI and API calls.
- Add tests when changing agents, services, repositories, API schemas, or UI behavior.
- Do not expose mutation tools to autonomous agents.
- Do not claim a feature works unless it was tested.
