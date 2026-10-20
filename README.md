# Shopee AI Agent

面向电商创意 Agent 的后端学习项目。目前已验收阶段 1：FastAPI 内存任务管理接口。
完整开发与学习计划见 [Shopee_AI_Agent.md](Shopee_AI_Agent.md)。

## 当前能力与限制

| 接口 | 用途 | 成功状态码 |
|---|---|---|
| `GET /health` | 检查应用是否能响应 | 200 |
| `POST /tasks` | 提交 prompt，创建 UUID 任务 | 201 |
| `GET /tasks/{task_id}` | 查询任务 | 200 |

- prompt 必须是字符串，去掉首尾空白后不能为空；无效输入返回 422。
- UUID 格式错误返回 422；格式正确但任务不存在返回 404。
- 任务只保存在当前进程内存中，重启会丢失；不同服务进程不共享任务。
- 状态目前只有 `PENDING`，没有 Worker、模型调用、数据库或鉴权，不用于公开生产服务。
- HTTP 201 表示任务记录创建成功，不代表创意作品已生成。

## 安装（WSL Ubuntu）

已验证的 Python 版本为 3.12.3。以下命令在项目根目录执行：

```bash
cd /home/wangjinwei/projects/shopee-agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
```

若已有 `.venv`，跳过创建步骤即可。若系统提示缺少 venv/ensurepip，先为当前
Python 安装 Ubuntu 对应的 venv 支持包，再创建虚拟环境。

`requirements.txt` 列出运行所需包；`requirements-dev.txt` 包含运行依赖及测试工具。
这里固定了直接依赖版本，间接依赖仍由 pip 解析，因此不是完整的依赖锁文件。
只运行服务时，可改为安装 `requirements.txt`。不需要模型 API Key。

## 启动

```bash
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

`main:app` 表示加载 `main.py` 中的 `app` 对象。保持该终端运行，浏览器打开：

- 健康检查：http://127.0.0.1:8001/health
- Swagger：http://127.0.0.1:8001/docs

按 `Ctrl+C` 停止服务。若出现 `address already in use`，换一个空闲端口并同步修改
浏览器地址。不要启动多个进程来测试当前的内存任务查询。

## 手动验证

1. Swagger 展开 `POST /tasks`，点击 **Try it out**，填写以下 JSON 后点击 **Execute**：

   ```json
   {"prompt": "制作一张运动鞋促销海报"}
   ```

2. 在 **Server response** 确认实际返回 201，复制响应中的 `task_id`。
3. 在 `GET /tasks/{task_id}` 中点击 **Try it out**，填写 ID 并执行；应返回 200，
   ID、prompt 与创建时一致，状态为 `PENDING`。
4. 提交 `{"prompt": "   "}` 应返回 422；查询 `not-a-uuid` 应返回 422。
5. 查询 `00000000-0000-4000-8000-000000000000`（未创建的合法 UUID）应返回 404。
6. 停止并重新启动服务，再查之前创建的 ID 应返回 404；这是内存存储的已知限制。

## 自动化测试

无需先启动服务。在项目根目录运行：

```bash
.venv/bin/python -m pytest -q
```

查看每个用例，或只运行一个测试：

```bash
.venv/bin/python -m pytest -v
.venv/bin/python -m pytest -v test_main.py::test_create_task
```

现有 14 个用例覆盖健康检查、创建与查询、输入校验、未知 ID、重复提交。
`TestClient` 在进程内调用应用；fixture 在每个用例前后清空任务，避免测试相互影响。
这些测试不替代浏览器交互和真实服务重启实验。

## 文件说明

- `main.py`：请求/响应模型、内存存储和三个接口。
- `test_main.py`：pytest 接口测试和数据隔离 fixture。
- `requirements.txt` / `requirements-dev.txt`：运行与开发依赖。
- `AGENTS.md`：项目开发与教学约定。
- `Shopee_AI_Agent.md`：路线图、真实进度和验收记录。

虚拟环境、缓存和 `.env` 已在 `.gitignore` 中排除，不要提交密钥。
