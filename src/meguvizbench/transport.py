"""Trusted provider transport and the single-turn file submission harness."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from http.client import HTTPException, HTTPSConnection
import os
import socket
import time

from .protocol import BenchError, MAX_PROMPT, decode, encoded, require, validate_submission

MAX_RESPONSE = 192 * 1024


class BudgetExhausted(BenchError):
    pass


@dataclass
class ModelReply:
    status: str
    cost: int | None
    receipt: dict
    content: str | None = None
    retryable: bool = False


def submission_prompt(task):
    return [
        {"role": "system", "content": (
            'Return one JSON object whose keys are exactly the requested file paths and whose values '
            'are complete UTF-8 file contents. Return no markdown, comments outside the JSON, or extra files. '
            'The task is evaluated from the files only. You have no external tools.'
        )},
        {"role": "user", "content": encoded({
            "task": task.prompt, "starter": task.fixture("starter"), "paths": task.files,
        }).decode("utf-8")},
    ]


def model_request(model, messages, output_tokens):
    return {
        "model": model["model_id"], "messages": messages, "max_completion_tokens": output_tokens,
        "response_format": {"type": "json_object"}, "reasoning_effort": "low", "store": False,
        "service_tier": "default",
    }


def charge(model, prompt, output, cached=0, write=0):
    rates = {key: Decimal(str(model[key])) for key in ("input_rate", "cached_rate", "output_rate")}
    total = (
        (prompt - cached - write) * rates["input_rate"] + cached * rates["cached_rate"]
        + write * rates["input_rate"] * Decimal("1.25") + output * rates["output_rate"]
    )
    return int(total.to_integral_value(rounding=ROUND_CEILING))


def reserve(model, body, budget, remaining, calls):
    if calls <= 0 or len(body) > MAX_PROMPT:
        raise BudgetExhausted("request_limit_reached")
    # Count all bytes and framing overhead, applying the more expensive cache-write rate.
    token_allowance = len(body) + 1024
    reserve_microusd = charge(model, token_allowance, budget["output_tokens"], write=token_allowance)
    if reserve_microusd > remaining:
        raise BudgetExhausted("request_reservation_exceeds_trial_budget")
    return reserve_microusd


class OpenAITransport:
    def __init__(self, api_key, connection=HTTPSConnection):
        require(bool(api_key), "missing_openai_api_key")
        self.api_key = api_key
        self.connection = connection

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("OPENAI_API_KEY"))

    def complete(self, body, model, deadline, reserved):
        started = time.monotonic()
        remaining = deadline - started
        if remaining <= 0:
            return ModelReply("timeout", 0, {"called": False, "reserved_microusd": 0, "latency_seconds": 0})
        request_deadline = min(deadline, started + 85)
        conn = self.connection("api.openai.com", timeout=min(85, remaining))
        receipt = {"called": True, "reserved_microusd": reserved, "usage": None, "billing": "unknown"}
        try:
            conn.request("POST", "/v1/chat/completions", body=body, headers={
                "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
            })
            response = conn.getresponse()
            receipt["http_status"] = response.status
            receipt["request_id"] = response.getheader("x-request-id")
            data = bytearray()
            while len(data) <= MAX_RESPONSE:
                remaining = request_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(8192, MAX_RESPONSE + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            receipt["body"] = bytes(data[:MAX_RESPONSE]).decode("utf-8", errors="replace")
            if response.status != 200:
                return ModelReply("api_error", None, receipt, retryable=response.status in {429, 502, 503, 504})
            if len(data) > MAX_RESPONSE:
                return ModelReply("api_error", None, receipt)
            return parse_reply(decode(bytes(data)), model, receipt)
        except (TimeoutError, socket.timeout):
            return ModelReply("timeout" if time.monotonic() >= deadline else "api_error", None, receipt)
        except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
            return ModelReply("api_error", None, receipt)
        finally:
            receipt["latency_seconds"] = round(time.monotonic() - started, 3)
            conn.close()


def parse_reply(payload, model, receipt):
    usage = payload.get("usage")
    cost = None
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details") or {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        cached = details.get("cached_tokens", 0)
        write = details.get("cache_write_tokens", 0)
        if all(type(value) is int and value >= 0 for value in (prompt, completion, cached, write)) and cached + write <= prompt:
            cost = charge(model, prompt, completion, cached, write)
            receipt["usage"] = usage
            receipt["billing"] = "estimated_from_provider_usage"
    receipt["provider_model"] = payload.get("model")
    choices = payload.get("choices")
    if type(choices) is not list or len(choices) != 1:
        return ModelReply("api_error", cost, receipt)
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return ModelReply("api_error", cost, receipt)
    content = message.get("content")
    if choice.get("finish_reason") != "stop" or not isinstance(content, str) or message.get("refusal"):
        return ModelReply("model_error", cost, receipt)
    return ModelReply("received", cost, receipt, content=content)


def parse_submission(text, allowed):
    return validate_submission(decode(text), allowed)
