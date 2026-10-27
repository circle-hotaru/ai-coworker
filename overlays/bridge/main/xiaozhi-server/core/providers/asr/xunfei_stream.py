import json
import hmac
import base64
import hashlib
import asyncio
import websockets
import gc
from time import mktime
from datetime import datetime
from urllib.parse import urlencode
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from config.logger import setup_logging
from wsgiref.handlers import format_date_time
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()

# 帧状态常量
STATUS_FIRST_FRAME = 0  # 第一帧的标识
STATUS_CONTINUE_FRAME = 1  # 中间帧标识
STATUS_LAST_FRAME = 2  # 最后一帧的标识


class ASRProvider(ASRProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__()
        self.interface_type = InterfaceType.STREAM
        self.config = config
        self.text = ""
        self.asr_ws = None
        self.forward_task = None
        self.is_processing = False
        self.server_ready = False
        self._segments = {}
        self._last_frame_sent = False
        self._finalizing = False
        self._frame_seq = 0

        # 讯飞配置
        self.app_id = config.get("app_id")
        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")

        if not all(isinstance(value, str) and value.strip() and not value.startswith("你的")
                   for value in (self.app_id, self.api_key, self.api_secret)):
            raise ValueError("必须提供app_id、api_key和api_secret")

        # 识别参数
        self.iat_params = {
            "domain": config.get("domain", "slm"),
            "language": config.get("language", "zh_cn"),
            "accent": config.get("accent", "mandarin"),
            "result": {"encoding": "utf8", "compress": "raw", "format": "plain"},
        }

        for key in ("eos", "dwa", "ltc"):
            if key in config:
                self.iat_params[key] = config[key]
        if config.get("domain") == "spark_asr_v2":
            self.iat_params["result"]["format"] = "json"
        if config.get("context"):
            context = config["context"]
            if not isinstance(context, str):
                context = json.dumps(context, ensure_ascii=False)
            if len(context.encode("utf-8")) > 2048:
                raise ValueError("讯飞上下文不能超过2KB")
            self.iat_params["context"] = context
        self.output_dir = config.get("output_dir", "tmp/")
        self.delete_audio_file = delete_audio_file

    def create_url(self) -> str:
        """生成认证URL"""
        url = "wss://iat.cn-huabei-1.xf-yun.com/v1"
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "iat.cn-huabei-1.xf-yun.com" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v1 " + "HTTP/1.1"

        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding="utf-8")

        authorization_origin = (
            'api_key="%s", algorithm="%s", headers="%s", signature="%s"'
            % (self.api_key, "hmac-sha256", "host date request-line", signature_sha)
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode(
            encoding="utf-8"
        )

        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "iat.cn-huabei-1.xf-yun.com",
        }

        # 拼接鉴权参数，生成url
        url = url + "?" + urlencode(v)
        return url

    async def open_audio_channels(self, conn: "ConnectionHandler"):
        await super().open_audio_channels(conn)

    async def receive_audio(self, conn: "ConnectionHandler", pcm_frame, audio_have_voice):
        if self._last_frame_sent or self._finalizing:
            return
        started = False
        # 先调用父类方法处理基础逻辑
        await super().receive_audio(conn, pcm_frame, audio_have_voice)

        # 如果本次有声音，且之前没有建立连接
        if audio_have_voice and self.asr_ws is None and not self.is_processing:
            try:
                await self._start_recognition(conn)
                started = True
            except Exception as e:
                logger.bind(tag=TAG).error(f"建立ASR连接失败: {str(e)}")
                await self._cleanup()
                return

        # 发送当前音频数据
        if not started and self.asr_ws and self.is_processing and self.server_ready:
            try:
                await self._send_audio_frame(pcm_frame, STATUS_CONTINUE_FRAME)
            except Exception as e:
                logger.bind(tag=TAG).warning(f"发送音频数据时发生错误: {e}")
                await self._cleanup()

        if conn.client_voice_stop:
            await self._send_stop_request()

    async def _start_recognition(self, conn: "ConnectionHandler"):
        """开始识别会话"""
        try:
            self.is_processing = True
            self.text = ""
            self._segments = {}
            self._last_frame_sent = False
            self._finalizing = False
            self._frame_seq = 0
            # 建立WebSocket连接
            ws_url = self.create_url()
            logger.bind(tag=TAG).info("正在连接讯飞ASR服务（WSS）")

            # 如果为手动模式,设置超时时长为一分钟
            if conn.client_listen_mode == "manual":
                self.iat_params["eos"] = 60000

            self.asr_ws = await websockets.connect(
                ws_url,
                max_size=1000000000,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
            )

            logger.bind(tag=TAG).info("ASR WebSocket连接已建立")
            self.server_ready = False
            self.forward_task = asyncio.create_task(self._forward_results(conn))

            # 发送首帧音频
            if conn.asr_audio and len(conn.asr_audio) > 0:
                cached = tuple(conn.asr_audio[-10:])
                first_pcm = cached[0]
                await self._send_audio_frame(first_pcm, STATUS_FIRST_FRAME)
                logger.bind(tag=TAG).info("已发送首帧，开始识别")

                # 发送缓存的音频数据
                for cached_pcm in cached[1:]:
                    try:
                        await self._send_audio_frame(cached_pcm, STATUS_CONTINUE_FRAME)
                    except Exception as e:
                        logger.bind(tag=TAG).info(f"发送缓存音频数据时发生错误: {e}")
                        break
                self.server_ready = True

        except Exception as e:
            logger.bind(tag=TAG).error(f"建立ASR连接失败: {type(e).__name__}")
            if hasattr(e, "__cause__") and e.__cause__:
                logger.bind(tag=TAG).error(f"错误原因: {str(e.__cause__)}")
            if self.asr_ws:
                await self.asr_ws.close()
                self.asr_ws = None
            self.is_processing = False
            raise

    async def _send_audio_frame(self, audio_data: bytes, status: int):
        """发送音频帧"""
        if not self.asr_ws:
            return

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        self._frame_seq += 1
        frame_data = {
            "header": {"status": status, "app_id": self.app_id},
            "parameter": {"iat": self.iat_params},
            "payload": {
                "audio": {"audio": audio_b64, "sample_rate": 16000, "encoding": "raw",
                          "channels": 1, "bit_depth": 16, "seq": self._frame_seq,
                          "status": status}
            },
        }

        if self.config.get("res_id"):
            frame_data["header"]["res_id"] = self.config["res_id"]
        if status != STATUS_FIRST_FRAME:
            frame_data.pop("parameter")
        await self.asr_ws.send(json.dumps(frame_data, ensure_ascii=False))

    async def _forward_results(self, conn: "ConnectionHandler"):
        """转发识别结果"""
        try:
            while not conn.stop_event.is_set():
                try:
                    response = await asyncio.wait_for(self.asr_ws.recv(), timeout=60)
                    result = json.loads(response)
                    logger.bind(tag=TAG).debug(f"收到ASR结果: {result}")

                    header = result.get("header", {})
                    payload = result.get("payload", {})
                    code = header.get("code", 0)
                    status = header.get("status", 0)

                    if code != 0:
                        logger.bind(tag=TAG).error(
                            f"识别错误，错误码: {code}, 消息: {header.get('message', '')}"
                        )
                        break  # A failed recognition must not submit a partial transcript.

                    # 处理识别结果
                    if payload and "result" in payload:
                        text_data = payload["result"]["text"]
                        if text_data:
                            # 解码base64文本
                            decoded_text = base64.b64decode(text_data).decode("utf-8")
                            text_json = json.loads(decoded_text)
                            if text_json.get("ret", 0) != 0:
                                raise ValueError(f"讯飞识别返回错误码 {text_json['ret']}")
                            self._merge_result(text_json, payload["result"])

                    if status == 2 or payload.get("result", {}).get("status") == 2:
                        logger.bind(tag=TAG).debug("收到最终识别结果，触发处理")
                        if not self._finalizing:
                            self._finalizing = True
                            # Final result is already here; do not send a second last frame.
                            await super().handle_voice_stop(conn, conn.asr_audio.copy())
                        break

                except asyncio.TimeoutError:
                    logger.bind(tag=TAG).error("接收结果超时")
                    break
                except websockets.ConnectionClosed:
                    logger.bind(tag=TAG).info("ASR服务连接已关闭")
                    self.is_processing = False
                    break
                except Exception as e:
                    logger.bind(tag=TAG).error(f"处理ASR结果时发生错误: {str(e)}")
                    if hasattr(e, "__cause__") and e.__cause__:
                        logger.bind(tag=TAG).error(f"错误原因: {str(e.__cause__)}")
                    self.is_processing = False
                    break

        except Exception as e:
            logger.bind(tag=TAG).error(f"ASR结果转发任务发生错误: {str(e)}")
            if hasattr(e, "__cause__") and e.__cause__:
                logger.bind(tag=TAG).error(f"错误原因: {str(e.__cause__)}")
        finally:
            # 清理连接资源
            await self._cleanup()
            conn.reset_audio_states()

    async def handle_voice_stop(
        self, conn: "ConnectionHandler", asr_audio_task: List[bytes]
    ):
        """Request finalization; only the final server response may submit the transcript."""
        await self._send_stop_request()

    def _merge_result(self, text, envelope=None):
        envelope = envelope or {}
        sequence = int(text.get("sn", envelope.get("seq", len(self._segments))))
        replacement = text.get("pgs", envelope.get("pgs"))
        region = text.get("rg", envelope.get("rg"))
        if replacement == "rpl" and isinstance(region, list) and len(region) == 2:
            for key in list(self._segments):
                if int(region[0]) <= key <= int(region[1]):
                    del self._segments[key]
        self._segments[sequence] = "".join(
            slot.get("cw", [{}])[0].get("w", "")
            for slot in text.get("ws", []) if slot.get("cw")
        )
        self.text = "".join(self._segments[key] for key in sorted(self._segments))

    def stop_ws_connection(self):
        if self.asr_ws:
            asyncio.create_task(self.asr_ws.close())
            self.asr_ws = None
        self.is_processing = False

    async def _send_stop_request(self):
        """发送停止识别请求（不关闭连接）"""
        # A stop can arrive while the WebSocket handshake is still in progress.
        for _ in range(100):
            if not self.is_processing or self.server_ready:
                break
            await asyncio.sleep(0.1)
        if self.asr_ws and not self._last_frame_sent:
            self._last_frame_sent = True
            self.is_processing = False
            try:
                await self._send_audio_frame(b"", STATUS_LAST_FRAME)
                logger.bind(tag=TAG).debug("已发送停止请求，等待最终识别结果")
            except Exception:
                logger.bind(tag=TAG).error("发送讯飞停止请求失败")

    async def _cleanup(self):
        """清理资源（关闭连接）"""
        logger.bind(tag=TAG).debug(
            f"开始ASR会话清理 | 当前状态: processing={self.is_processing}, server_ready={self.server_ready}"
        )

        # 状态重置
        self.is_processing = False
        self.server_ready = False
        self._last_frame_sent = False
        self._finalizing = False
        logger.bind(tag=TAG).debug("ASR状态已重置")

        # 关闭连接
        if self.asr_ws:
            try:
                logger.bind(tag=TAG).debug("正在关闭WebSocket连接")
                await asyncio.wait_for(self.asr_ws.close(), timeout=2.0)
                logger.bind(tag=TAG).debug("WebSocket连接已关闭")
            except Exception as e:
                logger.bind(tag=TAG).error(f"关闭WebSocket连接失败: {e}")
            finally:
                self.asr_ws = None

        # 清理任务引用
        self.forward_task = None

        logger.bind(tag=TAG).debug("ASR会话清理完成")

    async def speech_to_text(self, opus_data, session_id, artifacts=None):
        """获取识别结果"""
        result = self.text
        self.text = ""
        return result, None

    async def close(self):
        """资源清理方法"""
        if self.asr_ws:
            await self.asr_ws.close()
            self.asr_ws = None
        if self.forward_task:
            self.forward_task.cancel()
            try:
                await self.forward_task
            except asyncio.CancelledError:
                pass
            self.forward_task = None
        self.is_processing = False
