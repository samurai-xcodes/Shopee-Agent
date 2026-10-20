# 架构与技术决策

## 实际数据流

HTTP 客户端 → FastAPI 身份/校验 → SQLAlchemy 事务提交任务 → 数据库队列表。
独立 Worker 领取租约 → LangGraph 结构化 Brief → 三个图片节点 → 持久化 interrupt。
候选存为不可变版本 → 用户文字编辑/选择 → 批准事务重新排队 → Command(resume) → SUCCESS → 导出。

这是一条受控 Agent 工作流，不是让模型自由执行代码或访问任意工具的通用 Agent。
模型只能解析 Brief 与生成背景图，不决定 owner、文件路径、任务状态或导出授权。

## 选择及取舍

| 方案 | 评价与取舍 |
|---|---|
| SQLAlchemy + Alembic + Psycopg | ORM、迁移与 PostgreSQL 驱动职责清晰；没有手写 ORM/迁移框架 |
| SQLModel | 同样成熟，但再封装 Pydantic/SQLAlchemy；本项目保留请求模型与数据库模型的边界 |
| Redis + Celery/RQ | 有成熟调度生态，但增加服务与数据库/队列双写一致性问题；当前无需其完整能力 |
| PostgreSQL 任务队列（当前） | 入队就是任务事务，无“入库成功但投递失败”；FOR UPDATE SKIP LOCKED 支持并发领取 |
| LangGraph | 复用 StateGraph、interrupt、Command、PostgresSaver/SqliteSaver，无自造图引擎 |
| 独立文字图层 | 改价格不重新生成图片，可验证图片引用与字节保持；不能支持任意扁平图编辑 |
| 静态 Bearer Token | 演示与受控环境可用；不等同完整用户系统，公开部署需补 OAuth/OIDC/轮换 |

SQLAlchemy/Alembic、LangGraph 使用 MIT，Psycopg 使用 LGPL，OpenAI SDK 使用 Apache-2.0，
Pillow 使用 HPND；使用库接口而未直接复制仓库实现。版本见 requirements.txt。

## 一致性与故障

- owner + idempotency_key 唯一约束。同键不同 prompt/provider 返回 409。
- 每用户数据库锁序列化配额与幂等判断；全局 admission 锁保证容量判定不会并发穿透。
- Worker 用领取时生成的 lease_token 作为写回条件，租约过期/被接管后旧 Worker 不能发布结果。
- RUNNING 超时由 Worker 下一轮扫描恢复；mock 可有限重试，指数退避最长 60 秒。
- OpenAI 请求结果未知时不自动重试；SDK 内部重试为 0，避免无提示重复计费。
- 检查点与业务状态不是同一事务：若图已暂停而业务候选尚未入库，重领时从检查点读取，再幂等发布。
- 每张候选单独成为图节点；已完成的节点不会因确认/后续节点恢复而重跑。
- 最后一次外部副作用与检查点写入之间仍有崩溃窗口，不能承诺外部调用 exactly-once。
- 同步供应商请求有网络超时，节点检查执行预算；租约/条件更新保证结果不会无限挂在 RUNNING。
  这不是杀死供应商远端请求的硬实时保证，远端可能继续执行或计费。

## 可观测性与隐私

任务有持久 trace_id，HTTP 响应有独立 X-Trace-ID；事件记录节点阶段、耗时、模型、模拟标记、
供应商返回的 usage（如果有），不记录原始错误正文或凭据。模型 usage 不等同真实账单，费用未知为 null。
请求延迟指标取当前用户最近 1000 次请求；任务状态计数/完成调用数为当前用户累计值。
部署需定期归档/清理请求指标和旧检查点，当前未实现自动保留调度。

## 已知边界

提供原生 HTML/JS 本地 Studio 和 Swagger；没有 React 构建链。没有任意 inpainting、对象存储、注册登录、
真实模型质量评测、账单对账、跨区域部署或线上压测。
SQLite 只适合本地低并发；正式多 Worker 部署选择 PostgreSQL。
Worker 退出后恢复扫描也会暂停，需进程监控；/ready 不代表 Worker 或模型健康。
数据库迁移步骤调用 PostgresSaver.setup 创建其官方检查点表；Worker 只读写检查点，避免多 Worker 首次执行时竞争建表。
升级其依赖时需按上游迁移说明评估。

## 参考来源

- https://docs.sqlalchemy.org/en/20/orm/quickstart.html
- https://docs.sqlalchemy.org/en/20/core/selectable.html
- https://alembic.sqlalchemy.org/en/latest/tutorial.html
- https://www.psycopg.org/psycopg3/docs/basic/usage.html
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/image-generation
