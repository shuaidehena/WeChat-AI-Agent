# Docker 部署教程（一步一步学）

## 先理解：为什么不能把整个项目丢进 Docker？

你的项目核心能力是：

| 能力 | 依赖 | Docker Linux 容器 |
|------|------|-------------------|
| 控制微信窗口 | pywinauto / pygetwindow | ❌ 不行 |
| 截图 + OCR | pyautogui + 屏幕 | ❌ 不行（无 GUI） |
| 模拟键鼠发消息 | pyautogui | ❌ 不行 |
| 调用 DeepSeek API | HTTP | ✅ 可以 |

**结论：微信 Agent 必须跑在 Windows 宿主机；只有 API/网关类服务适合 Docker。**

本方案采用 **混合部署**：

```
┌─────────────────────────────────────────────┐
│  Windows 宿主机（你的电脑）                    │
│  ┌─────────────────────────────────────┐   │
│  │  python main.py  ← 微信 OCR/回复     │   │
│  └──────────────┬──────────────────────┘   │
│                 │ HTTP (可选)               │
│  ┌──────────────▼──────────────────────┐   │
│  │  Docker: llm-gateway :8000          │   │
│  │  (DeepSeek API 代理)                 │   │
│  └──────────────┬──────────────────────┘   │
└─────────────────┼───────────────────────────┘
                  ▼
           DeepSeek 云端 API
```

---

## 第 0 步：准备环境

1. 安装 **Docker Desktop for Windows**  
   https://www.docker.com/products/docker-desktop/

2. 安装后打开 Docker Desktop，等右下角图标变绿（Engine running）

3. 验证：

```powershell
docker --version
docker compose version
```

4. 配置 API Key（项目根目录）：

```powershell
copy docker\.env.example .env
notepad .env   # 填入 DEEPSEEK_API_KEY=sk-xxxx
```

---

## 第 1 步：理解 Dockerfile 是什么

Dockerfile = **镜像构建说明书**，告诉 Docker 如何打包你的程序。

打开 `docker/llm-gateway/Dockerfile`，逐行理解：

```dockerfile
FROM python:3.10-slim          # 基础镜像：自带 Python 的迷你 Linux
WORKDIR /app                   # 容器内工作目录
COPY requirements.txt .        # 复制依赖清单
RUN pip install ...            # 安装依赖（构建时执行一次）
COPY app.py .                  # 复制程序代码
EXPOSE 8000                    # 声明端口（文档作用）
HEALTHCHECK ...                # 健康检查：容器是否存活
CMD ["uvicorn", ...]           # 容器启动时执行的命令
```

**关键概念：**

- **镜像 (Image)**：只读模板，类似「安装包」
- **容器 (Container)**：镜像的运行实例，类似「正在运行的程序」
- **层 (Layer)**：每条指令产生一层，改代码重建时只重建后面几层（快）

---

## 第 2 步：手动构建第一个镜像（学习用）

在项目根目录执行：

```powershell
cd docker\llm-gateway
docker build -t wechat-llm-gateway:1.0 .
```

解释：

- `docker build` — 根据 Dockerfile 构建
- `-t wechat-llm-gateway:1.0` — 给镜像打标签（名字:版本）
- `.` — 构建上下文目录（当前目录）

成功会看到 `Successfully tagged wechat-llm-gateway:1.0`

查看镜像：

```powershell
docker images
```

---

## 第 3 步：手动运行容器（学习用）

```powershell
docker run -d `
  --name llm-test `
  -p 127.0.0.1:8000:8000 `
  -e DEEPSEEK_API_KEY=sk-你的key `
  -e DEEPSEEK_BASE_URL=https://api.deepseek.com `
  -e LLM_GATEWAY_TOKEN=至少32字节随机令牌 `
  wechat-llm-gateway:1.0
```

参数说明：

| 参数 | 含义 |
|------|------|
| `-d` | 后台运行 |
| `--name llm-test` | 容器名称 |
| `-p 8000:8000` | 宿主机端口:容器端口 |
| `-e KEY=VAL` | 环境变量 |

测试：

```powershell
curl http://localhost:8000/health
```

浏览器打开 http://localhost:8000/health 应看到 `{"status":"ok",...}`

停止并删除练习容器：

```powershell
docker stop llm-test
docker rm llm-test
```

---

## 第 4 步：用 docker-compose 一键启动（推荐）

`docker-compose.yml` = **多容器编排清单**。目前只有一个服务，但以后可以加 Redis、数据库等。

```powershell
cd docker
docker compose up -d --build
```

| 命令 | 作用 |
|------|------|
| `docker compose up` | 启动 compose 里所有服务 |
| `-d` | 后台运行 |
| `--build` | 启动前重新构建镜像 |

常用管理命令：

```powershell
docker compose ps          # 查看状态
docker compose logs -f     # 看日志
docker compose down        # 停止并删除容器
docker compose restart     # 重启
```

---

## 第 5 步：Windows 一键部署（完整流程）

回到项目根目录：

```powershell
# 方式 A：网关 + Agent 一起启动（Agent 直连 DeepSeek）
.\scripts\deploy.ps1

# 方式 B：Agent 走 Docker 网关（学习 HTTP 解耦）
.\scripts\deploy.ps1 -UseGateway

# 方式 C：只启动 Docker 网关
.\scripts\deploy.ps1 -GatewayOnly
```

`deploy.ps1` 做了三件事：

1. 检查 `.env` 是否存在  
2. `docker compose up` 启动 LLM 网关  
3. `python main.py --send` 在 Windows 上启动微信 Agent  

---

## 第 6 步：验证 Agent 走网关（可选实验）

1. 确保网关运行：`curl http://localhost:8000/health`

2. 修改 `.env`：

```env
LLM_BASE_URL=http://localhost:8000
LLM_GATEWAY_TOKEN=与网关一致的随机令牌
```

3. 或用脚本：`.\scripts\deploy.ps1 -UseGateway`

4. 启动 Agent，观察日志里 DeepSeek 调用是否正常

数据流变为：

```
Agent → localhost:8000 (Docker) → api.deepseek.com
```

好处：API Key 可以只放在 Docker 里，Agent 不直接接触密钥（进阶安全）。

---

## 第 7 步：常用 Docker 命令速查

```powershell
# 镜像
docker images                    # 列出镜像
docker rmi 镜像名                 # 删除镜像

# 容器
docker ps                        # 运行中的容器
docker ps -a                     # 所有容器
docker logs 容器名 -f             # 看日志
docker exec -it 容器名 bash       # 进入容器 shell

# 清理
docker system prune -f           # 清理无用资源
```

---

## 目录结构

```
docker/
├── docker-compose.yml      # 编排文件
├── .env.example            # 环境变量模板
├── README.md               # 本教程
└── llm-gateway/
    ├── Dockerfile          # 镜像构建
    ├── app.py              # FastAPI 网关
    └── requirements.txt    # 容器内 Python 依赖

scripts/
└── deploy.ps1              # Windows 一键部署脚本
```

---

## 进阶：如果未来想「更多服务进 Docker」

可以逐步拆分：

| 阶段 | 做法 |
|------|------|
| 现在 | Agent 在 Windows，LLM 网关可选 Docker |
| 下一步 | 记忆检索 / 向量库做成 HTTP 服务放 Docker |
| 再下一步 | Agent 瘦身为纯客户端，只负责 OCR + 发消息 |
| 很难 | 微信本身进容器（需 Windows 容器 + GUI，成本极高，不推荐） |

---

## 常见问题

**Q: `docker compose up` 报错 port already in use**  
A: 8000 端口被占用，改 `.env` 里 `LLM_GATEWAY_PORT=8001`，同步改 Agent 的 `LLM_BASE_URL`

**Q: 构建很慢**  
A: 首次需下载 Python 基础镜像，已配置清华 pip 源加速

**Q: Agent 能在 Docker 里跑吗**  
A: 不能（Linux 容器无 Windows 微信 GUI）。除非改用 Android 微信 + 完全不同技术栈

**Q: 生产环境怎么部署**  
A: 网关容器放云服务器；Agent 仍在你有微信登录的 Windows 机器上，通过内网/HTTPS 调云端网关
