from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from rescueops.models import RescueCase
from rescueops.slack_blocks import format_evidence_source


CompletionClient = Callable[[str], str]

ALLOWED_REASONER_MODES = {"llm", "local", "openai-compatible", "ollama"}
DEFAULT_REASONING_MODEL = "qwen3:8b"
DEFAULT_TIMEOUT_SECONDS = 12
MAX_REASONED_RESPONSE_CHARS = 2800


def generate_reasoned_text(
    case: RescueCase,
    task: str,
    fallback: str,
    user_request: str = "",
    completion_client: CompletionClient | None = None,
) -> str:
    prompt = build_reasoning_prompt(case, task, user_request)
    if completion_client is None and not llm_reasoning_enabled():
        return fallback

    try:
        candidate = completion_client(prompt) if completion_client else call_configured_llm(prompt)
    except ReasonerError:
        return fallback

    return validate_reasoned_output(candidate, case, fallback)


def llm_reasoning_enabled() -> bool:
    mode = os.getenv("RESCUEOPS_REASONER_MODE", "deterministic").lower()
    return mode in ALLOWED_REASONER_MODES and bool(os.getenv("RESCUEOPS_LLM_ENDPOINT"))


def build_reasoning_prompt(case: RescueCase, task: str, user_request: str = "") -> str:
    payload = build_grounding_payload(case, task, user_request)
    return (
        "You are RescueOps, a Slack-native revenue rescue agent.\n"
        "Use only the grounded JSON facts below. Do not invent money, dates, owners, channels, evidence, or customer promises.\n"
        "If evidence is missing, say what is missing and keep the recommendation conservative.\n"
        "Write concise Slack mrkdwn. Keep the response operational: decision, why, next action.\n"
        "Return only the final answer. Do not include hidden reasoning, chain-of-thought, or <think> blocks.\n\n"
        f"Grounded RescueCase JSON:\n{json.dumps(payload, indent=2)}"
    )


def build_grounding_payload(case: RescueCase, task: str, user_request: str = "") -> dict[str, Any]:
    top_evidence = sorted(case.evidence, key=lambda item: item.weight, reverse=True)[:6]
    return {
        "task": task,
        "user_request": user_request,
        "account": {
            "id": case.account.account_id,
            "name": case.account.name,
            "segment": case.account.segment,
            "renewal_date": case.account.renewal_date,
            "owner": case.account.owner,
        },
        "metrics": {
            "risk_score": case.risk_score,
            "risk_level": case.risk_level,
            "revenue_at_risk": case.metrics["revenue_at_risk"],
            "expected_revenue_protected": case.metrics["expected_revenue_protected"],
            "evidence_items": case.metrics["evidence_items"],
            "evidence_source": format_evidence_source(case.metrics.get("evidence_source", "unknown")),
            "mean_time_to_rescue_reduction_pct": case.metrics["mean_time_to_rescue_reduction_pct"],
            "old_time_to_plan": case.metrics["old_time_to_plan"],
            "new_time_to_plan": case.metrics["new_time_to_plan"],
        },
        "root_causes": list(case.root_causes),
        "emerging_patterns": case.metrics.get("emerging_patterns", [])[:3],
        "recommended_actions": [
            {
                "title": action.title,
                "owner": action.owner,
                "due": action.due,
                "reason": action.reason,
            }
            for action in case.actions[:4]
        ],
        "evidence": [
            {
                "source": item.source,
                "channel": item.channel,
                "title": item.title,
                "text": item.text,
                "weight": item.weight,
                "tags": list(item.tags),
            }
            for item in top_evidence
        ],
    }


def call_configured_llm(prompt: str) -> str:
    endpoint = os.environ["RESCUEOPS_LLM_ENDPOINT"]
    model = os.getenv("RESCUEOPS_LLM_MODEL", DEFAULT_REASONING_MODEL)
    timeout = int(os.getenv("RESCUEOPS_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))

    if "ollama" in endpoint or endpoint.endswith("/api/chat"):
        payload = {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = post_json(endpoint, payload, timeout)
        message = response.get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        raise ReasonerError("Ollama response did not include message.content.")

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You write grounded Slack operational briefs from supplied JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    response = post_json(endpoint, payload, timeout)
    choices = response.get("choices", [])
    if choices and isinstance(choices[0], dict):
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content
    raise ReasonerError("OpenAI-compatible response did not include choices[0].message.content.")


def post_json(endpoint: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("RESCUEOPS_LLM_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ReasonerError(str(error)) from error


def validate_reasoned_output(candidate: str, case: RescueCase, fallback: str) -> str:
    text = strip_reasoning_traces(candidate).strip()
    if not text or len(text) > MAX_REASONED_RESPONSE_CHARS:
        return fallback
    if case.account.name not in text:
        return fallback
    if mentions_unallowed_money(text, case):
        return fallback
    return text


def strip_reasoning_traces(text: str) -> str:
    return re.sub(r"(?is)<think>.*?</think>", "", text).strip()


def mentions_unallowed_money(text: str, case: RescueCase) -> bool:
    allowed_amounts = {
        int(case.metrics["revenue_at_risk"]),
        int(case.metrics["expected_revenue_protected"]),
        int(case.account.revenue_at_risk),
    }
    for match in re.finditer(r"(?i)(usd\s*)?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|million)?", text):
        raw = match.group(0).lower()
        suffix = (match.group(3) or "").lower()
        if "usd" not in raw and "$" not in raw and suffix not in {"k", "m", "million"}:
            continue
        amount = float(match.group(2).replace(",", ""))
        if suffix == "k":
            amount *= 1_000
        elif suffix in {"m", "million"}:
            amount *= 1_000_000
        if round(amount) not in allowed_amounts:
            return True
    return False


class ReasonerError(Exception):
    pass
