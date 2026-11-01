# src/toolpulse/llm/openai_client.py
"""OpenAI-style ``ChatClient`` — the only ToolPulse module that imports openai (D17).

Port of legacy ``sweagent/agent/algorithm/utils/llm_client.py``
(``chat_completion`` → ``OpenAIChatClient.complete``); the environment-variable
prefix changes from ``TOOL_FAMILIAR_LLM_`` to ``TOOLPULSE_LLM_`` (D11), keeping
the ``OPENAI_API_KEY``/``OPENAI_BASE_URL`` fallbacks.
"""
from __future__ import annotations

import os

from openai import OpenAI

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIChatClient:
    def complete(self, prompt: str, *, system: str | None = None,
                 timeout: float | None = None) -> str:
        """Call an OpenAI-style chat completions endpoint and return the message text.

        Configuration is read from environment variables. Raises ``RuntimeError`` when
        required config is missing or the response is empty; propagates SDK errors otherwise.
        """
        api_key = os.environ.get("TOOLPULSE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("TOOLPULSE_LLM_API_KEY (or OPENAI_API_KEY) is not set")
        base_url = (
            os.environ.get("TOOLPULSE_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or _DEFAULT_BASE_URL
        )
        model = os.environ.get("TOOLPULSE_LLM_MODEL")
        if not model:
            raise RuntimeError("TOOLPULSE_LLM_MODEL is not set")
        if timeout is None:
            timeout = float(os.environ.get("TOOLPULSE_LLM_TIMEOUT", "30"))

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, object] = {"model": model, "messages": messages, "timeout": timeout}
        max_tokens = os.environ.get("TOOLPULSE_LLM_MAX_TOKENS")
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)
        temperature = os.environ.get("TOOLPULSE_LLM_TEMPERATURE")
        if temperature:
            kwargs["temperature"] = float(temperature)

        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty response")
        return content
