"""Resolve ASR configuration without changing the requested provider."""

XUNFEI_CREDENTIALS = ("app_id", "api_key", "api_secret")


def resolve_asr(config):
    """Use the existing local model when Xunfei credentials are incomplete.

    Return (effective name, provider type, settings, missing credential names).
    This is configuration fallback only; cloud authentication/network failures
    must remain visible rather than silently submitting the utterance elsewhere.
    """
    name = config["selected_module"]["ASR"]
    settings = config["ASR"][name]
    provider_type = settings.get("type", name)
    missing = ()
    if provider_type == "xunfei_stream":
        missing = tuple(
            key for key in XUNFEI_CREDENTIALS
            if not isinstance(settings.get(key), str)
            or not settings[key].strip()
            or settings[key].strip().startswith("你的")
        )
        if missing:
            name = "FunASR"
            settings = config["ASR"].get(name)
            if not settings or settings.get("type", "fun_local") != "fun_local":
                raise ValueError("讯飞凭据不完整，且未配置本地 FunASR (type: fun_local)")
            provider_type = "fun_local"
    return name, provider_type, settings, missing
