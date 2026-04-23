"""
RealEstork — AI Gateway
Module 5 (M5) — 4-tier LLM integration
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import yaml
from loguru import logger


class AIGateway:
    """
    Handles communication with LLM APIs (Ollama, Zero-token, Anthropic).
    Automatically reads config/ai.yaml to determine which provider to use.
    """

    def __init__(self, config_path: str = "config/ai.yaml") -> None:
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        with open(config_path, encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}

        config = full_config.get("ai", {})
        self.provider = config.get("provider", "ollama")
        
        # Base settings
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 300)
        self.timeout = config.get("timeout_seconds", 30)
        self.fallback = config.get("fallback_to_rules_on_error", True)
        self.prompt_template = config.get("classification_prompt", "")

        # Provider specifics
        if self.provider == "ollama":
            self.p_config = config.get("ollama", {})
            self.model = self.p_config.get("model", "gemma4:e4b")
            self.base_url = self.p_config.get("base_url", "http://localhost:11434")
        elif self.provider == "zero-token":
            self.p_config = config.get("zero_token", {})
            self.model = self.p_config.get("model", "deepseek-web/deepseek-chat")
            self.base_url = self.p_config.get("base_url", "http://localhost:3001/v1")
            self.api_key = self.p_config.get("api_key", "dummy")
        elif self.provider in ("anthropic", "openai"):
            self.p_config = config.get(self.provider, {})
            self.model = self.p_config.get("model", "")
            self.api_key = os.environ.get(self.p_config.get("api_key_env", ""), "")
        else:
            logger.warning(f"[ai] Unknown provider '{self.provider}'")

        logger.info(f"[ai] Gateway initialized: {self.provider} ({self.model})")

    async def analyze_listing(self, listing: Any) -> dict[str, Any] | None:
        """
        Analyze listing text using configured LLM.
        Returns dict matching JSON schema requirements.
        """
        prompt = self.prompt_template.format(
            title=listing.title or "",
            description=listing.description or "",
            phone=listing.phone or "",
            photo_count=len(listing.images),
            floor_level=listing.floor_level or "Unknown",
            listing_age_hours=listing.listing_age_hours or "Unknown",
            source=listing.source,
        )

        try:
            if self.provider == "ollama":
                return await self._call_ollama(prompt)
            elif self.provider == "zero-token":
                return await self._call_openai_compatible(prompt, is_zero_token=True)
            elif self.provider in ("anthropic", "openai"):
                return await self._call_openai_compatible(prompt)
            else:
                return None
        except Exception as e:
            logger.error(f"[ai] {self.provider} call failed: {e}")
            if self.fallback:
                return None
            raise

    async def _call_ollama(self, prompt: str) -> dict[str, Any] | None:
        """Call local Ollama /api/generate endpoint."""
        url = f"{self.base_url.rstrip('/')}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
            "format": "json"  # Ensure JSON output
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = data.get("response", "")
        return self._parse_json_response(text)

    async def _call_openai_compatible(self, prompt: str, is_zero_token: bool = False) -> dict[str, Any] | None:
        """Call OpenAI-compatible format (used by Openclaw, OpenAI, etc)."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        if not is_zero_token:
             payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"[ai] API Error {resp.status_code}: {resp.text}")
                return None
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        return self._parse_json_response(text)

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        """Extract JSON from LLM string output."""
        # Find JSON block in code fences if present
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw_json = match.group(1) if match else text

        try:
            # Clean up before parsing
            raw_json = raw_json.strip()
            # If not started/ended properly, try naive fix
            start_idx = raw_json.find('{')
            end_idx = raw_json.rfind('}')
            if start_idx != -1 and end_idx != -1:
                raw_json = raw_json[start_idx:end_idx+1]
                
            parsed = json.loads(raw_json)
            
            # Validate format visually (keys present)
            if "is_owner_probability" in parsed:
                return parsed
            else:
                logger.warning(f"[ai] Missing required key in JSON: {parsed}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"[ai] Failed to parse JSON from LLM. Output: {text[:100]}... Error: {e}")
            return None
