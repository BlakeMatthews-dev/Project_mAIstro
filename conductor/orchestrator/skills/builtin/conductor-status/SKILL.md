---
name: conductor-status
description: "Check conductor system health — services, quotas, and active recipes"
version: 1.0.0
user-invocable: true
---

# Conductor Status Check

When the user asks about system health, status, or diagnostics:

1. Check the health of all conductor services:
   - Gateway (port 9090)
   - Conductor Router (port 8100)
   - LiteLLM (port 4000)
   - Langfuse (port 3100)
   - OpenWebUI (port 3200)

2. Report quota status from `/status/quotas`

3. Report any active agent recipes and their variant performance

Respond with a clear status table showing each service and its health.
