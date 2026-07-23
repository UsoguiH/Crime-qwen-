"""The single Qwen3-VL client. Every analytic call goes through complete_json():
prompt files → messages (text first, then images as base64 data URLs) →
provider-adapted request → tenacity retries → JSON parse → Pydantic validation
→ (on failure) repair re-ask → ModelCall row logged with tokens/latency/cost.
"""
import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from openai import (APIConnectionError, APIStatusError, APITimeoutError,
                    AsyncOpenAI, InternalServerError, RateLimitError)
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_random_exponential)

from app.config import Settings
from app.db.models import ModelCall
from app.modelclient import budget, mock, presets
from app.services.hashing import sha256_text

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# forensic determinism: grounding/classification runs cold, prose slightly warmer
TEMPERATURE_BY_PURPOSE = {
    "triage": 0.1, "detect": 0.1, "aggregate": 0.1,
    "compare": 0.2, "narrative": 0.4, "refine": 0.0, "qa": 0.0,
}


class ModelJSONError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


@dataclass
class FrameImage:
    data: bytes
    ref: str            # frame id / filename — cross-referenced inside prompts
    name_hint: str = "" # media filename stem — mock fixture + recorder key
    mime: str = "image/jpeg"


@dataclass
class CallResult:
    value: BaseModel
    model_call_id: str
    status: str = "ok"
    raw_text: str = ""
    usage: dict = field(default_factory=dict)


@lru_cache(maxsize=64)
def load_prompt(prompts_dir: str, files: tuple[str, ...]) -> tuple[str, str]:
    """Concatenate prompt files (00_common_rules first — except 9x standalone
    prompts, whose technical tasks the forensic persona would contaminate)."""
    names = files if files and files[0].startswith("9") \
        else ("00_common_rules.md", *files)
    parts = []
    for name in names:
        path = Path(prompts_dir) / name
        parts.append(path.read_text(encoding="utf-8").strip())
    text = "\n\n---\n\n".join(dict.fromkeys(parts))  # dedupe identical blocks, keep order
    return text, sha256_text(text)


def prompt_hashes(settings: Settings) -> dict[str, str]:
    out = {}
    for path in sorted(settings.prompts_dir.glob("*.md")):
        out[path.name] = sha256_text(path.read_text(encoding="utf-8"))
    return out


class VLMClient:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker):
        self.settings = settings
        self.factory = session_factory
        self.semaphore = asyncio.Semaphore(settings.model_max_concurrency)
        self.run_counts: dict[str, int] = {}
        self._client: AsyncOpenAI | None = None

    # ── public API ────────────────────────────────────────────────────────
    async def complete_json(
        self,
        *,
        prompt_files: tuple[str, ...],
        schema: type[BaseModel],
        purpose: str,
        thinking: bool = False,
        images: list[FrameImage] | None = None,
        context: dict | None = None,
        run_id: str | None = None,
        stage: int | None = None,
        frame_id: str | None = None,
        media_file_id: str | None = None,
        max_output_tokens: int = 4096,
        temperature: float | None = None,
        enforce_schema: bool = True,
    ) -> CallResult:
        images = images or []
        self._check_budget(run_id)
        prompt_text, prompt_sha = load_prompt(str(self.settings.prompts_dir), prompt_files)
        started = time.monotonic()

        if self.settings.model_mode == "mock":
            value = mock.resolve(self.settings.fixtures_dir, purpose,
                                 [im.name_hint for im in images], context, schema)
            call_id = await self._log(
                run_id=run_id, stage=stage, purpose=purpose, provider="mock",
                model_name="mock", thinking=thinking, prompt_files=prompt_files,
                prompt_sha=prompt_sha, frame_id=frame_id, media_file_id=media_file_id,
                usage={}, latency_ms=int((time.monotonic() - started) * 1000),
                attempts=1, status="ok", error=None,
            )
            self._bump(run_id)
            return CallResult(value=value, model_call_id=call_id)

        model_name = presets.pick_model(self.settings, thinking)
        response_format, extra_body = presets.build_request_extras(
            self.settings, thinking=thinking, schema=schema,
            schema_name=schema.__name__, enforce_schema=enforce_schema)
        messages = self._build_messages(prompt_text, context, images)

        attempts = 0
        status = "ok"
        raw_text = ""
        usage: dict = {}
        error_text: str | None = None
        value: BaseModel | None = None
        resolved_temp = (temperature if temperature is not None
                         else TEMPERATURE_BY_PURPOSE.get(purpose, 0.2))
        try:
            async with self.semaphore:
                raw_text, usage = await self._call_api(
                    model_name, messages, response_format, extra_body,
                    max_output_tokens, resolved_temp)
            attempts = 1
            try:
                value = self._parse(raw_text, schema)
            except (json.JSONDecodeError, ValidationError) as first_err:
                # repair loop: up to 2 focused re-asks with the validator error
                for _ in range(2):
                    attempts += 1
                    raw_text, extra_usage = await self._repair(
                        model_name, raw_text, first_err, schema, extra_body)
                    usage = _merge_usage(usage, extra_usage)
                    try:
                        value = self._parse(raw_text, schema)
                        status = "repaired"
                        break
                    except (json.JSONDecodeError, ValidationError) as err:
                        first_err = err
                if value is None:
                    raise ModelJSONError(
                        f"{purpose}: model output failed schema after repairs: {first_err}")
        except ModelJSONError as exc:
            status, error_text = "failed", str(exc)[:2000]
            raise
        except Exception as exc:
            status, error_text = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            call_id = await self._log(
                run_id=run_id, stage=stage, purpose=purpose,
                provider=self._provider_label(), model_name=model_name,
                thinking=thinking, prompt_files=prompt_files, prompt_sha=prompt_sha,
                frame_id=frame_id, media_file_id=media_file_id, usage=usage,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=max(attempts, 1), status=status, error=error_text,
            )
            self._bump(run_id)

        if self.settings.record_fixtures and images and images[0].name_hint:
            try:
                mock.record(self.settings.fixtures_dir, purpose,
                            images[0].name_hint, value.model_dump())
            except OSError:
                pass
        return CallResult(value=value, model_call_id=call_id, status=status,
                          raw_text=raw_text, usage=usage)

    async def health(self) -> dict:
        if self.settings.model_mode == "mock":
            return {"ok": True, "mode": "mock", "model": "mock"}
        try:
            client = self._get_client()
            models = await asyncio.wait_for(client.models.list(), timeout=15)
            return {"ok": True, "mode": self.settings.model_mode,
                    "model": presets.pick_model(self.settings, False),
                    "available": len(models.data or [])}
        except Exception as exc:
            return {"ok": False, "mode": self.settings.model_mode,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}

    def set_run_count(self, run_id: str, count: int) -> None:
        self.run_counts[run_id] = count

    # ── internals ─────────────────────────────────────────────────────────
    def _check_budget(self, run_id: str | None) -> None:
        if run_id and self.run_counts.get(run_id, 0) >= self.settings.model_max_calls_per_run:
            raise BudgetExceeded(
                f"run {run_id} reached MODEL_MAX_CALLS_PER_RUN="
                f"{self.settings.model_max_calls_per_run}")

    def _bump(self, run_id: str | None) -> None:
        if run_id:
            self.run_counts[run_id] = self.run_counts.get(run_id, 0) + 1

    def _provider_label(self) -> str:
        return "vllm" if self.settings.model_mode == "local" else self.settings.model_provider

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key or "not-needed",
                base_url=self.settings.resolved_base_url,
                timeout=self.settings.model_timeout_s,
                max_retries=0,  # tenacity owns retries
                default_headers={"X-Title": "Athar Crime Scene Analysis"},
            )
        return self._client

    def _build_messages(self, prompt_text: str, context: dict | None,
                        images: list[FrameImage]) -> list[dict]:
        user_content: list[dict] = []
        if context:
            ctx = json.dumps(context, ensure_ascii=False, indent=1)
            user_content.append({"type": "text",
                                 "text": f"بيانات المهمة (JSON):\n{ctx}"})
        else:
            user_content.append({"type": "text", "text": "نفّذ المهمة وفق التعليمات."})
        for im in images:
            b64 = base64.b64encode(im.data).decode("ascii")
            user_content.append({"type": "text", "text": f"الصورة التالية مرجعها: {im.ref}"})
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{im.mime};base64,{b64}"},
            })
        return [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": user_content},
        ]

    @retry(
        retry=retry_if_exception_type((APITimeoutError, APIConnectionError,
                                       RateLimitError, InternalServerError)),
        wait=wait_random_exponential(min=1, max=32),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _call_api(self, model_name: str, messages: list[dict],
                        response_format: dict | None, extra_body: dict,
                        max_output_tokens: int,
                        temperature: float = 0.2) -> tuple[str, dict]:
        client = self._get_client()
        kwargs: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "extra_body": extra_body or None,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        # DashScope JSON mode documents that max_tokens must stay unset
        if not (self.settings.model_provider == "dashscope"
                and response_format == {"type": "json_object"}):
            kwargs["max_tokens"] = max_output_tokens
        try:
            # hard wall-clock deadline: the SDK read-timeout does not bound a
            # provider that trickles bytes — one call once ran 17.8 minutes.
            # Cancel and let tenacity retry (rerouted, usually to a fast replica).
            resp = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=self.settings.model_timeout_s)
        except asyncio.TimeoutError as exc:
            import httpx
            raise APITimeoutError(
                request=httpx.Request("POST", "chat/completions")) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise InternalServerError(exc.message, response=exc.response,
                                          body=exc.body) from exc
            raise
        choice = resp.choices[0]
        text = choice.message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.prompt_tokens or 0,
                "output_tokens": resp.usage.completion_tokens or 0,
            }
            details = getattr(resp.usage, "completion_tokens_details", None)
            if details is not None:
                usage["reasoning_tokens"] = getattr(details, "reasoning_tokens", None)
        # which backend actually served this call (OpenRouter routing varies!)
        served = getattr(resp, "provider", None) \
            or (getattr(resp, "model_extra", None) or {}).get("provider")
        if served:
            usage["served_by"] = served
        return text, usage

    async def _repair(self, model_name: str, raw_text: str, error: Exception,
                      schema: type[BaseModel], extra_body: dict) -> tuple[str, dict]:
        repair_prompt, _ = load_prompt(str(self.settings.prompts_dir), ("60_repair.md",))
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content":
                f"المخطط المطلوب (JSON Schema):\n{schema_json}\n\n"
                f"خطأ التحقق:\n{str(error)[:1500]}\n\n"
                f"النص المطلوب إصلاحه:\n{raw_text[:8000]}"},
        ]
        async with self.semaphore:
            return await self._call_api(model_name, messages, None, extra_body,
                                        4096, temperature=0.0)

    @staticmethod
    def _parse(text: str, schema: type[BaseModel]) -> BaseModel:
        candidate = text.strip()
        match = FENCE_RE.search(candidate)
        if match:
            candidate = match.group(1).strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start > 0 and end > start:
            candidate = candidate[start:end + 1]
        data = json.loads(candidate)
        return schema.model_validate(data)

    async def _log(self, *, run_id, stage, purpose, provider, model_name, thinking,
                   prompt_files, prompt_sha, frame_id, media_file_id, usage,
                   latency_ms, attempts, status, error) -> str:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if usage.get("served_by"):
            provider = f"{provider}:{usage['served_by']}"
        row = ModelCall(
            run_id=run_id, stage=stage, purpose=purpose, provider=provider,
            model_name=model_name, thinking=thinking,
            prompt_file="+".join(prompt_files), prompt_sha256=prompt_sha,
            frame_id=frame_id, media_file_id=media_file_id,
            input_tokens=input_tokens, output_tokens=output_tokens,
            reasoning_tokens=usage.get("reasoning_tokens"),
            latency_ms=latency_ms,
            cost_usd_estimate=budget.estimate_cost(model_name, input_tokens, output_tokens),
            attempts=attempts, status=status, error=error,
        )
        async with self.factory() as session:
            session.add(row)
            await session.commit()
        return row.id


def _merge_usage(a: dict, b: dict) -> dict:
    out = dict(a)
    for key in ("input_tokens", "output_tokens"):
        out[key] = (a.get(key) or 0) + (b.get(key) or 0)
    if b.get("reasoning_tokens"):
        out["reasoning_tokens"] = (a.get("reasoning_tokens") or 0) + b["reasoning_tokens"]
    return out
