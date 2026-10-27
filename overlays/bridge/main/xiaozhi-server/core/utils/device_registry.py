"""Explicit hardware enrollment shared by routing, notifications and motion."""
import re
from pathlib import Path
from ruamel.yaml import YAML

DEVICE_AGENTS = {}
DEVICE_LABELS = {}
DANCE_DEVICE = None

def configure_devices(path):
    global DANCE_DEVICE
    mapping = YAML(typ='safe').load(Path(path).read_text())
    routes = mapping.get('devices') if isinstance(mapping, dict) else None
    if not isinstance(routes, dict):
        raise ValueError('devices must be a mapping')
    agents, labels, dance = {}, {}, None
    for raw_device, route in routes.items():
        device = str(raw_device).strip().lower()
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', device):
            raise ValueError('Invalid device MAC')
        if not isinstance(route, dict):
            raise ValueError('Invalid device route')
        agent = route.get('agent_id')
        if not isinstance(agent, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', agent):
            raise ValueError('Invalid agent_id')
        for flag in ('push_enabled', 'dance_enabled'):
            if flag in route and not isinstance(route[flag], bool):
                raise ValueError(flag + ' must be a boolean')
        if route.get('push_enabled') or route.get('dance_enabled'):
            label = route.get('firmware_label')
            if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,47}', label):
                raise ValueError('Enabled hardware requires firmware_label')
            labels[device] = label
        if route.get('push_enabled'):
            agents[device] = agent
        if route.get('dance_enabled'):
            if dance is not None:
                raise ValueError('Only one motion device can be enabled')
            dance = device
    # Only publish validated settings; preserve dict identity for importing modules.
    DEVICE_AGENTS.clear(); DEVICE_AGENTS.update(agents)
    DEVICE_LABELS.clear(); DEVICE_LABELS.update(labels)
    DANCE_DEVICE = dance
