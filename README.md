# Codeforces 思维训练终端 (CF-Coach-CLI)

专为**“只构思算法思路、不实际写代码”**的算法竞赛思维训练设计。针对 Codeforces 题库，由 AI 算法教练协助你剥离原题无用故事背景、提炼形式化数学模型，在交互中验证你的状态设计与算法复杂度，并严格限制只输出单个反例或阶梯式提示，杜绝泄露题解。

---

## 🌟 核心特性

1. **智能选题池与全量本地缓存**：
   - 自动拉取 Codeforces 官方题库与用户历史提交数据。
   - **题目全量本地持久化**：抓取到的题面结构、样例与时空限制全部持久化缓存入 SQLite；二次访问耗时从 ~15 秒降至 **0.17 毫秒**（性能提升近 10 万倍）。
   - **大模型题意摘要缓存**：提炼出的纯粹数学模型同步持久化，再次打开同题 0 秒加载且 0 额外 Token 消耗。
   - **当前未解决题目现场锁定**：正在思考的题目退出后自动常驻保存在本地，下次启动直接**秒级恢复现场**，直至验证通过 (PASS)、显式 `/pass` 或切换 `/next`。
   - 结合本地 SQLite 数据库与 CF 官方 AC 记录，自动过滤所有已解决题目。
   - 支持按 Rating 难度区间（如 `1500~2000`）及算法 Tags（如 `dp, greedy, math, graphs`）筛选。
2. **纯粹题意转化**：
   - Agent 自动剥离背景故事修饰，提炼严谨的数学模型、数据范围规模与时空限制。
3. **金牌教练思维点拨**：
   - 用户在终端输入解题想法、状态转移方程或时间复杂度。
   - **通过判定**：思路正确且复杂度达标时，判定通过并自动记录至本地已解决题库。
   - **循序渐进**：思路有缺陷时，**严格限制只给出 1 个致命反例或 1 处逻辑漏洞**，或提供 1 级阶梯提示（`/hint`），绝不剧透完整题解。
4. **按需现代 C++ AC 代码**：
   - 输入 `/code` 即时生成现代 C++ (C++17/20) 的 AC 级高质代码与防踩坑注释。
5. **生产级日志中枢与可观测性**：
   - 采用 `loguru` 实现**前台静默交互、后台自动轮转落盘**，杜绝日志刷屏污染 TUI 界面。
   - 规范写入 `~/.local/share/cf-coach/logs/cf_coach.log`，单文件超 10MB 自动轮转并保留 7 天历史归档。
   - 完整追踪 CF 抓取链路耗时、缓存命中状态、LLM 请求与反例判定细节。
6. **双模型与本地路由**：
   - 原生支持 OpenAI 兼容 API、火山方舟 Coding 端点、以及通过 `base_url` 接入本地部署的 Ollama / vLLM 模型。

---

## 🛠️ 快速上手

### 1. 安装依赖

推荐使用 `uv` 快速创建虚拟环境并安装：

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 配置参数 (`config.yaml`)

编辑 `config.yaml` 或直接使用默认配置：

```yaml
codeforces:
  handle: "sanzenin"       # 你的 Codeforces 用户名
  rating_min: 1500         # 训练起始 Rating
  rating_max: 2000         # 训练结束 Rating
  tags: []                 # 标签过滤，如 ["dp", "greedy"]，留空则不限

llm:
  provider: "openai_compatible"
  base_url: "https://ark.cn-beijing.volces.com/api/coding/v3"
  api_key: "YOUR_API_KEY_HERE"
  model: "glm-5-3-flash"     # 指定接入的模型标识
  temperature: 0.2
  max_tokens: 4096

storage:
  db_path: "data/cf_coach.db"
```

### 3. 运行训练工具

该工具已注册为全局命令行指令 `cf-coach`（位于 `~/.local/bin/cf-coach`），在系统的任意工作目录下均可直接调用：

```bash
# 全局直接启动
cf-coach

# 指定难度范围与标签快速启动
cf-coach --min-rating 1600 --max-rating 1900 --tags dp,greedy

# 直接挑战特定题目（如 1800A）
cf-coach --problem 1800A
```

亦可在项目目录中使用虚拟环境解释器调用：

```bash
.venv/bin/python3 main.py
```

---

## ⌨️ 终端指令速查

在思维训练会话中，输入普通文本即向教练提交解题思路；输入斜杠指令可触发快捷操作（支持 Tab 补全）：

| 指令 | 说明 |
| :--- | :--- |
| `/next [ID]` | 随机抽取下一道符合条件的题目（或指定题号如 `/next 1999B`） |
| `/glow` | **调用 Glow 原生交互式全屏分页**浏览当前题面、公式或代码（按 `q` 退出返回） |
| `/hint` | 向教练请求 1 级阶梯启发提示（不泄露完整题解） |
| `/code` | 生成该题的标准现代 C++ AC 代码与关键实现注释 |
| `/raw` | 查看 Codeforces 原始英文题面与输入输出样例 |
| `/pass` | 手动标记当前题目为已解决并存入本地数据库 |
| `/stats` | 查看本地历史做题统计（已通过 / 尝试中） |
| `/config` | 查看当前配置与 LLM 状态 |
| `/help` | 查看帮助列表 |
| `/quit` | 保存进度并退出 |

---

## 📺 极致终端：结合 Glow 实时双屏联动

本工具已全面内嵌并联动 **Charmbracelet Glow** 终端渲染器：

1. **会话内交互式分页**：
   - 在 `cf-coach` 交互会话中，输入 `/glow` 即可利用 Glow 的全屏滚动分页器查看题面与代码，支持键盘上下翻页。
2. **实时双屏同步 (Live Dual-Pane)**：
   - 每次切换题目、教练评估或生成代码时，题面与点拨会自动同步至 `~/.local/share/cf-coach/current.md`。
   - 在右侧或副终端窗格执行：
     ```bash
     cf-coach --watch
     # 或
     glow-watch ~/.local/share/cf-coach/current.md
     ```
   - 此时左侧专注文档或输入思路，右侧将**实时自动刷新**题目数学模型与最新点拨！
3. **命令行独立查看**：
   - 无需进入 TUI 循环，直接调用：`cf-coach --glow` 查看最近一道题目的完整排版。

---

## 📂 项目结构规范

```text
.
├── config.yaml               # 配置文件
├── requirements.txt          # 核心依赖清单
├── README.md                 # 运行说明与手册
├── main.py                   # 启动入口与 CLI 参数解析
├── data/                     # 本地 SQLite 数据库与 CF 题库缓存目录
└── src/
    ├── __init__.py
    ├── config.py             # Pydantic 配置模型与环境加载
    ├── cf_client.py          # Codeforces 官方 API 与题面抓取解析
    ├── storage.py            # SQLite 训练记录与做题状态存储
    ├── agent/
    │   ├── __init__.py
    │   ├── llm_factory.py    # LangChain 模型工厂 (OpenAI/Ark/Local)
    │   ├── prompts.py        # 题意提炼、思路判定与阶梯点拨 Prompt
    │   └── coach_chain.py    # LangChain 完整交互链路封装
    └── tui/
        ├── __init__.py
        └── app.py            # Rich 控制台渲染与 prompt_toolkit 交互循环
```
