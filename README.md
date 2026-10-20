# Shopee Creative Agent

面向电商营销的可运行后端 MVP：提交 Brief → 独立 Worker → LangGraph 解析与生成
→ 3 个海报候选 → 选择/编辑/恢复版本 → 人工确认 → PNG / SVG / JSON 导出。

默认配置保留 **mock 模拟生成**，图片带 SIMULATED 标记；本机真实模式使用 OpenAI 兼容文本服务和硅基流动图片服务。
用户已确认部署更新后的真实图片生成验证通过；创意质量的量化评测和费用仍未验收。
`evals/openai-smoke.json` 保留早期 gpt-image-1 请求返回 500 的历史记录，不代表当前硅基流动验证结果。

## 实际完成范围

- SQLAlchemy + Alembic；支持 PostgreSQL 16 和本地 SQLite；任务跨 API 重启保存。
- 开发身份与 Bearer Token 两种模式；任务、版本、预览、事件、导出按用户隔离。
- 数据库可靠队列；独立 Worker；幂等键、容量限制、用户配额、租约与故障恢复。
- 持久化 LangGraph 检查点；人工中断确认；恢复确认流程不重新生成图片。
- 不可变作品版本；仅允许修改 title/price，图片引用不变；可恢复旧版。
- 请求/任务 Trace、审计事件、延迟分位数、调用 usage 记录；无账单时费用返回 null。
- 40 个模拟功能评测案例；真实 HTTP/进程重启演示脚本；Docker Compose 与 CI 配置。

真实开发证据和未完成项见 [路线图](Shopee_AI_Agent.md)，架构取舍见 [设计记录](docs/architecture.md)，
演示与项目描述见 [作品集说明](docs/portfolio.md)。
本项目不对接 Shopee 内部系统，不宣称已达到公开生产服务要求。

## 本地启动

Python 3.12，WSL/Linux。命令均在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m database
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8002
```

另一个终端启动 Worker（同一目录与同一配置）：

```bash
.venv/bin/python -m worker
```

浏览器打开 http://127.0.0.1:8002/ 使用本地操作界面，或访问 `/docs` 使用 Swagger。默认 AUTH_MODE=dev，填写每个接口的
`X-Dev-User`（例如 alice）。**这是可伪造的测试身份，仅限本地演示。**
默认文件为 data/agent.db、data/checkpoints.db、data/assets/，均不提交 Git。
若端口占用，换端口即可；旧的内存版进程不会因文件变更自动更新，请重启新版服务。

### PostgreSQL

在已有数据库和账户的情况下，API、Worker、迁移命令统一配置：

```bash
export DATABASE_URL='postgresql+psycopg:///shopee_agent'
.venv/bin/python -m database
```

此示例使用本机 Unix socket 和 peer 身份认证，数据库及同名角色需事先创建；
远程连接使用有权限的账户与环境变量，不要把带密码的 URL 提交到仓库。
PostgreSQL 模式的 LangGraph 检查点也存入同一数据库。时间字段使用 UTC Unix 秒。
`python -m database` 执行 Alembic 迁移，可重复运行；不是每次启动时重建表。

### OpenAI 真实生成

按 `.env.example` 配置项目根目录 `.env`；本地启动会加载该文件，已存在的进程环境变量优先。
也支持通过进程管理器或 Docker Compose 注入。不要在聊天或仓库中填写真实 Key。

```bash
export PROVIDER=openai
export OPENAI_TEXT_MODEL=gpt-4.1-mini
export OPENAI_IMAGE_MODEL=gpt-image-1
# 在本机安全设置 OPENAI_API_KEY，然后重新启动 API 与 Worker。
```

文本使用 Responses 的 Pydantic 结构化输出，图片使用 Images API，每任务 3 张背景图。
模型名可替换为账户已授权的兼容模型；实际权限、配额、价格需以账户为准。
图片可单独使用硅基流动：设置 `IMAGE_PROVIDER=siliconflow`、`IMAGE_API_KEY`、
`IMAGE_BASE_URL=https://api.siliconflow.cn/v1` 和 `OPENAI_IMAGE_MODEL=Kwai-Kolors/Kolors`。
文本仍使用原来的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_TEXT_MODEL`。
图片下载仅允许硅基流动或阿里云 HTTPS 地址，单张上限 20 MiB。
SDK 自动重试被禁用；真实生成出现异常或 Worker 租约过期时不会静默重复调用，
任务转 FAILED，外部请求是否已执行/计费可能未知。不会静默切换 mock 冒充真实结果。
价格和标题使用独立图层；不承诺扁平图片任意局部编辑。

### Token 身份模式

设置 `AUTH_MODE=token`，`API_TOKENS_JSON` 为“用户 ID → 随机长 Token”的 JSON 对象，
Token 至少 24 字符。由你在本地生成并通过环境变量注入，不要使用示例占位值。
请求携带 `Authorization: Bearer <token>`。此模式忽略 X-Dev-User。
这是受控演示使用的静态 API Token 方案，尚无注册登录、Token 轮换或 OAuth/OIDC。

## 完整操作链路

1. `POST /tasks` 提交 `{"prompt":"运动鞋促销海报，售价 99，简洁风格"}`。
   可设置 `Idempotency-Key`，首次 201，同用户同键同内容重放为 200，换内容为 409。
2. `GET /tasks/{task_id}` 轮询。Worker 将 PENDING → RUNNING → WAITING_APPROVAL。
3. `GET /tasks/{task_id}/versions` 查看三个候选；各版本的 `/preview` 返回 PNG。
4. `PATCH /tasks/{task_id}/versions/{version_id}` 提交 `{"price":"79"}`，创建新版本；
   原版本不变，只修改文字字段，图片引用不变。`POST .../restore` 从旧版再创建副本。
5. `POST /tasks/{task_id}/approve` 提交 `{"version_id":"选中的 UUID"}`。
6. Worker 从持久化中断点继续，状态变为 SUCCESS 后，通过
   `GET /tasks/{task_id}/export?format=png` 导出；还支持 svg 和 json。
7. `/tasks/{task_id}/events` 查看任务事件；`/metrics` 查看当前用户的观测数据。

初始任务没有 result，生成候选后 result 含结构化 brief 和 simulated 标记。
FAILED 任务有经过清理的 error 类型；不向客户端暴露供应商原始错误正文。
`POST /tasks/{task_id}/retry` 可人工重试；真实模型任务必须在请求体中显式设置
`acknowledge_possible_duplicate_charge=true`，确认可能再次计费。

| 状态码 | 含义 |
|---|---|
| 200 / 201 | 查询/重放成功；首次资源创建成功 |
| 401 / 404 | 缺少身份；资源不存在或不属于当前用户 |
| 409 / 422 | 状态/幂等冲突；字段校验失败 |
| 429 / 503 | 用户提交配额耗尽；队列满或数据库未就绪 |

配额针对创建任务：滚动一分钟 20 个、24 小时 100 个；全局待执行/运行任务最多 100。
幂等重放不消耗新任务配额。确认和编辑不调用模型。限制可用环境变量调整。
`/health` 仅检查进程，`/ready` 检查业务表可访问；两者不证明 Worker 正常或模型账户可用。

## 验证

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke
.venv/bin/python -m evals.run
.venv/bin/python -m scripts.benchmark_checkpoint
```

PostgreSQL 双后端回归（测试账户须能创建 schema；只使用专用测试数据库）：

```bash
TEST_DATABASE_URL='postgresql+psycopg:///shopee_agent_test' .venv/bin/python -m pytest -q
```

测试在唯一临时 schema 中运行，结束后清理该 schema，不清空已有业务表。
`smoke` 启动独立 API 与 Worker，验证 API 重启后可查询，并最终导出 PNG。
`evals/latest.json` 是本机 mock 功能数据，**不是模型质量、生产延迟或真实账单数据**。

## Docker Compose

在 `.env` 中安全设置 `POSTGRES_PASSWORD`（用 URL 安全字符生成的随机值），随后：

```bash
docker compose up --build
```

API 映射到 http://127.0.0.1:8002 ，依次启动 PostgreSQL、迁移、API 与 Worker，
数据库和资产使用持久卷。默认开发身份仅允许本机访问；公开部署前必须启用 token 或
更完整的身份系统、HTTPS、网关限流，并设置备份与数据保留策略。
`docker compose down` 停止服务；不要随意添加 `-v`，该选项会删除持久卷。

## 主要文件

| 文件 | 职责 |
|---|---|
| main.py / schemas.py / auth.py | HTTP 接口、输入输出与身份验证 |
| database_models.py / migrations/ | 表结构、约束和版本迁移 |
| service.py | 用户隔离、幂等、配额、版本和任务状态 |
| worker.py / workflow.py | 独立执行、领取恢复、LangGraph 与人工确认 |
| providers.py / storage.py | 模拟/OpenAI 适配、图片存储和导出 |
| tests/、test_main.py | 故障、并发、隔离和接口回归 |
| scripts/smoke.py / evals/ | 真实进程演示与模拟功能评测 |

requirements.txt 声明直接依赖，requirements-runtime.lock 固定 Linux/Python 3.12 的运行依赖闭包，
开发安装通过约束文件复用它；尚未添加分发包哈希，也不承诺其他平台二进制兼容。日志不记录 Token、Key 或原始 prompt；
数据库、检查点和资产仍含业务内容，部署者需控制存储访问及保留时间。

可选浏览器回归（在运行本地 mock 服务时执行）：

```bash
npm install --prefix data/browser-tests playwright@1.64.0
node data/browser-tests/node_modules/playwright/cli.js install --with-deps chromium
NODE_PATH="$PWD/data/browser-tests/node_modules" node scripts/browser_smoke.cjs
```

默认验证 8002 端口；可用 STUDIO_URL 覆盖。浏览器依赖和截图均保存在忽略目录，
不属于服务运行依赖。脚本会提交模拟任务，修改价格、确认并下载 PNG。

若使用本次已启动的 `shopee-agent-demo` 演示，数据库凭据位于忽略文件
`data/compose.env`。在根目录 `.env` 设置 `OPENAI_API_KEY` 和 `PROVIDER=openai` 后，
可保留原数据库配置并更新服务：

```bash
docker compose --env-file data/compose.env --env-file .env -p shopee-agent-demo up -d
```

重新打开已配置真实模型的项目时，也应使用上面这条双配置文件命令。
只指定 `--env-file data/compose.env` 会继续使用原先的 mock 演示配置，不会读取根目录 `.env` 中的模型设置。
修改 Python 代码或新增供应商适配后，在命令中加上 `--build` 重建镜像；只重启旧容器不会更新代码。
可访问 `/ready` 检查当前生成模式。任务保留创建时的 provider，切换配置后请新建任务验证，旧的 mock 任务不会自动变成真实生成。

本机 Docker 若要求权限，使用具有 Docker 权限的账户或按本机配置运行该命令。
更换 PROVIDER 只影响新创建的任务；旧任务按其创建时的供应商模式处理。
