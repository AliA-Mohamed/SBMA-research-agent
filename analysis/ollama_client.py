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


def call_llm(
    prompt: str,
    mode: str = "extraction",
    json_mode: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Unified LLM call that routes to Ollama, Gemini, or Claude based on config.

    Args:
        prompt: The prompt to send.
        mode: "extraction" (uses Sonnet/fast model) or "synthesis" (uses Opus/powerful model).
        json_mode: If True, request JSON-formatted output.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.

    Returns:
        Raw response text from the model.
    """
    backend = config.LLM_BACKEND

    if backend == "ollama":
        model = config.OLLAMA_EXTRACTION_MODEL if mode == "extraction" else config.OLLAMA_SYNTHESIS_MODEL
        client = OllamaClient(model=model)
        return client.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
        )

    elif backend == "gemini":
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        model = config.GEMINI_EXTRACTION_MODEL if mode == "extraction" else config.GEMINI_SYNTHESIS_MODEL
        gen_config = {"max_output_tokens": max_tokens}
        if json_mode:
            gen_config["response_mime_type"] = "application/json"
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=gen_config,
        )
        return response.text

    elif backend == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        model = config.CLAUDE_EXTRACTION_MODEL if mode == "extraction" else config.CLAUDE_SYNTHESIS_MODEL
        system_msg = "You are an expert SBMA researcher. "
        if json_mode:
            system_msg += "Respond with valid JSON only, no markdown formatting."
        # Use streaming for large requests to avoid SDK timeout
        if max_tokens > 16384:
            collected = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    collected.append(text)
            return "".join(collected)
        else:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text

    else:
        raise ValueError(f"Unknown LLM_BACKEND: {backend}")


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
