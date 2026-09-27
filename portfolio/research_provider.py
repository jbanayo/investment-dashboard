"""Provider boundary for on-demand, source-backed AI investment research."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ssl
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from .research import CONFIDENCE_LEVELS, STANCES, TRIGGER_TYPES


PROMPT_VERSION = "research-v1"
SOURCE_TYPES = ("filing", "company", "exchange", "news", "research", "other")


class ProviderError(RuntimeError):
    """A safe, user-readable provider error that never contains credentials."""


class ResearchProvider(Protocol):
    provider_name: str
    model: str

    def research(self, instrument: dict, focus_prompt: str = "") -> dict: ...


class JsonHttpClient:
    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def post_json(self, endpoint: str, payload: dict, headers: dict[str, str]) -> dict:
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(  # nosec B310 - endpoint is fixed by the adapter
                request, timeout=self.timeout_seconds, context=self.ssl_context
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                body = json.loads(error.read().decode("utf-8"))
                message = body.get("error", {}).get("message")
            except (json.JSONDecodeError, UnicodeDecodeError):
                message = None
            raise ProviderError(message or f"Research provider returned HTTP {error.code}.") from error
        except (URLError, TimeoutError) as error:
            raise ProviderError("Could not reach the research provider. Check the internet connection.") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderError("Research provider returned an unreadable response.") from error


def _schema() -> dict:
    nullable_string = {"type": ["string", "null"]}
    nullable_number = {"type": ["number", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stance": {"type": "string", "enum": list(STANCES)},
            "summary": {"type": "string"},
            "supporting_points": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
            "confidence_reason": {"type": "string"},
            "time_horizon": {"type": "string"},
            "trigger_type": {"type": "string", "enum": list(TRIGGER_TYPES)},
            "trigger_price": nullable_number,
            "trigger_currency": nullable_string,
            "event_trigger": nullable_string,
            "source_target": nullable_number,
            "source_target_currency": nullable_string,
            "source_target_issuer": nullable_string,
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "publisher": nullable_string,
                        "url": {"type": "string"},
                        "published_at": nullable_string,
                        "source_type": {"type": "string", "enum": list(SOURCE_TYPES)},
                    },
                    "required": ["title", "publisher", "url", "published_at", "source_type"],
                },
            },
        },
        "required": [
            "stance", "summary", "supporting_points", "risks", "confidence",
            "confidence_reason", "time_horizon", "trigger_type", "trigger_price",
            "trigger_currency", "event_trigger", "source_target",
            "source_target_currency", "source_target_issuer", "sources",
        ],
    }


@dataclass
class OpenAIWebResearchProvider:
    api_key: str
    model: str = "gpt-5.5"
    client: JsonHttpClient | None = None

    provider_name = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def research(self, instrument: dict, focus_prompt: str = "") -> dict:
        if not self.api_key.strip():
            raise ProviderError("OpenAI API key is not configured.")
        prompt = (
            "Research this investment using current public web sources. Prefer official company "
            "filings, investor relations, exchange or regulator disclosures, then reputable financial "
            "news. Separate facts from interpretation, acknowledge conflicting evidence, and do not "
            "invent a consensus or price target. Return a balanced actionable thesis and cite every "
            "material current claim. A numeric trigger must include currency and time horizon.\n\n"
            f"Instrument: {instrument['name']}\nTicker: {instrument.get('ticker') or 'none'}\n"
            f"Asset class: {instrument['asset_class']}\nMarket/platform: {instrument['platform']}\n"
            f"Native currency: {instrument['native_currency']}\n"
            f"Local price: {instrument.get('market_price') or 'unavailable'}\n"
            f"Local price date: {instrument.get('market_price_date') or 'unavailable'}\n"
        )
        if instrument.get("current_thesis"):
            prompt += f"Current user-approved thesis for comparison: {instrument['current_thesis']}\n"
        if focus_prompt.strip():
            prompt += f"User focus: {focus_prompt.strip()}\n"
        payload = {
            "model": self.model,
            "store": False,
            "tools": [{"type": "web_search", "search_context_size": "medium"}],
            "tool_choice": "required",
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema", "name": "investment_research",
                    "strict": True, "schema": _schema(),
                }
            },
        }
        response = (self.client or JsonHttpClient()).post_json(
            self.endpoint, payload, {"Authorization": f"Bearer {self.api_key}"}
        )
        if response.get("status") not in (None, "completed"):
            raise ProviderError(f"Research response ended with status {response.get('status')}.")
        text = None
        citations: dict[str, dict] = {}
        for output in response.get("output", []):
            if output.get("type") != "message":
                continue
            for content in output.get("content", []):
                if content.get("type") == "refusal":
                    raise ProviderError("The research provider declined this request.")
                if content.get("type") == "output_text":
                    text = content.get("text")
                    for annotation in content.get("annotations", []):
                        if annotation.get("type") == "url_citation" and annotation.get("url"):
                            citations[annotation["url"]] = annotation
        if not text:
            raise ProviderError("Research provider returned no structured result.")
        try:
            result = json.loads(text)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderError("Research provider returned invalid structured data.") from error
        _validate_result(result)

        declared = {source["url"]: source for source in result["sources"] if _safe_url(source["url"])}
        if citations:
            result["sources"] = [
                {
                    **declared.get(url, {}),
                    "title": declared.get(url, {}).get("title") or citation.get("title") or url,
                    "publisher": declared.get(url, {}).get("publisher"),
                    "url": url,
                    "published_at": declared.get(url, {}).get("published_at"),
                    "source_type": declared.get(url, {}).get("source_type", "other"),
                }
                for url, citation in citations.items()
            ]
        else:
            result["sources"] = []
        return result


def _safe_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _validate_result(result: dict) -> None:
    required = {
        "stance", "summary", "supporting_points", "risks", "confidence",
        "confidence_reason", "time_horizon", "sources", "trigger_type",
    }
    if not isinstance(result, dict) or not required.issubset(result):
        raise ProviderError("Research result is missing required fields.")
    if result["stance"] not in STANCES or result["trigger_type"] not in TRIGGER_TYPES:
        raise ProviderError("Research result contains an unsupported stance or trigger.")
    if result["confidence"] not in CONFIDENCE_LEVELS:
        raise ProviderError("Research result contains an unsupported confidence level.")
    if not result["summary"].strip() or not result["risks"]:
        raise ProviderError("Research result must include a summary and risks.")
    if not isinstance(result["supporting_points"], list) or not isinstance(result["sources"], list):
        raise ProviderError("Research result contains invalid evidence or sources.")
    if result["trigger_type"] in ("at_or_below", "at_or_above"):
        if not result.get("trigger_price") or not result.get("trigger_currency") or not result.get("time_horizon"):
            raise ProviderError("Numeric research trigger is incomplete.")
