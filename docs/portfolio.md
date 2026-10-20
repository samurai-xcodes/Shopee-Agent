# 作品集说明与演示脚本

## 可验证的项目描述

开发电商创意 Agent 后端 MVP，使用 FastAPI、PostgreSQL、SQLAlchemy/Alembic 和 LangGraph。
实现任务持久化、用户隔离、请求幂等、数据库任务队列、Worker 租约恢复、持久化人工确认、
作品版本编辑/恢复与 PNG/SVG 导出。接入 OpenAI 官方 SDK 适配器，默认提供明确标记的模拟模式。

自动化回归覆盖 SQLite 与真实 PostgreSQL；本机 40 个模拟功能案例通过。
真实兼容服务的结构化文本解析已验证，图片请求返回 500，图像服务由用户选择后续配置。
真实图像质量、调用成本、线上吞吐量尚未验证，不将这些数据写为已有成果。

## 三分钟演示

1. 打开本地 Studio，说明当前使用 mock、身份为开发身份。
2. 输入商品、价格、风格，提交任务；说明浏览器没有直接调用模型。
3. 展示 Worker 执行后出现三个候选与 WAITING_APPROVAL。
4. 修改一个版本的价格，展示原版与新版图片引用一致、原版仍可查看。
5. 确认版本，状态变为 SUCCESS，下载 PNG。
6. 重启 API，展示任务仍存在；通过事件接口查看生成和确认轨迹。
7. 说明生产模式用 PostgreSQL 与 token/OIDC，真实生成需要独立 Key 和模型权限。

## 三个故障案例（测试注入，不是线上事故）

### Worker 领取后崩溃

测试将 RUNNING 租约置为过期；下次扫描按次数上限重排或置 FAILED。
旧 lease_token 写回被拒绝，防止旧执行覆盖新结果。真实模型调用结果未知时停止自动重试。
证据：test_expired_claim_retries_and_fences_old_worker、test_unknown_openai_outcome_not_automatically_retried。

### 客户端重复提交

同用户、同幂等键与同内容返回同一 task_id；不同内容返回 409。
并发情况下由数据库用户锁和唯一约束保护，避免只在 Python 进程内判断。
证据：test_idempotency、test_concurrent_idempotency_has_one_task。

### 确认时进程已重启

候选生成后，检查点已持久保存到人工中断节点。
批准后新执行从 Command(resume) 继续，注入“任何模型调用都报错”的供应商仍能完成。
证据：test_checkpoint_resume_does_not_regenerate。这个测试也运行在 PostgreSQL 上。

## 设计比较数据

见 evals/checkpoint_comparison.json：在本机 mock 控制实验中，对比“确认时重新生成三张图”的
朴素实验基线与实际检查点恢复，图片调用数 3 → 0。
这不是历史线上版本的性能提升记录，也不代表真实 API 延迟或费用；真实付费收益待测。

## 仍需补充的交付

- 配置真实 OpenAI 凭据和已授权模型，验证实际海报质量、usage 和费用。
- 真实案例评测与规则/视觉质量评估，不能用 mock pass rate 替代。
- 按需录屏、选择部署环境、配置 HTTPS/OIDC/备份/监控及留存策略。
