"""OpenAI API adapter used when API mode is enabled."""

from __future__ import annotations

import os


class GPTAPIAdapter:
    def __init__(self, config: dict, logger):
        self.cfg = config.get("api_adapter", {})
        self.logger = logger

    async def query(self, prompt: str) -> str:
        try:
            from openai import AsyncOpenAI
        except Exception as exc:
            raise RuntimeError(
                "openai package is required for api mode. Install requirements and retry."
            ) from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set while using api adapter.")

        base_url = os.getenv("OPENAI_API_BASE") or None
        org = os.getenv("OPENAI_ORG_ID")
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if org:
            kwargs["organization"] = org

        client = AsyncOpenAI(**kwargs)
        response = await client.chat.completions.create(
            model=self.cfg.get("model", "gpt-5.5-pro"),
            messages=[{"role": "user", "content": prompt}],
            temperature=float(self.cfg.get("temperature", 0.2)),
            max_tokens=int(self.cfg.get("max_tokens", 2048)),
            timeout=float(self.cfg.get("response_wait_seconds", 60)),
        )
        client = None  # free socket references earlier if object cleanup not immediate
        if not response.choices:
            raise RuntimeError("No response choices returned from API mode.")
        return response.choices[0].message.content.strip() if response.choices[0].message else ""
