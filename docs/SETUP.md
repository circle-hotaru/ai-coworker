# 安装与配置

这是源码扩展仓库。Python 3.10+、Git、ffmpeg 与 Opus 是语音桥所需工具；
固件使用 ESP-IDF 6.1（最低 6.0.1），安装工具链后从对应环境构建。

## 准备上游源码

在仓库根目录执行（会访问 upstreams.json 列出的两个公共 GitHub 仓库）：

```sh
python3 scripts/materialize.py bridge
python3 scripts/materialize.py firmware
python3 -m venv .venv
.venv/bin/python -m pip install -r .build/bridge/main/xiaozhi-server/requirements.txt
```

工具拒绝覆盖已有 .build 组件目录。该目录是生成/运行工作区，不要提交。
上游依赖含模型、原生库和平台版本约束，安装前阅读固定版本的上游说明。

## 语音桥

1. 将 examples/devices.example.yaml 复制到 runtime/devices.local.yaml（先创建 runtime/）。
   替换示例 MAC 和 Agent ID。push_enabled/dance_enabled 必须是布尔值，最多一个动作设备。
   firmware_label 必须和所编固件响应一致：非 C 板 Reviewer、C 板 Researcher、StackChan Operator。
   这些标签只用于端点身份匹配，Agent ID 可独立修改。
2. 创建 .build/bridge/main/xiaozhi-server/data/.config.yaml，使用 examples/bridge.example.yaml
   作为覆盖配置。device_map 填入上一步文件在你机器上的绝对路径；api_key 填入本机 Gateway 凭据。
   将 bridge-host.local 替换为设备可达的实际 Mac/Linux 主机地址，避免 VPN 接口误选。
3. 在固定上游的配置说明中完成 FunASR/SenseVoiceSmall 与 Silero 模型配置，
   核对模型路径和中文语言设置；模型不随本仓库分发。TTS 沿用上游 EdgeTTS 配置。
4. 在本机准备 OpenClaw Gateway，并建立与你的映射一致的 Agent；工作区人格可参考
   examples/personas。不要把文件复制当作 Agent 已完成注册或通信验收。
5. 执行 .venv/bin/python scripts/run_bridge.py。每台设备的 OTA 指向
   http://你的主机:8003/xiaozhi/ota/。不要在已有桥实例占用端口时重复启动。

devices 文件中的语音路由每连接读取；更改通知/动作登记、凭据或服务配置后重启桥。
本地运行数据会保存在设备映射旁，必须保持该目录私有。

## 插件

integrations/openclaw-agent-voice-push 与 integrations/openclaw-stackchan-dance
是插件源码。按你所安装 OpenClaw 版本的插件管理方式安装；本仓库没有运行 Gateway 安装操作。
主动播报钩子需要显式允许会话访问（hooks.allowConversationAccess=true）。
Gateway 进程启动环境支持 AI_COWORKER_AGENTS（逗号分隔，默认 reviewer,researcher,operator）
和 AI_COWORKER_DANCE_AGENT（默认 operator）；修改环境需要重启对应 Gateway 进程。
插件连接固定本机 8003 桥端口，不要向公网开放事件/动作入口。

## 可选讯飞

在 runtime/xunfei/credentials.yaml 填入自己的 credentials.example.yaml 三字段。
从根目录运行 .venv/bin/python integrations/xunfei-asr/manage.py check，
probe --audio 自己授权的.wav，确认结果后 apply --audio 同一录音并重启桥。
probe/apply 都会实际将录音发给讯飞，格式须为 16kHz/16bit/单声道、不超过 60 秒。
rollback 只恢复 ASR 字段。服务/私有目录可由 AI_COWORKER_SERVER、AI_COWORKER_PRIVATE 覆盖。
缺凭据时可回退已有本地 FunASR；鉴权、额度或网络错误不在录音中途静默回退。

## 固件

在 .build/firmware 中使用 scripts/build.py --list-boards 查看板型，按上游规范串行构建。
固件扩展支持 StackChan/CoreS3、Waveshare ESP32-S3-Touch-AMOLED-1.75 非 C 与 C 板。
每次选择精确板型、Flash 容量、分区、资源与唤醒配置；不能跨板直接互刷。
本仓库不提供原设备头像、资源包或烧录镜像；使用公开上游的默认资源流程或你自己的素材。
新硬件需单独核验分区和备份，源码测试不能代替实机验收。

动作还要求该设备 NVS 中已有正确的 servo/zero_pos_1、zero_pos_2 校准值；
公开固件不内置其他设备的校准位置，缺值或越界会禁用动作。校准应按硬件厂商流程完成。

## 离线回归测试

准备好尚未配置运行凭据的两个 .build 源码树及依赖后，执行：

```sh
.venv/bin/python scripts/test.py
```

还需要 Node.js 与主机 C++ 编译器。测试使用 mock，不连接云端、Gateway 或真实硬件。
测试工具拒绝已有 data/.config.yaml 的桥目录，以避免读取使用者的运行配置。
