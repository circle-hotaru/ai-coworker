"""Apply a board's optional EdgeTTS voice without changing shared settings."""
import copy
from pathlib import Path
from ruamel.yaml import YAML


def device_tts_config(config, device_id=None, route=None):
    if route is None and device_id:
        llm = config['LLM'][config['selected_module']['LLM']]
        path = llm.get('device_map')
        if path:
            with Path(path).open() as stream:
                routes = YAML(typ='safe').load(stream)['devices']
            route = next((v for k, v in routes.items()
                          if str(k).strip().lower() == str(device_id).strip().lower()), None)
    voice = (route or {}).get('tts_voice')
    if not isinstance(voice, str) or not voice.strip():
        return config
    selected = config['selected_module']['TTS']
    settings = config['TTS'][selected]
    if settings.get('type', selected).lower() != 'edge':
        raise ValueError('Per-device tts_voice requires EdgeTTS')
    result = copy.deepcopy(config)
    settings = result['TTS'][selected]
    settings['voice'] = voice.strip()
    settings['private_voice'] = voice.strip()
    return result
