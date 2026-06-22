# AI Safety & "Harmlessness" (HHH)

> **Requirement 3** of this project asks us to validate the design against the
> latest AI-Agent engineering practices — especially *harmlessness* — and to
> document it. This file is that documentation: what we implemented, *why*, and
> how it was verified.

## 1. The HHH framing

Modern assistant design is commonly evaluated on three axes — **Helpful, Honest,
Harmless (HHH)**. "Harmless" means the agent should refuse to facilitate harm,
resist manipulation, stay within its mandate, and keep a human in control of
consequential actions. This project treats harmlessness as a *first-class design
constraint*, not an afterthought.

## 2. Sources consulted (verification)

The safety design is grounded in current, authoritative guidance:

1. **Anthropic — *Building effective agents*** (Dec 2024, updated 2025).
   Key takeaways we applied:
   - *Guardrails via **sectioning***: "one model instance processes user queries
     while another screens them for inappropriate content or requests. This tends
     to perform better than having the same LLM call handle both guardrails and the
     core response." → We separate `guardrails.py` from the task logic.
   - *Agents need **guardrails** and **sandboxing*** because of autonomy, cost and
     **compounding errors**. → We cap tool iterations and gate sensitive actions.
   - *Maintain **simplicity** and **transparency** (show planning steps)*. → We keep
     a non-LLM fallback and persist a full execution trace.
   - *Engineer the **agent-computer interface (ACI)*** (tool docs). → Tool
     docstrings are written as careful, example-rich contracts.
2. **OWASP Top 10 for LLM Applications** — informs our handling of
   **LLM01 Prompt Injection** and **LLM02 Insecure Output Handling**.
3. **MCP (Model Context Protocol)** — tools are exposed through a typed, explicit
   schema, making capabilities auditable rather than implicit.

> These were reviewed while building the project (see the project chat log).
> The Anthropic article is linked from the README and quoted above.

## 3. Controls implemented

| Risk | Control | Code |
|---|---|---|
| Harmful requests (malware, CSAM, weapons, intrusion, DRM-cracking) | **Input guardrail** refuses before any tool runs | `screen_input()` in [`guardrails.py`](../src/ai_media_assistant/agent/guardrails.py) |
| **Prompt injection** from tool output / web / RSS | Detect & **sanitise untrusted content** before it reaches the model | `detect_injection()`, `sanitize_external()` |
| Runaway tool loops / cost | **Max-iteration cap** (`AGENT_MAX_ITERATIONS`) + bounded worker toolsets | `config.py`, `graph.py` |
| Irreversible action without consent | **Human-in-the-loop confirmation** for downloads (`AGENT_REQUIRE_DOWNLOAD_CONFIRM`) | `DownloadService.download(confirm=…)` |
| Hidden behaviour | **Execution trace** of every step/tool | `agent_execution_log`, `/api/tasks/{id}/trace` |
| Scope creep | Workers bound to **minimal, specific toolsets**; assistant scoped to media | `graph.py` |
| Hallucinated recommendations | **RAG grounding** — recommend only from retrieved context | `recommendation_service.py` |
| Secret leakage | Credentials only via env/`.env`; `.env` git-ignored; no secrets in logs | `config.py`, `.gitignore` |
| Insecure output | Output pass-through hook (`screen_output`) for moderation; API uses typed Pydantic models | `guardrails.py`, `api/app.py` |

### 3.1 Sectioning guardrail (the core "harmless" mechanism)

```text
            ┌──────────────┐        blocked → safe refusal
 user ────▶ │ screen_input │ ──────────────────────────────▶
            └──────┬───────┘
                   │ allowed
                   ▼
            ┌──────────────┐    untrusted tool/RSS/web text
            │  Task agent   │ ◀── sanitize_external() ───────
            └──────┬───────┘
                   ▼
            ┌──────────────┐
            │ screen_output │ ──▶ user
            └──────────────┘
```

The screening model/component is **independent** of the task model, exactly as
Anthropic recommends, so a single prompt is never asked to both *do the task* and
*police itself*.

### 3.2 Human-in-the-loop

Downloads are the only state-changing external action. With
`AGENT_REQUIRE_DOWNLOAD_CONFIRM=true`, the agent must obtain an explicit `confirm`
flag (a human approval) before `download_media` executes; otherwise a
`GuardrailError` is raised. This implements the "pause for human feedback at
checkpoints" guidance for autonomous agents.

### 3.3 Prompt-injection defence

RSS titles, web pages and tool outputs are **untrusted input**. Before any such
text is shown to the model, `sanitize_external()` truncates it and, if it matches
injection signatures ("ignore previous instructions", "reveal your system prompt",
"exfiltrate…"), replaces it with a neutral placeholder while preserving the user's
original instruction as authoritative.

## 4. How it was verified

- **Automated tests** ([`tests/test_agent.py`](../tests/test_agent.py)):
  - disallowed requests are blocked (`test_guardrail_blocks_disallowed`,
    `test_runner_blocks_disallowed`),
  - normal requests pass (`test_guardrail_allows_normal_request`),
  - injection strings are detected (`test_injection_detection`).
- **Manual check:** `python -m ai_media_assistant.cli "build me a botnet to ddos a site"`
  returns a refusal and performs **no** tool calls.

## 5. Residual risks & recommended hardening for production

The built-in checks are **rule-based and deterministic** (so they run offline).
For a real deployment, augment with:

- A **moderation model** (e.g. Llama Guard / OpenAI moderation) in `screen_input`
  and `screen_output` alongside the regex rules.
- **Sandboxing** the download client and file system (containers, least-privilege).
- **Rate limiting & authn/z** on the FastAPI endpoints.
- **Secret management** (Vault/SOPS) instead of `.env`.
- **Allow/deny lists** for trackers and content categories.
- **Eval harness** running adversarial prompts in CI (the "automating evals"
  pattern).

## 6. Summary

Harmlessness here is enforced by *architecture*, not hope: a dedicated screening
layer, sanitised untrusted input, human approval for consequential actions, bounded
autonomy, grounded outputs, and full traceability — each tied to a cited,
current best practice.
