# WeChat AI Agent

基于 Python 的 Windows 微信自动化 AI 助手。

通过 **截图 OCR + 模拟键鼠** 读取微信消息，调用 **多模型 LLM** 生成符合个人风格的回复，并自动发送。不涉及微信协议逆向、hook 或 DLL 注入。

## 功能概览

- 检测 / 激活微信窗口，自动定位聊天区域
- RapidOCR 识别聊天气泡（含坐标、颜色判断发送者）
- 过滤系统消息与时间戳（居中时间行、撤回提示等）
- 侧边栏红点检测，自动切换未读联系人
- 按好友游标增量识别新消息，连发合并后回复一次
- **多模型 LLM**：聊天回复 / 记忆提取 / 画像更新分任务路由
- 本地 JSONL 聊天记录作为 Prompt 上下文（最近 20 条）
- 向量长期记忆 + **详细好友画像**，辅助个性化回复
- **个人语言风格学习**：从全部聊天历史自动提取「我的说话方式」
- 聊天历史滚动采集工具

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| Python | 3.10+ |
| 微信 | Windows 桌面版 |
| API | 至少配置一个 LLM Provider（推荐 Qwen + DeepSeek 组合） |

## 安装

```bash
cd WeChat-AI-Agent
pip install -r requirements.txt
```

## 配置

### 1. LLM API（多任务路由）

复制 `.env.example` 为 `.env` 并填入 Key：

```bash
cp .env.example .env
```

推荐组合（拟人回复 + 省钱记忆/画像）：

```env
# 聊天回复 — 拟人化（推荐 Qwen-Plus）
LLM_CHAT_PROVIDER=qwen
LLM_CHAT_API_KEY=sk-your-qwen-key

# 记忆提取 — 可用便宜模型
LLM_MEMORY_PROVIDER=deepseek
LLM_MEMORY_API_KEY=sk-your-deepseek-key

# 画像更新 — 结构化 JSON 输出
LLM_PROFILE_PROVIDER=deepseek
LLM_PROFILE_API_KEY=sk-your-deepseek-key
```

支持的 Provider：`qwen` | `moonshot` | `glm` | `deepseek`。三任务也可共用同一 Provider（见 `.env.example` 注释）。

### 2. 聊天区域坐标

窗口大小变化后需重新校准，推荐使用可视化工具：

```bash
python tools/region_selector.py
```

坐标保存至 `config/chat_region.json`，程序启动时自动加载。输入框区域由聊天区坐标自动推算（`config/settings.py` 中的 `INPUT_REGION`）。

### 3. 个人画像与聊天风格

| 文件 | 说明 |
|------|------|
| `storage/profile.json` | 你的身份、爱好（Prompt 角色设定，手动维护） |
| `storage/style.json` | 语气、句长、常用词（手动风格约束，可选） |
| `storage/personal/my_style.json` | **自动学习**的个人语言风格（从全部 history 提取 `sender=me`） |

### 4. 个人知识库

个人知识库支持 Markdown、TXT 和 JSON，使用独立的 ChromaDB collection。先初始化目录：

```bash
python tools/knowledge_admin.py init
```

把资料放入 `storage/knowledge/sources/`，再编辑
`storage/knowledge/access.json`。权限配置默认 `private`，未明确授权的资料不会进入任何联系人的回复。
可参考 `config/knowledge_access.example.json`：

- `access: private`：任何联系人都不可使用。
- `access: allowlist`：仅 `allowed_contacts` 中的好友 ID 或微信显示名可使用。
- `access: all`：所有联系人可使用。
- `sensitivity: sensitive`：即使 `access` 为 `all`，也必须命中明确白名单；只有显式填写 `allowed_contacts: ["*"]` 才会向所有联系人开放。

配置完成后导入并测试：

```bash
python tools/knowledge_admin.py import
python tools/knowledge_admin.py search "我喜欢什么" --friend-id zhangsan --friend-name 张三
```

修改资料或权限后需要重新运行 `import`。回复时最多检索 4 个相关片段；可通过
`WECHAT_KNOWLEDGE_MIN_SCORE` 调整最低相关度，默认 `0.35`。

### 5. 好友画像

| 文件 | 说明 |
|------|------|
| `storage/profiles/{friend_id}.json` | 每位好友的详细画像（自动从 history + 向量记忆生成） |
| `storage/friends.json` | 好友元数据（关系、标签、手动 notes） |
| `storage/history/{friend_id}.jsonl` | 与每位好友的完整聊天记录 |

### 6. 隐私与调试

- `storage/`、`.env`、`debug/` 和 `logs/` 已默认加入 `.gitignore`，不要手动提交或同步。
- 控制台和日志默认隐藏聊天正文；完整 Prompt、审计日志和记忆详情默认不落盘/不显示。
- 检索命中的已授权知识片段会随 Prompt 发给当前配置的 LLM Provider；不要授权不应离开本机的资料。
- 仅在本机排障时，才在 `.env` 临时开启 `WECHAT_SHOW_CONTENT=1`、`WECHAT_SAVE_DEBUG_PROMPT=1` 等调试开关，完成后立即关闭。
- `storage/` 仍是本地明文数据（知识原文、ChromaDB、JSONL）；应使用 Windows 设备加密、BitLocker 或 EFS 保护磁盘，并限制该目录的系统账户权限。

## 使用方法

### 启动 Agent（主程序）

```bash
python main.py                  # 安全预览：生成回复但不发送
python main.py --send           # 明确启用自动监听 + 自动回复
python main.py --send --interval 5  # 自动发送，每 5 秒轮询一次
```

运行后程序会：

1. **启动时**同步个人语言风格 + 批量检查好友画像更新
2. 扫描侧边栏未读红点，或监控当前聊天窗口
3. OCR 解析消息，过滤系统/时间戳
4. 检索向量记忆、加载好友画像与风格上下文
5. 从 `storage/history/{friend_id}.jsonl` 加载最近 20 条对话
6. 调用 LLM 生成回复并发送
7. **回复后**异步提取记忆、增量更新个人风格

自动发送必须显式传入 `--send`；发送前会再次精确验证聊天标题，期间若手动切换联系人则自动中止。

按 `Ctrl+C` 停止。

### 采集聊天历史

```bash
python tools/history_collector.py
```

滚动聊天窗口、OCR 解析，保存至 `storage/history/{friend_id}.jsonl`（自动识别当前聊天对象并创建 friend_id）。历史数据是个人风格学习和好友画像的数据源。

### 批量更新好友画像

```bash
python -m memory.batch_update_profiles
```

从 `storage/history/*.jsonl` 强制重新生成所有好友的详细画像（跳过 test/test2 及消息过少的好友）。

### 记忆管理 CLI

```bash
python tools/memory_admin.py list-friends
python tools/memory_admin.py show yangchunhui
python tools/memory_admin.py search yangchunhui "喜欢什么"
```

### 调试工具

```bash
python automation/mouse.py           # 实时显示鼠标坐标
python tools/region_selector.py      # 可视化选择截图区域
python -m personal.style_test        # 个人风格模块测试
```

## 架构与数据流

```
侧边栏红点 / 当前聊天
        ↓
  截图 → RapidOCR → BubbleParser（颜色+坐标）
        ↓
  SystemMessageFilter（过滤时间戳/系统消息）
        ↓
  ChatTracker（按好友增量识别新消息）
        ↓
  MemoryService.retrieve_and_rank()  → 向量记忆
  StyleContextBuilder              → 好友画像 + 双方说话样例
  PersonalStyle (my_style.json)      → 我的语言风格
  HistoryStorage.get_recent(20)      → 近期对话
        ↓
  PromptBuilder → LLMClient(task=chat) → ReplyGuard → WeChatSender
        ↓
  写入 storage/history/*.jsonl
  异步: 记忆提取 + 个人风格增量 + 画像自动更新
```

**Prompt 组装优先级：**

1. 好友身份卡（summary / 背景 / 雷点 / 聊天注意）
2. 我的聊天风格（PersonalStyle Learning）
3. 我的说话样例 + 对方说话样例
4. 长期记忆（向量检索 Top 3）
5. 本地 JSONL 历史（最近 20 条，去重）
6. 屏幕 OCR 可见消息（无历史文件时兜底）

完整 Prompt 调试文件：`debug/last_prompt.txt`

## 项目结构

```
WeChat-AI-Agent/
├── main.py                     # 程序入口
├── config/
│   ├── settings.py             # 全局配置（区域坐标等）
│   └── chat_region.json        # 可视化校准的聊天区域
├── system/
│   └── runner.py               # 主循环：未读检测 → 回复调度
├── listener/                   # 消息监听 & 增量检测
├── parser/                     # 气泡 OCR → Message
├── agent/
│   ├── agent.py                # Agent 核心（决策 → Prompt → LLM → 发送）
│   └── prompt.py               # Prompt 组装（画像/风格/记忆/上下文）
├── wechat/                     # 窗口、截图、OCR、发送、未读检测
├── llm/
│   ├── client.py               # 多任务 LLM 客户端（chat/memory/profile）
│   └── config.py               # Provider 路由配置
├── personal/                   # 个人语言风格学习
│   ├── history_reader.py       # 从全部 jsonl 提取 sender=me
│   ├── style_analyzer.py       # LLM 分析 + 增量更新
│   └── style_storage.py        # → storage/personal/my_style.json
├── memory/                     # 长期记忆、好友画像、风格上下文
│   ├── memory_service.py       # 统一入口（检索/提取/画像同步）
│   ├── profile_builder.py      # 好友画像 LLM 更新
│   ├── friend_history_reader.py# 从 jsonl 提取 sender=friend
│   ├── style_context.py        # 好友身份卡 + 双方说话样例
│   └── batch_update_profiles.py# 批量强制更新画像
├── history/
│   └── storage.py              # JSONL 聊天记录读写
├── storage/
│   ├── history/                # 各好友聊天记录 *.jsonl
│   ├── profiles/               # 好友详细画像 *.json
│   ├── personal/my_style.json  # 自动学习的个人风格
│   ├── vector_db/chroma/       # ChromaDB 向量库
│   ├── profile.json            # 用户身份（手动）
│   └── style.json              # 聊天风格约束（手动）
├── tools/
│   ├── region_selector.py      # 区域校准工具
│   ├── history_collector.py    # 历史消息采集
│   └── memory_admin.py         # 记忆管理 CLI
└── debug/
    └── last_prompt.txt         # 最近一次发给 LLM 的 Prompt
```

规范入口以本节为准：历史采集使用 `tools/history_collector.py`，实时气泡解析使用 `parser/bubble_parser.py`，未读检测使用 `wechat/unread_detector.py`。旧的 `history.collector`、`wechat.parser`、`listener.sidebar_monitor` 仅保留兼容并已标记废弃。

## 技术方案

| 能力 | 方案 |
|------|------|
| 窗口控制 | pywinauto (UIA) + pygetwindow |
| 截图 / 键鼠 | pyautogui + Pillow |
| OCR | rapidocr-onnxruntime（ONNX，无需 GPU） |
| 大模型 | 多 Provider OpenAI 兼容 API（Qwen / DeepSeek / Moonshot / GLM） |
| 中文嵌入 | fastembed + BAAI/bge-small-zh-v1.5（512 维） |
| 长期记忆 | ChromaDB 向量检索 + 记忆合并/去重 |
| 持久化 | JSON / JSONL 文件 |

## 注意事项

- 微信窗口需完全在屏幕内，发送前会自动激活窗口并点击输入框
- 首次打开某好友聊天时只做快照、不回复历史消息；只有**新出现**的消息会触发回复
- OCR 存在误识别可能，已通过规则过滤时间戳和系统消息，极端情况仍可能漏判/误判
- 个人风格和好友画像都依赖 `storage/history/*.jsonl`，建议先用 `history_collector.py` 采集足够历史
- 聊天记录 JSONL 中可能有历史采集产生的重复行，`get_recent()` 会自动去除连续重复
- 运行期间尽量避免手动切换焦点，以免干扰自动发送

## 常见问题

**回复没有发到微信？**  
确认微信在前台；检查 `config/chat_region.json` 是否匹配当前窗口尺寸；查看日志是否有「无法激活微信窗口」。

**回复前言不搭后语？**  
打开 `debug/last_prompt.txt` 查看实际上下文；确认 `storage/history/{friend_id}.jsonl` 是否有该好友的记录；检查 `storage/profiles/{friend_id}.json` 画像是否已生成。

**回复太「AI 味」？**  
确认 `LLM_CHAT_PROVIDER` 使用 Qwen-Plus 或 Moonshot；运行 `python -m memory.batch_update_profiles` 刷新画像；检查 `storage/personal/my_style.json` 是否有足够样本。

**同一条消息重复回复？**  
删除或编辑 `storage/chat_tracker.json` 中对应好友条目后重启；确保已更新到最新版（内容指纹，不含 Y 坐标）。

## 详细文档

- [新消息检测与记忆模块分析](docs/新消息检测与记忆模块分析.md) — 架构详解、模块索引、改造记录

## Docker 部署（混合架构）

微信 Agent **不能**整包跑进 Linux Docker（依赖 Windows 微信 GUI）。可容器化的部分是 LLM API 网关。

**一步一步教程：** 见 [docker/README.md](docker/README.md)

**快速一键部署（Windows）：**

```powershell
copy docker\.env.example .env    # 填入 API Key
.\scripts\deploy.ps1             # Docker 网关 + Windows Agent
.\scripts\deploy.ps1 -UseGateway # Agent 经 localhost:8000 调 LLM
```
