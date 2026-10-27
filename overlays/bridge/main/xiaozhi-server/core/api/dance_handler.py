"""Local OpenClaw -> bridge -> Operator firmware preset control, including idle devices."""
import asyncio
import ipaddress
import time
from aiohttp import web, ClientSession, ClientTimeout, ClientError

from core.utils import device_registry as registry
_peer = None
_seen = 0.0


def record_operator_peer(device_id, peer):
    global _peer, _seen
    if str(device_id).lower() != registry.DANCE_DEVICE or not peer:
        return
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return
    if address.version == 4 and address.is_private and not address.is_loopback:
        _peer, _seen = str(address), time.monotonic()


async def handle_dance(request):
    try:
        local = ipaddress.ip_address(request.remote).is_loopback
    except (ValueError, TypeError):
        local = False
    if not local:
        return web.json_response({"error": "local_openclaw_only"}, status=403)
    action = request.match_info["action"]
    if action not in {"start", "stop", "status"}:
        return web.json_response({"error": "unknown_action"}, status=404)
    if _peer is None or time.monotonic() - _seen > 86400:
        return web.json_response({"error": "Operator has not registered its current address; restart device"}, status=503)
    # Do not queue stop behind start: both are short firmware commands, never whole dances.
    try:
        async with ClientSession(timeout=ClientTimeout(total=4), trust_env=False) as client:
            async with client.post(f"http://{_peer}:8020/dance/{action}", allow_redirects=False) as response:
                data = await response.json()
                if data.get("device") != registry.DEVICE_LABELS.get(registry.DANCE_DEVICE):
                    return web.json_response({"error": "unexpected_device"}, status=502)
                return web.json_response(data, status=response.status)
    except (ClientError, asyncio.TimeoutError, ValueError) as exc:
        return web.json_response({"error": "Operator motion endpoint unavailable", "kind": type(exc).__name__}, status=503)
