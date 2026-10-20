# Shopee AI Creative Agent：开发计划与学习路线图

> 版本：v1.0 · 2026-10-19<br>
> 用途：供 `shopee-agent` 项目的 Codex/Cursor 读取，作为分阶段开发与教学依据。<br>
> 注意：这是根据目标岗位和此前讨论制定的**拟开发项目**，不是 Shopee 官方内部系统或对招聘考核内容的保证。

> 最新协作约定（2026-10-20）：按用户要求连续实现并测试，不再提供理解题或测试代码讲解；
> 环境知识不作重点，只解释关键设计和真实限制。以下 Day 1 的逐题教学记录保留为历史，不再要求逐题等待。

## 1. 项目目标

开发一个面向电商营销的 **AI Creative Studio Agent**：用户提交创意 Brief（如商品、卖点、品牌、尺寸、视觉风格），系统理解需求、生成多个候选方案、允许用户选择和局部修改、维护版本记录，并在用户确认后导出作品。

项目要证明的不是“会调模型 API”，而是：能设计可查询、可恢复、可测试、可观测、可控制成本的 AI Agent 产品。

### 非目标（初期不做）
- 不直接对接 Shopee 生产系统或非公开 API。
- 不在 Day 1 就引入 LangGraph、PostgreSQL、Redis 和复杂前端。
- 不承诺所有扁平图片都能完美进行局部文字编辑。
- 不把 AI 自动生成的代码视为无需审查的正确实现。

## 2. 开发与学习约定

**工作环境：** Windows + WSL Ubuntu（Linux 文件系统 `/home/.../projects/shopee-agent`）、Cursor、ChatGPT/Codex、Python。

**分工：**
- 学习者：提出需求、选择技术方案、解释数据流、审查关键实现、实际验收和复盘；**不强制手写代码**。
- Codex：小步实现、补充测试、运行并汇报结果、解释关键代码和常见故障。
- 当前方式：Codex 连续实现、测试和更新进度；仅在关键设计/外部依赖处简述，不以理解题阻塞开发。

**每一步遵循：** 需求 → 设计（含取舍）→ Codex 实现 → 测试 → 阅读关键代码 → 验收 → Git 提交。

**状态约定：** `未开始`、`进行中`、`已验收`。本路线图中所有开发阶段默认为**未验收**；以仓库真实代码及测试结果为准，不能因为曾讨论过就标记完成。

## 3. 目标架构（逐步演进，非一次建成）

```text
用户浏览器（React，后期）
    |
    v
FastAPI（鉴权、参数校验、请求幂等、任务查询）
    |                         \
    v                          v
PostgreSQL（任务、版本、审计）   可靠任务投递机制 / Redis 队列
                                   |
                                   v
                              Worker + LangGraph
                                   |
                     +-------------+------------+
                     |                          |
                LLM / 图像工具              文件/对象存储
                     |                          |
                     +-------------+------------+
                                   |
                          结果与状态持久化
```

**特别注意：** 数据库写入成功和队列投递成功之间存在一致性问题，后期采用 Outbox 等机制或合适的可靠队列方案；Worker 可能重复执行，业务处理须按幂等设计；模型提供商未必支持查询任务与幂等请求。

## 4. 分阶段开发计划

### 阶段 0：本地环境与协作规范（约 0.5–1 天）
**目标：** Codex 与 Cursor 指向同一个 WSL 项目；能重复运行项目。

**产物：** `README.md`、`AGENTS.md`、`.gitignore`、`.venv`（不提交）、Git 仓库。

**验收：** `pwd` 显示 `/home/.../projects/shopee-agent`；Codex 能读取仓库；`python3 --version`、`git status` 正常；不提交密钥和虚拟环境。

**学习：** WSL 与 Windows 文件路径、虚拟环境、Git 工作流、Codex 权限。

### 阶段 1：FastAPI 与任务状态（第 1 周，已验收）
**目标：** 先把任务提交与查询链路运行起来，不接模型。

**范围：**
- `GET /health` 返回健康状态。
- `POST /tasks` 接收 JSON `prompt`，校验非空内容，生成 UUID，返回任务标识，建议 HTTP 201。
- `GET /tasks/{task_id}` 查询任务，不存在返回 404。
- 内存字典保存任务；初始状态 `PENDING`。
- pytest 对正常创建、空 Prompt、未知 ID 进行测试。

**验收：** Swagger `/docs` 可以调用两个业务 API；测试通过；重启后任务消失（主动体验内存存储局限）。

**学习重点：** HTTP GET/POST、JSON、路由装饰器、Pydantic、UUID、HTTP 状态码、内存状态、API 测试与日志。

**不要提前加入：** 数据库、真实模型 API、前端、任务队列。

### 阶段 2：持久化与用户隔离（第 2 周前半，已实现验证）
**目标：** 重启服务后任务仍然存在，并防止跨用户访问。

**范围：** PostgreSQL；任务表（ID、owner_id、prompt、status、created_at、updated_at、result_ref、error）；数据库迁移；基础鉴权的开发方案（可以先用测试身份，不能把测试身份冒充生产安全）。

**验收：** 服务重启后可查询旧任务；不存在返回 404；未授权访问被拒绝；数据迁移可重复执行。

**学习重点：** SQL、主键与唯一约束、索引、数据库事务、ORM、鉴权与授权区别。

### 阶段 3：后台任务、幂等与故障恢复（第 2 周后半–第 3 周）
**目标：** 长任务独立运行，浏览器退出后仍可查询。

**范围：** 任务队列（Redis + Worker 或等价方案）；状态 `PENDING/RUNNING/SUCCESS/FAILED`；任务 ID 查询；幂等键；超时和有上限的重试；队列背压；异常任务检查。

**验收：** 关闭浏览器后任务可以继续；重复提交同一幂等键只创建一个逻辑任务；模拟 Worker 崩溃后不会无限停在 `RUNNING`；失败有可解释的最终状态。

**学习重点：** `async/await` 与后台 Worker 的区别、队列、并发控制、竞态条件、任务状态机、至少一次投递、幂等、指数退避、状态对账；不能假定外部模型只会计费一次。

### 阶段 4：LangGraph Agent 基础（第 4 周）
**目标：** 从简单任务后端进化为可控的 Agent 工作流。

**范围：** Brief 结构化解析、工具选择与调用、工作流 State/Node/Edge、Checkpoint、失败分支、人工确认节点。

**验收：** 能展示一条从用户 Brief → 解析 → 调用模拟工具 → 返回结构化候选方案的完整 Trace；错误路径可测试；中断后在支持的检查点恢复。

**学习重点：** Agent 与固定工作流的边界、结构化输出、Tool Calling、图状态、检查点、模型幻觉与工具权限。

### 阶段 5：创意生成 MVP 与编辑（第 5 周，真实模型验收待凭据）
**目标：** 展示适合 Shopee 岗位场景的真实产品能力。

**范围：** 接入授权的文本/图像模型 API；生成 2–3 个候选海报；作品版本管理；用户选择与修改；优先对独立文字图层做确定性编辑；扁平图像使用受限的局部编辑流程；导出。

**验收：** 输入 Brief 能得到候选；能修改价格且验证未授权图层数据未变化（有图层时）；修改记录可回退；模型失败不污染原作品。

**学习重点：** 模型供应商接口、图像生成与编辑差异、版本控制、文件存储、视觉/规则验证、成本意识。

### 阶段 6：Agent Eval、稳定性与可观测性（第 6 周）
**目标：** 把 Demo 提升为有证据的工程作品。

**范围：** 至少 30–50 个代表性测试案例；功能正确率、工具调用正确率、修改约束满足率、任务成功率；日志与 Trace ID；P50/P95 延迟、失败率、模型调用成本；限流、配额及降级策略。

**验收：** 可复现的评测脚本和结果；一次故障案例的 Trace；至少一个有前后对照数据的优化；明确哪些指标是模拟数据、哪些来自实际测试。

**学习重点：** Agent Eval、Guardrails、可观测性、尾延迟、压测、隐私与安全、模型路由的质量/速度/成本权衡。

### 阶段 7：部署、作品集与求职（第 6 周后，持续完善）
**目标：** 项目可演示、可解释、可投递。

**范围：** Docker Compose（按实际复杂度选择）、环境变量、部署流程、架构文档、README、录屏、技术决策记录、简历项目描述、模拟面试。

**验收：** 第三方能按 README 启动 Demo；无真实密钥泄露；清楚解释核心技术选择和限制；项目指标可追溯；准备 3 个故障定位与设计取舍案例。

**学习重点：** 部署、安全、工程文档、面试沟通。

## 5. 当前学习清单（现在优先）

| 顺序 | 主题 | 至少理解到什么程度 | 通过方式 |
|---|---|---|---|
| 1 | HTTP / REST | 能解释 POST、GET、201、400/422、404 的用途 | 阅读请求和响应实例 |
| 2 | FastAPI 路由 | 知道 `@app.post` 如何绑定路径与函数 | 解释已有代码数据流 |
| 3 | Pydantic | 知道为什么要校验输入、如何禁止空 Prompt | 审查错误请求测试 |
| 4 | 任务数据模型 | 理解 `task_id/prompt/status/result` | 解释创建和查询任务 |
| 5 | UUID 与幂等 | 理解唯一 ID ≠ 幂等键 | 分析重复点击案例 |
| 6 | pytest | 看懂测试输入、断言与失败信息 | 运行并解释测试 |
| 7 | 日志与异常 | 区分正常响应、参数错误与服务错误 | 根据日志定位一个故障 |
| 8 | 内存与持久化 | 知道重启为什么丢任务 | 做一次重启实验 |

**本周暂不深入：** LangGraph、SFT/强化学习、分布式事务理论、Kubernetes。这些不是当前瓶颈。

## 6. Day 1：今天的 Codex 执行顺序（90–120 分钟）

1. **15 分钟：** 检查 WSL 路径、Python 环境、`AGENTS.md`、Git 状态；Codex 只读取并报告。
2. **20 分钟：** Codex 创建/检查 `GET /health`；讲解每行作用；运行并验证。
3. **35 分钟：** Codex 实现 `POST /tasks` 和 `GET /tasks/{task_id}`，先向学习者解释数据流和设计选择，再修改文件。
4. **20 分钟：** Codex 补充 pytest，展示成功、输入错误、任务不存在三类结果。
5. **10–30 分钟：** 在 `/docs` 调用接口；重启服务确认任务丢失；回答两道理解题。

**今天的完成标准：** 你无需手写代码，但能口头解释一次 POST 如何被处理、数据存在哪里、为何重启会丢失、何时返回 404，以及为什么后续需要数据库。

## 7. Codex 全局协作提示词（可粘贴）

```text
你是我在 shopee-agent 项目的结对开发与技术导师。
先读取 AGENTS.md、现有 README 和代码，检查实际进度，绝不把规划中的功能当作已完成。
我有两年 Android Framework 经验，但 Python 后端不熟；我不希望亲自手写代码。
你负责小步编写、修改、运行和测试；我负责需求、设计、理解与验收。
连续推进路线图中的功能，由你编写并测试代码；不需要理解题，也不需要解释测试程序。
只在关键设计与真实外部依赖处简述，不输出长篇教程。
各阶段按真实实现和验证证据更新，不把模拟模式、配置文件或计划当作真实服务验收。
每次修改后运行相关测试，说明修改文件、测试结果、已知限制和下一步。
优先参考现有项目和可靠开源实现，但不要盲目引入依赖；禁止泄露密钥。
从第 10 节的真实进度继续实现，不重复已验证步骤；不将未验证的外部服务标记为完成。
```

## 8. 开发记录模板（每个功能复用）

```text
功能：
目标与用户价值：
设计方案与备选方案：
本次修改文件：
核心数据流：
验证方式和测试结果：
异常/边界情况：
尚未解决的风险：
我今天理解的技术点：
下一步：
```

## 9. 面试准备检查点

- 能解释为何长耗时任务使用 Worker，而非长期阻塞 HTTP 请求。
- 能解释幂等键、数据库唯一约束、重复点击与重复计费。
- 能描述 Worker 崩溃后的异常状态对账、有限重试与未知状态。
- 能用 Trace 区分排队、模型调用、存储等环节的延迟。
- 能说清楚“只改海报价格”如何通过分层编辑和验证保证。
- 能解释 P95 延迟与平均值的区别，以及模型路由如何权衡质量、成本和速度。

## 10. 阶段进度表（由 Codex 根据事实更新）

| 阶段 | 状态 | 完成证据 |
|---|---|---|
| 0 环境与规范 | 已验收 | 环境、README、依赖安装与初始 Git 推送已验证；用户明确取消后续理解题，不再以依赖题阻塞 |
| 1 FastAPI 任务接口 | 已验收 | 三个接口已实现，pytest 14 passed；真实进程重启后旧任务返回 404；学习者确认 Swagger 创建 201、查询 200，ID/prompt 一致，并理解输入校验、内存生命周期与 HTTP/业务状态的区别 |
| 2 PostgreSQL | 已验收 | PostgreSQL 16、SQLAlchemy/Alembic、重启持久化、开发/Token 身份与跨用户隔离已通过自动化验证；静态 Token 不等同完整生产身份系统 |
| 3 Worker/幂等/恢复 | 已验收 | 数据库可靠队列、独立进程、幂等冲突/并发、配额/背压、租约恢复/次数上限/旧 Worker 拒写已验证；外部模型 exactly-once 不作保证 |
| 4 LangGraph | 已验收 | StateGraph、三个图片工具节点、持久检查点、interrupt/Command 确认与故障续跑已在 mock + PostgreSQL 验证，不等同真实模型质量验收 |
| 5 创意生成编辑 MVP | 进行中 | 本地 Studio、三个候选、不可变版本、文字编辑/恢复、确认与 PNG/SVG/JSON 导出已实现；OpenAI 兼容服务文本解析已实测通过，图片返回 500；用户选择稍后配置图像服务，真实图片生成未验收 |
| 6 Eval 与可观测性 | 进行中 | 双后端 87 passed、40 个 mock 功能案例、Trace/usage/延迟/配额及检查点控制比较已完成；真实质量/账单/线上负载未测 |
| 7 部署与求职 | 进行中 | 本地 Docker Compose 构建/运行/导出/重启恢复已验证；README、作品集与 CI 配置已提供；线上部署、录屏与远程 CI 结果未验收 |

### 2026-10-19：Day 1 第 1–2 步核验

- 已阅读本路线图与 `AGENTS.md`，后续按小步实现 → 测试 → 讲解 → 理解题 → 学习者反馈推进。
- 环境：实际路径 `/home/wangjinwei/projects/shopee-agent`；系统和 `.venv` 的 Python 均为 3.12.3；已有 Git 仓库，但尚无提交，当前项目文件均未跟踪。虚拟环境、缓存与 `.env` 已被忽略。
- 真实代码：`main.py` 只有 FastAPI 实例及 `GET /health`，返回 `{"status": "ok"}`；`test_main.py` 只有健康检查测试，验证 HTTP 200、JSON Content-Type 和响应内容。
- 验证：运行 `.venv/bin/python -m pytest -q`，结果 `1 passed`；通过 TestClient 核验健康响应和 OpenAPI，业务路径仅 `/health`。此为进程内测试，尚未完成独立服务启动及浏览器 Swagger 验收。
- 参考：[FastAPI 官方入门](https://fastapi.tiangolo.com/tutorial/first-steps/)、[官方测试示例](https://fastapi.tiangolo.com/tutorial/testing/)。本步保留已有最小实现，不引入依赖或复杂架构。
- 本次仅更新路线图，已有健康接口无需重复实现。学习点为路由注册与字典到 JSON 响应的数据流；理解情况待学习者回答，不能标记为已验收。
- 尚未实现：任务请求模型、POST /tasks、GET /tasks/{task_id}、UUID、PENDING 状态、内存存储及相应测试；阶段 2–7 均未开始。
- 下一步：回答本轮理解题后，再进入 Day 1 第 3 步的小步设计与实现。

### 2026-10-19：Day 1 第 3 步（创建任务）

- 学习反馈：学习者正确解释了路由路径与 Python 函数名的区别，继续推进创建接口。
- 参考：[FastAPI 请求体](https://fastapi.tiangolo.com/tutorial/body/)、[HTTP 状态码](https://fastapi.tiangolo.com/tutorial/response-status-code/)、[Pydantic 字符串约束](https://docs.pydantic.dev/latest/api/standard_library_types/#strings)。比较声明式请求模型与手动解析 JSON，选择前者复用校验、错误响应与 Schema；不复制第三方代码，不新增依赖。
- 修改：`main.py` 增加 TaskCreate 请求模型、Task 响应模型、内存字典和 POST /tasks；`test_main.py` 增加创建及输入边界测试，并用 fixture 隔离各测试的任务数据。
- 数据流：JSON → 去除 prompt 首尾空白并检查非空字符串 → 生成 UUID v4 → 存入内存，状态 PENDING → 返回 HTTP 201 与 task_id/prompt/status。
- 验证：`.venv/bin/python -m pytest -q`，结果 `11 passed`。覆盖健康接口、正常创建及存储、缺少 prompt、空串、空格、制表符/换行、null、数字、数组、对象和重复提交；无效输入返回 422 且不新增任务，相同 prompt 的两次提交创建不同任务。
- 限制：仅在当前进程内保存；无持久化、跨进程共享、后台执行或幂等保证。状态只支持 PENDING；未增加查询接口、数据库或模型调用。
- 学习验收：本轮讲解请求模型如何在业务函数执行前校验输入，等待理解题回答；不能据测试通过认定学习验收或阶段 1 全部完成。
- 下一步：根据学习反馈继续实现 GET /tasks/{task_id}，讲解任务查询和 404。

### 2026-10-19：Day 1 第 3–4 步（查询任务）

- 学习反馈：学习者正确说明了空白 prompt 被清理、长度校验失败、业务函数执行前返回 422 的处理顺序。
- 参考：[FastAPI 路径参数](https://fastapi.tiangolo.com/tutorial/path-params/)、[官方错误处理示例](https://fastapi.tiangolo.com/tutorial/handling-errors/)。采用 UUID 类型路径参数和 HTTPException；比较字典直接索引与 get，选择后者显式处理不存在，避免未处理的 KeyError。不新增依赖。
- 修改：`main.py` 增加 GET /tasks/{task_id}；`test_main.py` 增加创建后查询、未知 UUID、非法 UUID 三个测试。
- 数据流：路径字符串 → UUID 校验和转换 → 按 UUID 查询同一内存字典 → 找到返回 HTTP 200 与 Task；未找到抛出 HTTPException，返回 404 和 `{"detail": "Task not found"}`。非法 UUID 在进入函数前返回 422。
- 验证：`.venv/bin/python -m pytest -q`，结果 `14 passed`。查询测试包含两条不同任务及重复读取，验证按 ID 返回对应任务且不新增或删除任务。
- 限制：仍是单进程内存存储；本轮只完成接口与自动化测试，尚未进行独立服务、浏览器 Swagger 调用及重启丢失实验，阶段 1 保持进行中。
- 学习验收：本轮讲解路径参数、字典查询、raise HTTPException 与 404/422 区别，等待学习者回答理解题。
- 下一步：学习反馈后再推进 Day 1 第 5 步的运行与重启验收，不进入阶段 2。

### 2026-10-20：Day 1 第 5 步（真实服务与重启实验）

- 本轮未修改 `main.py` 或 `test_main.py`，只更新进度；阶段 2 未开始。
- 验证方式：用一次性 Python 验证脚本启动独立 Uvicorn 子进程，通过本机 TCP/HTTP 请求接口；停止第一个服务进程，再在同一地址启动新进程。脚本退出时已清理实验进程，未保持演示服务运行。
- 结果：GET /docs 为 200 且包含 Swagger UI HTML；GET /openapi.json 包含创建、查询两个业务操作。仅验证页面响应和接口描述，未在浏览器中执行 Swagger 的 Try it out，不能视为该项已验收。
- 创建任务返回 201，任务 ID 为 `c1429630-560d-4f4e-9a92-6a001d01a0af`；重启前查询为 200 且内容匹配。第一个进程 PID 252174，第二个为 252177；重启后健康检查为 200，查询同一 ID 返回 404 和 `{"detail": "Task not found"}`。
- 原理：新进程重新加载模块并执行 `tasks: dict[UUID, Task] = {}`，旧进程字典中的记录未写入持久存储，所以无法恢复。刷新客户端页面不会自行重置仍在运行的服务端字典。
- 本轮未重复运行未修改的自动化测试，最近结果仍为 `14 passed`；真实服务实验另行通过，不能用 TestClient 的清空 fixture 冒充重启验证。
- 学习验收：讲解进程内存的生命周期与重启实验，等待学习者回答理解题；尚未据此将阶段 1 标记为已验收。
- 下一步：根据回答继续完成 Day 1 剩余验收与环境文档，不提前引入数据库。

### 2026-10-20：Swagger 交互验收准备

- 学习反馈：学习者正确解释刷新浏览器不会清空仍在运行的服务进程内存，重启丢失原理已理解。
- 尝试使用 computer-use 操作浏览器，但 node_repl 初始化返回 `sandboxCwd is not a local file URI: file:///home/wangjinwei/projects/shopee-agent`，尚未进行任何页面点击。不能将工具初始化失败视为交互验收完成。
- 8000 端口已占用，未停止或替换原服务；另启当前项目 Uvicorn 于 `http://127.0.0.1:8001`，启动成功。HTTP 核验 /health 与 /docs 均为 200。
- 本轮未修改业务或测试代码；提供 Swagger 创建/查询的操作说明，等待实际浏览器响应反馈。README 与依赖清单仍未补齐，阶段 1 保持进行中。

### 2026-10-20：阶段 1 验收完成

- 学习者明确确认：在 Swagger 页面实际执行 POST /tasks 返回 201，GET /tasks/{task_id} 返回 200，查询结果与创建响应的 task_id、prompt 完全一致。此项证据来自学习者实际操作反馈，不是 Codex 浏览器自动化结果。
- 已讲解 `main.py` 与 `test_main.py` 全部现有代码、测试运行方法与断言含义；学习者理解空白输入在业务函数前被拒绝、刷新页面不清空服务进程内存、查询成功必须同时验证内容，以及 HTTP 成功与任务执行状态相互独立。
- 阶段 1 验收证据齐备：接口代码、最近一次自动化测试 14 passed、真实进程重启导致任务丢失的实验、Swagger 创建与查询反馈。状态更新为已验收。
- 本轮仅修改路线图，没有修改业务或测试代码，没有重复运行测试，也未新增 Worker、数据库或其他功能。
- 剩余事项：阶段 0 仍缺 README 和依赖清单，Git 尚未提交；阶段 2–7 未开始。下一步先补齐可重复启动与测试的环境文档，不因阶段 1 验收而宣称整个 Day 1 协作流程或项目已完成。

### 2026-10-20：README 与依赖清单

- 新增 `README.md`：记录当前接口、状态码、内存存储限制、WSL 安装、Uvicorn 启停、Swagger 验证、pytest 命令和文件职责。未改动业务代码与测试代码。
- 新增 `requirements.txt`：固定直接运行依赖 fastapi 0.146.0、pydantic 2.14.1、uvicorn 0.54.0；新增 `requirements-dev.txt`：通过 `-r requirements.txt` 包含运行依赖，并固定 pytest 9.1.1、httpx2 2.14.0。
- 方案比较：导出原环境所有包会引入当前项目不使用的 CLI/云服务依赖，因此采用精简直接依赖清单，按运行/测试用途分文件；间接依赖由 pip 解析，未声称实现完整锁定。
- 参考：[pip requirements 官方说明](https://pip.pypa.io/en/stable/user_guide/#requirements-files)、[FastAPI 手动启动说明](https://fastapi.tiangolo.com/deployment/manually/)。本次使用官方安装方式，无第三方代码复制。
- 初次干净环境验证发现 httpx 的 StarletteDeprecationWarning；核对本地 Starlette 1.9.0 的 testclient 源码后，将开发清单改为当前优先支持且原环境已有的 httpx2，未修改 TestClient 使用方式。
- 最终验证：新建独立临时虚拟环境，只按 requirements-dev.txt 安装成功；pip check 返回 No broken requirements found；pytest 为 14 passed，无上述弃用提示；uvicorn --version 正常。临时环境已自动清理，原 .venv 未修改。
- 限制：这次在临时环境验证安装、依赖一致性、接口测试及 Uvicorn 入口可用；未在该临时环境重复真实服务重启实验。没有新增模型、数据库、鉴权或 Worker。
- 学习点：虚拟环境隔离、直接与间接依赖、requirements 的 `==`/`-r` 语法、python -m 命令。等待本轮理解题反馈；Git 尚无提交，阶段 0 仍保持进行中。

### 2026-10-20：Git 初始版本交付

- 用户指定交付仓库：`git@github.com:samurai-xcodes/Shopee-Agent.git`。推送前通过 SSH 核验远程无 refs，本地现有分支为 master，采用普通推送，不强制覆盖历史。
- 初始提交范围：`.gitignore`、`AGENTS.md`、`README.md`、本路线图、`main.py`、`test_main.py` 和两个 requirements 文件。虚拟环境、缓存及 `.env` 均被忽略。
- 提交前再次运行 pytest，结果 14 passed。确切提交 ID 与远程交付状态以 Git 历史、推送结果及远程 refs 核验为准。
- 本轮仅交付已有阶段成果；依赖管理理解题尚未回答，阶段 0 不据 Git 操作自动标记为学习验收完成，阶段 2–7 未开始。

### 2026-10-20：阶段 2 第 1 步（任务表模型）

- 用户要求环境知识不作为教学重点并进入下一阶段；按该偏好推进，不以尚未回答依赖理解题阻塞阶段 2。
- 调研：[SQLAlchemy 官方仓库](https://github.com/sqlalchemy/sqlalchemy)与 [ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)、[Psycopg 官方示例](https://www.psycopg.org/psycopg3/docs/basic/usage.html)、[SQLModel 官方仓库](https://github.com/fastapi/sqlmodel)。SQLAlchemy/SQLModel 为 MIT，Psycopg 为 LGPL；均有官方文档和维护版本。
- 比较：Psycopg 直接执行 SQL、依赖层较少但需手动映射；SQLModel 依赖 SQLAlchemy/Pydantic、模型写法简洁但多一层封装；选择 SQLAlchemy 原生映射与 Session 事务，便于后续 PostgreSQL 和迁移。未复制第三方代码。
- 依赖：采用仍有维护更新且与本轮官方 2.0 文档一致的 SQLAlchemy 2.0.55（2026-10-16 版本）；已知当前另有 2.1 系列，本次未使用旧式 Query API。
- 新增 `database_models.py`：Base 与 TaskRecord，先映射 task_id 主键、非空 prompt、非空 status 与 ORM 插入默认 PENDING；这不是完整阶段 2 表结构，owner_id、时间戳、result_ref、error 后续小步补充。
- 新增 `test_database_models.py`：用 pytest 临时目录中的 SQLite 文件验证提交后重建 Engine 读取、flush 后回滚、重复主键失败且原记录不变；每个用例独立建表，结束释放连接。SQLite 只作本轮测试，不替代 PostgreSQL 验收。
- 当前 PATH 未发现 psql/postgres/pg_ctl/docker；本轮未安装数据库服务，不据此声称没有其他远程数据库。API、Swagger 和原内存任务行为保持原样；没有迁移、数据库注入、鉴权或用户隔离。
- 表约束目前只有主键及非空；数据库层尚未约束空白 prompt 或状态集合，不能把 Pydantic 校验误认为 ORM 自动提供的校验。`create_all` 仅用于测试建表，不是正式迁移机制。
- 验证：`.venv/bin/python -m pytest -q` 为 17 passed（原 API 14 个、新数据库行为 3 个）；pip check 无依赖冲突，git diff --check 通过。没有执行 PostgreSQL 测试或应用服务重启后的持久化验收。
- 本轮学习点：对象与表/行的映射、主键、Session 的 add/commit/flush/rollback。等待理解题反馈后继续接入数据库，不要求学习者手写代码。

### 2026-10-20：连续交付模式与完整 MVP 实现

- 用户取消理解题和测试讲解，要求优先完成项目；已同步 AGENTS.md 与本路线图，不再等待逐题反馈。真实模型供应商选择 OpenAI。
- 完成持久化 API 与身份隔离：Task 表含 owner_id、状态、UTC Unix 时间、结果引用、错误、尝试次数、租约及 trace_id；Alembic 0001 管理业务表，PostgresSaver.setup 在迁移步骤初始化官方检查点表。测试验证重复迁移安全。
- 认证分开发身份 X-Dev-User（明确可伪造、仅本地）与配置式 Bearer Token；Token 模式忽略开发身份头。创建、列表、查询、事件、版本、预览、编辑、恢复、确认、重试、导出和指标按 owner 限定，跨用户资源返回 404。
- 采用 PostgreSQL 任务表作为可靠队列，替代当前规模下的 Redis/Celery，入队与任务创建同事务；每用户及全局 admission 锁保护幂等、配额和队列容量，数据库唯一约束提供额外保证。未复制第三方队列实现。
- 独立 Worker 使用 FOR UPDATE SKIP LOCKED、条件更新、lease_token 和到期时间领取/写回，支持有限重试、指数退避、崩溃租约恢复、部分节点续跑和数据库暂时中断后的轮询恢复。旧 Worker 无法发布已过期结果。
- LangGraph 采用 Brief 解析 → 3 个独立图片工具节点 → interrupt 人工确认 → Command(resume) 的受控工作流。使用 SqliteSaver/PostgresSaver；确认恢复和第二张图故障恢复均有测试，不用内存 checkpointer 冒充持久化。
- 创意功能：本地 HTML/JS Studio、3 个候选、PNG 预览、不可变版本、title/price 白名单修改、恢复旧版副本、重复确认幂等、确认成功后 PNG/SVG/JSON 导出。图片内容地址存储，修改价格保持 image_ref 不变；SVG 文本转义，资产路径受限，PNG 支持 CJK 字体与标题换行。没有任意扁平图 inpainting。
- OpenAI 适配器使用官方 SDK 的 Responses 结构化输出和 Images API；模型名从环境配置，SDK max_retries=0，文本 store=False。供应商异常先清理再进入图检查点，日志/对外错误不保存原始供应商错误正文。未配置 Key 时不会自动用 mock 冒充成功。
- 真实生成失败/结果未知时不自动重复计费；人工 retry 需要明确 acknowledge_possible_duplicate_charge。任何外部模型调用与检查点之间仍存在副作用窗口，不承诺 exactly-once 或绝不重复计费。
- 观测：请求 X-Trace-ID、持久 task trace_id、节点/工具阶段、耗时、模型、模拟标记和可用 usage；按用户提供 P50/P95、任务状态及调用计数。无真实账单时费用字段为 null。
- 验证：SQLite + 原生 PostgreSQL 16 双后端回归 87 passed；独立 API/Worker 进程脚本在 SQLite 与 PostgreSQL 上均通过，验证 API 重启后任务仍存在，并能确认/导出 PNG。数据库故障、Worker 失效、幂等并发、容量并发及越权有专门回归。
- evals/cases.json 含 40 个模拟功能案例，最新一轮 40/40 通过；端到端 P50 190.38ms、P95 226.44ms，仅为本机 SQLite/mock 记录，不代表真实模型质量、生产延迟或账单。
- evals/checkpoint_comparison.json 是控制实验：朴素“确认时重新生成三张图”实验基线为 3 次/101.15ms，实际持久确认恢复为 0 次/15.14ms。该基线是对照实验，不是已有线上版本的历史数据；不推算真实 API 费用。
- 交付：README、架构与来源记录、作品集描述/3 个故障案例、40 案例评测、真实进程 smoke、部署 smoke、浏览器 smoke、Dockerfile/Compose、GitHub Actions。requirements-runtime.lock 锁定 Linux/Python 3.12 运行依赖闭包，暂未添加哈希。
- Docker Compose 已实际构建并启动 PostgreSQL/API/Worker，API 与 DB 健康；容器内完整创建→候选→价格编辑→确认→PNG 导出通过；重启 API 后已完成任务保留，重启 PostgreSQL 后仍能处理新任务。构建验证复用了本机缓存的发行包和镜像源，不引入仓库外业务代码。
- 本机 .env/data/compose.env、数据库、图片、浏览器缓存及安装包不提交 Git；数据库口令随机生成。当前公开接口仅绑定本机地址，默认 mock + 开发身份。
- 浏览器验证：使用 Linux Headless Chrome 实际完成提交、3 个候选预览、价格修改、确认、PNG 下载及刷新后同身份查询，未发现 JavaScript 错误。截图和下载产物保存在被忽略的 data/，不把界面测试误记为真实图像生成。
- 剩余真实验收：OpenAI Key/账户模型权限、真实创意质量与账单评测、线上负载/部署、录屏与长期监控；不能将这些项标记完成。凭据随后已配置，真实文本解析通过、图片供应商返回 500；用户选择先交付，图像服务稍后配置。Git 交付结果以提交和远程 refs 核验为准。

### 2026-10-20：最终浏览器与容器验证

- Linux Headless Chrome 真实浏览器回归通过：页面提交 → 三个候选 → 价格保存为新版本 → 人工确认 → SUCCESS → 下载有效 PNG；没有 JavaScript 错误。浏览器工具安装遇到下载缓慢后，使用与官方发行包校验值一致的镜像包验证，没有修改浏览器安全策略。
- 容器 API /ready 为 200，PostgreSQL 与 API 均 healthy，Worker 正常运行。已验证 API 容器重启后完成任务仍可查询；数据库容器重启后仍可完成新任务生成、编辑、确认和导出。
- 本地演示入口为 http://127.0.0.1:8002/，默认 mock + dev 身份；不需要真实 Key 即可验收工程链路，仍不能据此验收真实模型输出。

### 2026-10-20：真实供应商验证与交付决定

- 检测到本机配置凭据后，以公开合成的咖啡杯 Brief 执行真实验证，没有发送私人业务内容。
- 配置的 OpenAI 兼容服务、文本模型 gpt-6.1-sol 接受 Responses 结构化输出，Pydantic Brief 解析成功；第一张 gpt-image-1 图片请求返回 InternalServerError（HTTP 500），任务按设计 FAILED。
- 图片未自动重试，未静默替换 mock；只读模型列表未列出图像模型，但不据此断言供应商一定不支持图片。需要后续确认可用 Images API/模型配置。
- 用户明确选择“图像服务稍后配置，先交付”。因此继续使用 mock 演示，不将真实图片质量或整个路线图标记完成。
- evals/openai-smoke.json 保存脱敏验证摘要、可用文本 token 数和失败类型；不包含凭据、供应商主机地址或原始错误正文，账单费用仍为 null。
