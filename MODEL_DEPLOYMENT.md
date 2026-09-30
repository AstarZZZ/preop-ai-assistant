# 本地模型部署与验收

## 固定版本

`requirements-asr.txt` 锁定 FunASR 1.3.26、PyTorch/TorchAudio 2.8.0、FastAPI 0.141.1、Uvicorn 0.52.1、imageio-ffmpeg 0.6.0 和 pypinyin 0.55.0。后两者分别用于容器内音频解码和中文热词模糊匹配。ASR 权重包含 SenseVoiceSmall、FSMN-VAD、CAM++ 和 CT-Punc。文本模型使用 Ollama 0.9.0 下的 `qwen3:4b`。

业务端默认只允许 `PREOP_ASR_BACKEND=remote`，模型服务默认只从本地 `models/` 读权重。自动化测试使用的 `test-stub` 必须同时设置 `PREOP_TESTING=1`，不能在正常运行中触发。

## 权重目录

```text
models/modelscope/models/
├── iic--SenseVoiceSmall/snapshots/master/
├── iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master/
├── iic--speech_campplus_sv_zh-cn_16k-common/snapshots/master/
└── iic--punc_ct-transformer_cn-en-common-vocab471067-large/snapshots/master/
```

医院内网部署应在联网准备机完成权重下载、哈希留档和安全审查，再复制到内网。正式运行时保持 `PREOP_ALLOW_MODEL_DOWNLOAD=0`。

## 原生环境变量

```bash
export PREOP_ASR_BACKEND=remote
export PREOP_ASR_URL=http://127.0.0.1:8766
export PREOP_ASR_DEVICE=cpu
export PREOP_LLM_URL=http://127.0.0.1:11434/v1
export PREOP_LLM_MODEL=qwen3:4b
```

## 必须验收

1. 健康接口显示 ASR 与 Qwen 均为 `ready`，且 ASR 为 `offline_only`。
2. 使用 3–5 名真实不同讲话人、10 分钟左右的去标识化会议音频，验证讲话人标签、转写和时间戳。
3. 分开统计字错率、医学术语错误率、讲话人混淆率、同人拆分率和实时延迟；不用单一“准确率”掩盖子任务差异。
4. 组织两名医务人员独立校对至少 30 分钟转写，处理标注分歧后再形成指标。
5. 断开公网后重启并完成一次 WebM 录音识别和 Qwen 报告，确认没有隐式下载或外部 API。
6. 输入空音频、断裂 WebM、重叠语音、同音色讲话人和超长录音，确认会报错或进入人工复核，不生成虚构转写。
7. 验证 Qwen 不合法 JSON 会触发一次结构修复，再失败则回退到确定性摘要。
8. 确认规则引擎的预警编号、等级和触发状态不会被 Qwen 修改。
9. 输入医院常用手术名并录制包含该术语的语音，确认术语被传入本地 ASR 热词链路，且不会将未说出的热词写入转录。

## 已知工程边界

- CAM++ 是匿名聚类，只输出“讲话人1/2”；要绑定真实医生身份，需要独立的经同意声纹库和合规方案。
- 讨论人数作为聚类先验，不代表模型一定能在话语太短、同时说话、高混响或强噪声下正确分开所有人。
- 滚动实时识别会重复计算累计音频；原型优先保证录音可追溯和 WebM 可解码。院内高并发试点应换成流式 WebSocket 和有状态讲话人跟踪。
- 规则库必须由院内专业组审核；内置规则只用于流程开发，不得直接视为临床指南。
