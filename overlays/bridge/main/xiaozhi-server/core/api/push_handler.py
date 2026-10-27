"""Loopback agent events -> durable queue -> enrolled devices' idle-only LAN audio players."""
import asyncio
import ipaddress
import json
import re
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web, ClientSession, ClientTimeout
from core.utils.push_store import PushStore, DEVICE_AGENTS
from core.utils.device_registry import DEVICE_LABELS, configure_devices
from config.logger import setup_logging

_peers = {}

def record_push_peer(device_id, peer):
    device_id = str(device_id).lower()
    if device_id not in DEVICE_AGENTS:return
    try:
        address=ipaddress.ip_address(peer)
        if address.version==4 and address.is_private and not address.is_loopback:_peers[device_id]=str(address)
    except ValueError:pass

class PushService:
    def __init__(self,config):
        self.config=config
        self.logger=setup_logging()
        llm=config['LLM'][config['selected_module']['LLM']]
        configure_devices(llm['device_map'])
        self.store=PushStore(Path(llm['device_map']).with_name('push-state.sqlite'))
        self.store.recover()
        state_path=Path(llm['device_map']).with_name('conversation-state.json')
        if state_path.exists():
            devices=json.loads(state_path.read_text()).get('devices',{})
            for device,agent in DEVICE_AGENTS.items():
                entry=devices.get(device+'|'+agent)
                if entry and isinstance(entry.get('conversation_id'),str):
                    self.store.allow_existing(entry['conversation_id'],device)
        self.media=self.store.path.with_name('push-audio');self.media.mkdir(mode=0o700,exist_ok=True)
        self.task=None
    async def events(self,request):
        if not ipaddress.ip_address(request.remote).is_loopback:raise web.HTTPForbidden()
        if request.content_length is None or request.content_length>16000:raise web.HTTPRequestEntityTooLarge(max_size=16000,actual_size=request.content_length or 0)
        try:data=await request.json()
        except Exception:raise web.HTTPBadRequest()
        session,run,text=(data.get(k) for k in ['session','run','text'])
        if not all(isinstance(v,str) and v for v in [session,run,text]) or len(run)>200 or len(text.encode())>6000:raise web.HTTPBadRequest()
        if not any(session.startswith('agent:'+agent+':openai-user:') for agent in DEVICE_AGENTS.values()):raise web.HTTPForbidden()
        token=self.store.enqueue(session,run,text)
        if token is None:raise web.HTTPForbidden(text='Not an enrolled hardware voice task')
        return web.json_response({'id':token,'queued':True})
    async def audio(self,request):
        token=request.match_info['token']
        if request.remote!=_peers.get(self.store.owner(token)):raise web.HTTPForbidden()
        if not re.fullmatch('[0-9a-f]{64}',token):raise web.HTTPNotFound()
        p=self.media/(token+'.ogg')
        if not p.is_file():raise web.HTTPNotFound()
        return web.FileResponse(p,headers={'Cache-Control':'no-store'})
    async def start(self,app):self.task=asyncio.create_task(self.worker())
    async def stop(self,app):
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
    async def synthesize(self,token,text):
        from core.providers.tts.edge import TTSProvider
        from core.utils.device_tts import device_tts_config
        config = device_tts_config(self.config, device_id=self.store.owner(token))
        selected=config['selected_module']['TTS']
        tts=TTSProvider(config['TTS'][selected],True)
        mp3=self.media/(token+'.mp3');ogg=self.media/(token+'.ogg');tmp=self.media/(token+'.tmp.ogg')
        if ogg.exists():return
        await tts.text_to_speak(text,str(mp3))
        process=await asyncio.create_subprocess_exec(os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg') or 'ffmpeg','-v','error','-y','-i',str(mp3),'-ac','1','-ar','24000','-c:a','libopus','-frame_duration','60',str(tmp),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        _,error=await process.communicate()
        if process.returncode:raise RuntimeError('Notification audio conversion failed')
        tmp.chmod(0o600);tmp.replace(ogg);mp3.unlink(missing_ok=True)
    async def worker(self):
        async with ClientSession(timeout=ClientTimeout(total=5),trust_env=False) as client:
            while True:
                for device,agent in DEVICE_AGENTS.items():
                    try:
                        peer=_peers.get(device)
                        entry=self.store.next(device) if peer else None
                        if not entry:continue
                        token,text,state=entry
                        if state=='pending':await self.synthesize(token,text)
                        host=urlsplit(self.config['server']['websocket']).hostname
                        payload={'id':token,'text':text,'audio_url':f'http://{host}:8003/xiaozhi/push/audio/{token}.ogg'}
                        async with client.post(f'http://{peer}:8021/notify',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},allow_redirects=False) as response:
                            data=await response.json()
                        if data.get('device')!=DEVICE_LABELS.get(device):raise RuntimeError('Wrong notification device')
                        if data.get('id')==token:
                            result=data.get('state')
                            if result in ['done','failed','interrupted']:self.store.set_state(token,result)
                            elif result in ['queued','playing']:self.store.set_state(token,'accepted')
                    except asyncio.CancelledError:raise
                    except Exception as exc:
                        self.logger.debug(agent+' notification pending: '+type(exc).__name__)
                import time
                for p in self.media.glob('*'):
                    if p.stat().st_mtime<time.time()-86400:p.unlink(missing_ok=True)
                await asyncio.sleep(2)
