# AI Coworker

通过 ESP32 语音硬件与本机 OpenClaw Agent 协作：开始前对齐目标，执行中依据实际进展校准，
提交前检查事实与判断。支持连续对话、长任务等待、空闲后续播报和 StackChan 固定动作。

仓库采用固定上游版本 + 扩展源码覆盖层。保留项目的固件/桥/插件实现，
依赖由脚本从公共上游准备；历史部署文件与运行环境不进入源码仓库。

| 路径 | 内容 |
| --- | --- |
| overlays/firmware | 固件扩展，覆盖到固定上游树 |
| overlays/bridge | 语音桥扩展与相关测试 |
| integrations | 两个 OpenClaw 插件与可选 ASR 配置工具 |
| examples | 虚构人格、合成设备映射与空凭据模板 |
| scripts | 上游准备、启动与公开内容检查 |
| upstreams.json | 固定公共上游版本 |

先阅读 [安装步骤](docs/SETUP.md)、[架构与边界](docs/ARCHITECTURE.md)、
[验证范围](docs/RELEASE_STATUS.md) 和 [上游声明](THIRD_PARTY_NOTICES.md)。

示例默认本地 ASR、OpenClaw、EdgeTTS；可选讯飞云 ASR。麦克风处理与工具执行边界
见架构文档。角色是虚构配置，公开版不包含真实工作人格、业务资料或任何现成服务凭据。

此目录是公开源码候选，尚未发布远程仓库或二进制。
