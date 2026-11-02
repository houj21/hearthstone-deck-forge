# 炉石卡组构筑器（Hearthstone Deck Forge）

中文卡池 + 官方卡牌组码 + 真实天梯环境数据 + AI 教练，四合一的本地炉石构筑工具。
PC 与手机同 WiFi 通用，数据全部落在本地 SQLite，不需要任何账号。

---

## 快速开始

### 一键启动（推荐）

双击项目根目录的 **`run.bat`**（或命令行执行 `py -3.13 run.py`）。

它会自动完成：建 `.venv` → 装 `requirements.txt` 依赖 → 打印访问地址 → 启动服务 → **自动打开浏览器**。

依赖按 `requirements.txt` 内容哈希判断，改了依赖下次启动会自动重装；不想自动开浏览器时可设
`DECKFORGE_NO_BROWSER=1`（例如跑自动化时）。

```
========================================================
  Hearthstone Deck Forge is starting
  PC   : http://127.0.0.1:8765
  Phone: http://192.168.x.x:8765   (same Wi-Fi)
========================================================
```

### 手动启动

```bash
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8765
```

> 需要 Python **3.13**。HSReplay 环境数据要用本机 Edge/Chrome 内核，
> 首次抓取会自动拉起 Playwright 浏览器进程，无需额外配置（浏览器不可用时环境页会降级到本地留档）。
> 浏览器内核缺失时执行：`.venv\Scripts\python.exe -m playwright install chromium`

### 首次访问会发生什么

1. 启动时自动下载并入库中文卡表（6131 张，缓存 24 小时，之后增量刷新）；
2. 后台按 TTL 抓取 HSReplay 环境快照（首次约 10-30 秒），环境页自动出现数据；
3. 「我的」页 stamp 保存在本地 SQLite，不上传。

---

## AI 教练配置（可选）

不配凭证也能用全部功能，只是 AI 部分会走**规则兜底**（仍能出 30 张卡组）。

复制根目录 `.env.example` 为 `.env` 后填写：

```ini
LLM_BASE_URL=https://your-gateway/v1     # OpenAI 兼容网关根地址
LLM_API_KEY=sk-xxxx                      # 网关凭证
LLM_MODEL=Model-A                        # 必须显式指定模型
LLM_MODEL_FALLBACKS=Model-B,Model-C      # 主模型失败时按序降级
LLM_TIMEOUT=360                          # 秒；网关长文本响应可达 200-330 秒
```

`.env` 已在 `.gitignore` 中，密钥不会进版本库；凭证与模型**只**从这里读取，不写死在代码和 YAML。

> 实测提醒：部分网关的「重推理」模型（如 `step-5-preview`）90 秒吐不出首 token，会把界面拖成假死。
> 已在 `server/ai/client.py` 按「首包超时 / 连接重置 / 空 content」三种失败自动换下一个模型。
> 已验证可用的组合：主 `MiMo-V2.6-Flash`，兜底 `Qwen3.8-27B`、`DeepSeek-V4.1-Flash`。

---

## 功能一览

| 功能 | 说明 | 主要实现 |
|---|---|---|
| 中文卡池 | 6131 张可收集卡，按职业/费用/关键词/稀有度/系列筛选与搜索 | `server/cardpool/` |
| 组卡器 | 点到添加、右键减一，实时校验（30 张 / 传说上限 / 职业与模式合法性） | `web/static/js/cards.js`、`server/deckcode/validate.py` |
| 卡牌组码 | 官方算法编码、解码，编解码对拍一致 | `server/deckcode/codec.py` |
| 我的卡组 | 本地保存/载入/删除 | `server/db/`、`server/api/decks.py` |
| 环境数据 | HSReplay 真实胜率/样本/完整卡表，原型名英译中，按时间窗切换 | `server/meta/` |
| 推荐上分 | 贝叶斯收缩排序 + 职业多样性 + 分段/职业过滤 + 一键导入 | `server/recommend/engine.py` |
| AI 教练 | SSE 流式自动构筑 / 换卡建议 / 卡组点评，输出本地复核后重试 | `server/ai/` |

### AI 教练怎么用

右侧抽屉（手机上是底部弹出）→ 选一个意图（更快 / 更贪 / 针对快攻 / 更便宜 …）→
点「AI 自动构筑」→ 流式看到进度与思路 → 点「采纳这套卡组」直接进组卡器。
想微调单卡：在组卡器里点卡组中的某张卡 → 抽屉里点「换卡建议」。

**模型输出一律不直接信任**：卡名必须一字不差命中本地卡池，凑不够 30 张或传说超限，
就把具体错误回喂模型重试（最多 2 次）；仍然不过则由 `server/ai/rules.py` 按曲线配比兜底，
并在界面如实标注「规则兜底」和失败原因。

---

## 目录结构

```
lsgzq/
├── run.py, run.bat             # 一键启动
├── requirements.txt            # 依赖
├── pytest.ini
├── config/
│   ├── app.yaml                # 端口/卡池源/环境源/推荐参数/AI 行为参数
│   └── sets.yaml               # 标准模式可用系列（轮换时需校准）
├── server/
│   ├── main.py                 # FastAPI 应用与路由挂载
│   ├── settings.py             # YAML + 环境变量/ .env 读取
│   ├── db/{base.py, models.py, repo.py}
│   ├── cardpool/{fetcher.py, normalizer.py, service.py}
│   ├── deckcode/{codec.py, validate.py, heroes.py}
│   ├── meta/{browser.py, normalizer.py, service.py, providers/hsreplay.py}
│   ├── recommend/engine.py
│   ├── ai/{client.py, prompts.py, candidates.py, builder.py, rules.py}
│   └── api/{health,cards,decks,meta,recommend,ai}.py
├── web/
│   ├── templates/index.html
│   └── static/{css/theme.css, js/{app,api,cards,meta,ai,mine}.js}
├── tests/                      # 单测 + UI 冒烟
├── tools/                      # 探针与维护脚本
├── docs/{需求文档.md, 设计文档.md, context_HSreplayAPI.txt}
└── data/                       # 运行时数据（SQLite、卡表缓存、截图）
```

---

## API

| 分组 | 端点 |
|---|---|
| 健康 | `GET /api/health` |
| 卡池 | `GET /api/cards`、`/sets`、`/classes`、`/stats`、`/{dbf_id}`、`POST /refresh` |
| 卡组 | `POST /decks/parse`、`/encode`、`/validate`、`/save`；`GET /decks/heroes`、`/saved`、`/saved/{id}` |
| 环境 | `GET /api/meta/status`、`/summary`、`/entry/{id}`、`POST /refresh` |
| 推荐 | `GET /api/recommend`、`/api/recommend/buckets` |
| AI（全部 SSE） | `GET /api/ai/status`、`/build`、`/swap`、`/review` |

在线文档：启动后访问 `http://127.0.0.1:8765/docs`。

---

## 数据源与免费额度

| 源 | 用途 | 实测 |
|---|---|---|
| HearthstoneJSON (zhCN) | 中文卡表 | 直连 200 |
| HSReplay 分析接口 | 环境数据主源（胜率/样本/卡表） | 直连 403，**真实浏览器内核 200** |
| HSReplay 原型字典 / 版本周期 | 原型名翻译、当前补丁 | 同上 |
| HSGuru / NGA | — | 本机网络层不可达，已停用（保留配置位） |

HSReplay 免费额度边界（逐个参数实测 403/400 验证）：

- 段位只有 `BRONZE_THROUGH_GOLD` 免费，传说/钻石档需会员；
- 时间窗只有「当前版本」「近30天」免费；
- 地区只有「全部」免费。

因此**分段推荐**采用（已确认的方案）：免费数据 + 时间窗切分，再由卡组的**节奏风格**
（快攻/中速/控制/组合技）与胜率推断适配段位，而不是 HSReplay 的真实分段数据。

---

## 测试

```bash
# 全量单测（44 项，使用隔离卡池 fixture）
.venv\Scripts\python.exe -m pytest tests -q

# 真实卡池回归（校验标准轮换、真实卡组码、AI 端到端；默认跳过）
$env:RUN_REAL_POOL_TESTS=1
.venv\Scripts\python.exe -m pytest tests/test_real_decks.py tests/test_ai_real.py -q

# UI 冒烟（Playwright，含手机端 + AI 闭环，截图落在 data/shots）
.venv\Scripts\python.exe tests/smoke_ui.py
```

冒烟会检查：卡池渲染、搜索、组卡到 30/30、卡组码双向、保存到「我的」、环境页真实数据、
推荐榜一键导入、AI 构筑→采纳闭环、手机 Tab 可见性、控制台错误数（须为 0）。

---

## 维护脚本（`tools/`）

| 脚本 | 用途 |
|---|---|
| `probe_sources.py` | 探活所有数据源与直连可用性 |
| `probe_params.py` | 枚举 HSReplay 参数取值与免费/付费边界 |
| `probe_llm.py` | 探测 LLM 网关连通性与 content/reasoning 字段 |
| `probe_llm_json.py` | 实测模型能否稳定输出可校验通过的卡组 JSON |
| `smoke_ai.py` | AI 接口 SSE 真实网关冒烟 |
| `extract_heroes.py` | 更新英雄卡 dbfId 映射 |

---

## 文档

- `docs/设计文档.md`：需求映射、架构、各阶段实测结论（数据源边界、模型对比、推荐算法、AI 校验链路）、
  关键决策、目录结构、防踩坑清单、交付验收基线。

---

## 已知限制

1. **标准轮换**：新版本上线后需校准 `config/sets.yaml`（用 `tools/probe_params.py` 取权威系列清单，
   再用 `tests/test_real_decks.py` 回归真实卡组码验证）。
2. **分段数据是推断的**，不是真实分段（见上文免费额度）。
3. **卡组原型名**里若有未登录的英文词会原样保留（如 `Zee`、`Leyline`），可在
   `server/meta/normalizer.py` 的 `KEYWORD_CN` 里增量补表。
4. AI 输出受模型能力影响，个别时候会触发规则兜底——界面会明确标注，不会假装是模型给的。
