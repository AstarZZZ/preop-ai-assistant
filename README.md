# 术前智议：本地术前讨论 AI 辅助原型

这是一个本地优先、无演示转写回退的 Vue 3 + Python 原型：

- 创建术前讨论，录入手术、患者脱敏编号、科室、讨论人数和患者历史资料；
- 选择麦克风和本地存储目录，显示波形，保存原始录音；
- 约 8 秒滚动执行真实 SenseVoiceSmall + FSMN-VAD + CAM++ + CT-Punc 识别；
- 将新建讨论时的手术名称、科室和手术部位作为本地 ASR 热词，提高专业词命中率；
- 输出“讲话人1/2/3 + 时间戳 + 文本”，允许人工修订角色和转写；
- 可维护的本地知识规则库，支持新增、编辑、复制、启停、分类检索、JSON 导入导出和规则试跑；
- 本地 Qwen3:4B 生成患者摘要、讨论摘要、比对项和手术关键总结；
- SQLite 保存原始文本、摘要、比对结果、预警、结论和审计信息。

> 本项目是研究与流程验证原型，不是医疗器械或正式临床系统。AI 输出不构成诊断、治疗、麻醉或手术决策，不作为医疗责任认定或具有法律效力结论的独立依据，所有重要信息须由具备资质的医务人员复核。

## 当前实测环境

- Apple M4 Pro / 24 GB 内存；
- Python 3.10.20；
- FunASR 1.3.26；
- PyTorch / TorchAudio 2.8.0；
- SenseVoiceSmall、FSMN-VAD、CAM++、CT-Punc 权重位于 `models/`；
- FFmpeg 8.1.2；
- Ollama 0.9.0 + `qwen3:4b`；
- Docker 28.1.1 / Compose 2.35.1。

15.47 秒中文术前讨论测试音频在 CPU 上约 3.7 秒完成识别。浏览器 WebM/Opus 录音也已验证可解码和识别。

## 原生启动（macOS 推荐）

macOS 上原生 Ollama 可使用 Metal，比将 Ollama 放入 Linux 容器更快。

```bash
npm ci
npm run build
python3 -m venv .venv-asr
.venv-asr/bin/pip install -r requirements-asr.txt
ollama pull qwen3:4b
./scripts/start_native.sh
```

打开 <http://127.0.0.1:8765>。启动脚本会检查 FFmpeg、Ollama、Qwen 权重和 ASR 健康状态；任一真实模型缺失时会停止，不会切换为伪造文本。

## Docker 一键启动

当前机器已有 `models/` 权重时：

```bash
cp .env.example .env
docker compose up --build
```

新机器第一次准备 ASR 权重时，先在 `.env` 设置 `PREOP_ALLOW_MODEL_DOWNLOAD=1`，联网启动一次；权重准备完成后改回 `0`，再断网验证。`ollama-init` 会把 Qwen 权重保存在 Docker 卷中。

容器包含：

- `app`：Vue 静态前端 + Python 业务 API；
- `asr`：FastAPI + 内置 FFmpeg 解码器 + FunASR + PyTorch；
- `ollama`：Qwen 运行时；
- `ollama-init`：第一次自动准备 `qwen3:4b`；
- `./data`：SQLite 和原始录音持久化；
- `./models`：ASR 权重持久化。

## 健康检查

```bash
curl http://127.0.0.1:8766/health
curl http://127.0.0.1:8765/api/health
```

ASR 必须显示 `state: ready`、`weights_ready: true`、`offline_only: true`；Qwen 必须显示 `state: ready`。录制页只有在 ASR 就绪时才允许点击“开始会议录制”。

## 添加本地知识库

打开“知识规则”页面后，可直接新增条目，或导入 [`knowledge-template.json`](knowledge-template.json)。导入数据只写入本地 SQLite，不上传公网。

支持四类规则：

- `required_discussion`：必须讨论项，转写未命中任一覆盖词时提示；
- `conditional_term`：患者资料命中触发词，但讨论未命中覆盖词时提示；
- `contraindication_term`：患者资料命中疑似禁忌/高风险词时始终提示人工复核，系统不自动下临床结论；
- `patient_data_required`：患者历史资料未录入时提示。

每次会议分析会保存当时的知识库版本，并在预警中保留患者命中片段、转写证据、条目来源和条目版本。编辑或停用条目后，对历史会议点击“重新分析”才会应用新规则。

## 测试

```bash
PYTHONPYCACHEPREFIX=/tmp/preop-pycache python3 -m unittest discover -s tests -v
PREOP_ASR_BACKEND=remote PREOP_ASR_URL=http://127.0.0.1:8766 python3 scripts/real_pipeline_test.py
```

产品分层、小模型指令跟随策略和试点边界见 [`ARCHITECTURE.md`](ARCHITECTURE.md)，权重和验收细节见 [`MODEL_DEPLOYMENT.md`](MODEL_DEPLOYMENT.md)。

## 关于

本项目为原型系统，由杭州电子科技大学赵博士团队开发。邮箱：JunZhe_Zhao@hdu.edu.cn。
