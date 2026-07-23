"""Per-provider request adaptation: model choice, thinking toggles, JSON enforcement."""
from app.config import Settings
from app.schemas.model_io import strict_response_format


def pick_model(settings: Settings, thinking: bool) -> str:
    if settings.model_mode == "local":
        return settings.vllm_model
    return settings.model_name_thinking if thinking else settings.model_name_fast


def build_request_extras(settings: Settings, *, thinking: bool,
                         schema, schema_name: str,
                         enforce_schema: bool = True) -> tuple[dict | None, dict]:
    """Returns (response_format, extra_body) for the current provider.

    - OpenRouter / vLLM: strict json_schema; OpenRouter additionally gets privacy
      routing (data_collection deny / zdr) and require_parameters so only
      schema-capable providers serve the request.
    - DashScope: only json_object mode, and NOT while thinking (documented VL
      limitation) — those calls rely on prompt + validate + repair.
    """
    extra_body: dict = {}
    response_format: dict | None = None

    if settings.model_mode == "local":
        if enforce_schema:
            response_format = strict_response_format(schema, schema_name)
    elif settings.model_provider == "dashscope":
        extra_body["enable_thinking"] = thinking
        if not thinking and enforce_schema:
            response_format = {"type": "json_object"}
    else:  # openrouter or custom OpenAI-compatible
        if enforce_schema:
            response_format = strict_response_format(schema, schema_name)
        if settings.model_provider == "openrouter":
            provider: dict = {
                "data_collection": settings.openrouter_data_collection,
            }
            if response_format is not None:
                provider["require_parameters"] = True
            if settings.openrouter_zdr:
                provider["zdr"] = True
            order = [p.strip() for p in settings.openrouter_provider_order.split(",") if p.strip()]
            if order:
                provider["order"] = order
                # eval pins strictly (ALLOW_FALLBACKS=false); production keeps
                # fallbacks so an Alibaba outage degrades instead of failing
                provider["allow_fallbacks"] = settings.openrouter_allow_fallbacks
            extra_body["provider"] = provider

    return response_format, extra_body
