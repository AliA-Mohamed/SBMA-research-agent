"""Unified Ollama wrapper for LLM calls via the local HTTP API."""

import sys
import json
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("ollama_client")


class OllamaClient:
    """Calls Ollama's HTTP API (POST /api/generate) with JSON mode and retry logic."""

    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN, max=config.RETRY_WAIT_MAX),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def generate(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        json_mode: bool = True,
    ) -> str:
        """Send a prompt to Ollama and return the response text.

        Args:
            prompt: The prompt to send.
            model: Override the default model for this call.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.
            json_mode: If True, request JSON-formatted output.

        Returns:
            The raw response text from the model.
        """
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if json_mode:
            payload["format"] = "json"

        url = f"{self.base_url}/api/generate"
        logger.debug(f"Ollama request to {url} with model={payload['model']}")

        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()

        data = resp.json()
        text = data.get("response", "")
        logger.debug(f"Ollama response: {len(text)} chars")
        return text

    def generate_json(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Optional[dict]:
        """Send a prompt and parse the response as JSON.

        Returns:
            Parsed JSON dict, or None on failure.
        """
        text = self.generate(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
        )
        return parse_json_response(text)


def parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from an LLM response, handling markdown code blocks and other wrapping."""
    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract from ```json ... ```
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    # Extract from ``` ... ```
    if "```" in text:
        try:
            start = text.index("```") + 3
            newline = text.index("\n", start)
            start = newline + 1
            end = text.index("```", start)
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    # Find first JSON object by braces
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None
