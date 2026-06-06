# Novel Writer Agent 使用说明

## 目录

1. [环境准备](#1-环境准备)
2. [安装配置](#2-安装配置)
3. [快速体验](#3-快速体验)
4. [创建小说](#4-创建小说)
5. [章节生成](#5-章节生成)
6. [全自动模式](#6-全自动模式)
7. [输出与管理](#7-输出与管理)
8. [高级配置](#8-高级配置)
9. [常见问题](#9-常见问题)

---

## 1. 环境准备

### 必需条件
- **Python 3.12+** — [下载地址](https://www.python.org/downloads/)
- **Claude API Key** — [申请地址](https://console.anthropic.com/)（需要充值 $5+）
- **Windows 10/11** 或 Linux/macOS
- 磁盘空间：~500MB（依赖包）+ 小说输出空间（每部小说约 5-10MB）

### 验证 Python 版本
```bash
python --version
# 输出应为: Python 3.12.x 或更高
```

---

## 2. 安装配置

### 2.1 进入项目目录
```bash
cd F:\novel-writer-agent
```

### 2.2 安装依赖
```bash
pip install -r requirements.txt
```

如果遇到权限错误，使用：
```bash
pip install --user -r requirements.txt
```

### 2.3 配置 API Key

#### 方法一：使用 .env 文件（推荐）
```bash
# 复制模板
copy .env.example .env

# 用记事本编辑 .env 文件
notepad .env
```

将文件中的 `your-api-key-here` 替换为你的真实 API Key：
```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
```

#### 方法二：系统环境变量
```bash
setx ANTHROPIC_API_KEY "sk-ant-api03-xxxxxxxxxxxxx"
```

### 2.4 测试连接
```bash
python -m src.main test
```

成功输出：
```
  API test: 连接成功
  Cost: $0.000123 | Latency: 450ms
```

> ⚠️ 如果失败，请检查：
> - API Key 是否正确（以 `sk-ant` 开头）
> - 网络是否能访问 `api.anthropic.com`
> - 账户是否有余额

---

## 3. 快速体验

最快 5 分钟体验完整流程：

```bash
# 1. 确认连接正常
python -m src.main test

# 2. 创建一部玄幻小说（AI 全自动策划）
python -m src.main create 玄幻

# 3. 手动生成第一章
python -m src.main generate

# 4. 查看输出
dir output
```

---

## 4. 创建小说

### 4.1 指定类型创建

```bash
# 玄幻小说
python -m src.main create 玄幻

# 都市小说
python -m src.main create 都市

# 仙侠小说
python -m src.main create 仙侠

# 科幻小说
python -m src.main create 科幻

# 历史小说
python -m src.main create 历史

# 游戏小说
python -m src.main create 游戏

# 悬疑小说
python -m src.main create 悬疑
```

### 4.2 让 AI 自动选择类型

```bash
# 不写类型，AI 根据热门趋势自动选择
python -m src.main create
```

AI 会自动分析番茄小说和起点中文网的热门榜单，选出当前最火的类型和元素。

### 4.3 创建过程发生了什么？

创建一部小说时，系统会依次执行：

```
Step 1/5: 构建世界观
  → Claude Opus 设计修炼体系/社会结构/势力分布/历史背景

Step 2/5: 设计角色
  → 主角 + 配角(3-5名) + 反派(1-2名) + 关系图谱

Step 3/5: 创建小说记录
  → 存入数据库，设置书名、简介、目标章节数

Step 4/5: 初始化故事圣经
  → 角色状态追踪、情节线管理、时间线记录

Step 5/5: 生成初始大纲
  → 前 20 章的详细大纲（每章 3-5 个剧情点 + 钩子）
```

> 创建一部小说大约需要 2-5 分钟，消耗 ~$0.30-0.80（主要使用 Opus）。

---

## 5. 章节生成

### 5.1 手动生成

```bash
# 自动寻找活跃的小说，生成下一章
python -m src.main generate

# 指定小说 ID 生成
python -m src.main generate 1

# 连续生成多章（手动执行多次）
python -m src.main generate
python -m src.main generate
python -m src.main generate
```

### 5.2 生成过程发生了什么？

```
1. 加载 Story Bible（世界观+角色状态+情节线）
2. 组装分层上下文（最近3章全文+历史摘要）
3. Claude Sonnet 生成 ~2000 字章节内容
4. 质量检查（字数/对话/连贯性/重复检测）
5. 更新 Story Bible（角色状态变化/新事件/时间线）
6. 保存到 output 目录
7. 生成章节摘要（用于后续上下文管理）
```

### 5.3 生成一章节的成本

| 模型 | 缓存状态 | 每章成本 |
|------|----------|----------|
| Sonnet 4.6 | 未缓存 | ~$0.14 |
| Sonnet 4.6 | 已缓存 | ~$0.06 |
| Opus 4.8 | 未缓存 | ~$0.70 |

> 上午+下午两章在 1 小时内生成时，第二章享受缓存折扣，每日 ~$0.12。

---

## 6. 全自动模式

这是系统的核心功能——启动后无需人工干预，每天自动产出。

### 6.1 启动调度器

```bash
python -m src.main start
```

输出示例：
```
============================================================
  Starting Scheduler
============================================================
  ✓ Morning chapter:  08:00 daily
  ✓ Evening chapter:  20:00 daily
  ✓ Trend refresh:    Every sun at 03:00
  ✓ Cost report:      23:00 daily
  ✓ Health check:     Every 30 minutes
------------------------------------------------------------

  Scheduled Jobs (5):
  ID                             Next Run               Trigger
  ------------------------------ ---------------------- -------------------------
  health_check                   13:51:00               interval[0:30:00]
  morning_chapter                2026-06-06 08:00:00    cron[hour='8', minute='0']
  evening_chapter                2026-06-05 20:00:00    cron[hour='20', minute='0']
  trend_refresh                  2026-06-07 03:00:00    cron[day_of_week='sun']
  cost_report                    2026-06-05 23:00:00    cron[hour='23', minute='0']
------------------------------------------------------------
  Scheduler is RUNNING. Press Ctrl+C to stop.
============================================================
```

### 6.2 停止调度器

```bash
# 在新终端窗口执行
python -m src.main stop

# 或在运行窗口按 Ctrl+C
```

### 6.3 查看调度状态

```bash
python -m src.main jobs
```

### 6.4 自定义调度时间

编辑 `config\settings.yaml`：
```yaml
scheduling:
  timezone: "Asia/Shanghai"
  morning_chapter: "08:00"     # 改为你想要的发布时间
  evening_chapter: "20:00"
  trend_refresh:
    day: "sun"
    time: "03:00"
```

### 6.5 调度任务详解

| 任务 | 频率 | 说明 |
|------|------|------|
| **morning_chapter** | 每日 08:00 | 自动生成并发布上午章节（~2000字） |
| **evening_chapter** | 每日 20:00 | 自动生成并发布下午章节（~2000字） |
| **trend_refresh** | 每周日 03:00 | 爬取番茄+起点榜单，分析热门趋势 |
| **cost_report** | 每日 23:00 | 汇总当天 API 调用成本 |
| **health_check** | 每 30 分钟 | 检查数据库/输出目录状态 |

---

## 7. 输出与管理

### 7.1 查看系统状态

```bash
python -m src.main status
```

输出包含：
- 所有小说列表（ID、书名、类型、章节进度、状态）
- 输出目录中的文件数
- API 使用量和成本统计

### 7.2 文件输出结构

```
output/
└── 星辰变/                     # 以小说名命名的文件夹
    ├── metadata.json            # 小说元数据
    ├── story_bible.json         # 故事圣经（角色状态/情节/时间线）
    ├── chapter_0001.txt         # 第1章：武魂觉醒
    ├── chapter_0002.txt         # 第2章：初入宗门
    ├── chapter_0003.txt         # 第3章
    ├── ...
    ├── 星辰变_全文.txt          # 全本编译 TXT
    └── 星辰变.epub             # EPUB 电子书
```

### 7.3 章节文件格式

```
第1章 武魂觉醒

林风站在青云宗的山门前，望着巍峨的山峰，心中涌起一股豪情。
"这就是青云宗吗？"他喃喃自语道。
...
```

### 7.4 编译全本

```bash
# 编译为 TXT（适合阅读器、Word）
python -m src.main compile 1

# 编译为 EPUB（带排版、目录、封面）
python -m src.main compile 1 epub
```

EPUB 特性：
- 📖 自动生成封面页
- 📑 带超链接的章节目录
- 🎨 CSS 排版（字体/行距/缩进）
- 📱 兼容手机阅读器（微信读书/Apple Books/Kindle）

### 7.5 管理多部小说

```bash
# 创建不同的小说
python -m src.main create 玄幻    # → ID: 1
python -m src.main create 都市    # → ID: 2
python -m src.main create 仙侠    # → ID: 3

# 指定 ID 生成
python -m src.main generate 1    # 给《星辰变》写一章
python -m src.main generate 2    # 给都市小说写一章

# 查看所有小说
python -m src.main status

# 编译不同小说
python -m src.main compile 1 txt
python -m src.main compile 2 epub
```

> 注意：自动模式（`start`）只会给活跃的（status=writing）的小说生成章节。

---

## 8. 高级配置

### 8.1 修改章节长度

编辑 `config\settings.yaml`：
```yaml
generation:
  chapter:
    target_words: 2000    # 改为 3000 或 1500
    min_words: 1800
    max_words: 2200
```

### 8.2 修改每日章节数

```yaml
generation:
  chapter:
    chapters_per_day: 2   # 改为 1 或 3
```

需同步修改调度配置。

### 8.3 设置月度预算

```yaml
budget:
  monthly_limit_usd: 25.00    # 月度预算上限
  alert_threshold: 0.8         # 80% 时告警
```

或在 `.env` 中设置：
```
NOVEL_MONTHLY_BUDGET=25.00
```

### 8.4 更换写作模型

```yaml
llm:
  models:
    chapter_writing: "claude-sonnet-4-6-20250514"    # 性价比
    # chapter_writing: "claude-opus-4-8-20251101"    # 质量优先（贵5倍）
    world_building: "claude-opus-4-8-20251101"
    quality_check: "claude-haiku-4-5-20251001"
```

### 8.5 自定义 Prompt

Prompt 模板在 `config\prompts\` 目录下，可以直接编辑：

| 文件 | 作用 |
|------|------|
| `world_building.yaml` | 调整世界观构建风格 |
| `character_design.yaml` | 调整角色设计要求 |
| `chapter_outline.yaml` | 调整大纲规划策略 |
| `chapter_write.yaml` | **最重要** — 调整写作风格/规则 |
| `trend_analysis.yaml` | 调整趋势分析维度 |

例如，修改写作风格（编辑 `chapter_write.yaml`）：
```yaml
  - 语言：流畅中文，偏文艺风格
  - 段落：中等段落，每段 3-8 行
```

### 8.6 手动触发趋势分析

```bash
# 在 Python 环境中手动执行
python -c "
import asyncio
from src.main import NovelWriterApp
app = NovelWriterApp()
asyncio.run(app.trend_analyzer.run_full_analysis())
"
```

### 8.7 日志查看

```bash
# 主日志
type logs\app.log

# 成本日志
type logs\cost.log

# 错误日志
type logs\error.log
```

---

## 9. 常见问题

### Q: 创建小说时出错？
检查 API Key 和网络连接：
```bash
python -m src.main test
```

### Q: 小说连贯性不好？
- 确保质量检查分数 > 0.7
- 考虑换用 Opus 模型写关键章节
- 检查 `story_bible.json` 是否正确更新

### Q: 成本超出预算？
查看成本明细：
```bash
type logs\cost.log
```
建议：
- 降低章节字数
- 使用 Sonnet 替代 Opus
- 确保 Prompt Caching 生效（两章间隔 < 1小时）

### Q: 爬虫获取不到数据？
系统有 Fallback 机制 —— 爬取失败时使用配置中的默认热门数据。不影响小说生成。

### Q: 如何在一台电脑上运行多部小说？
调度器会自动找 `status=writing` 的小说。只有一部时会一直写它；有多部时只会写活跃的那部。切换活跃小说：
```sql
-- 在 SQLite 中手动切换
UPDATE novels SET status = 'writing' WHERE id = 2;
UPDATE novels SET status = 'paused' WHERE id = 1;
```

### Q: 数据库出问题了？
重置数据库（⚠️ 会删除所有小说记录）：
```bash
python -m src.main init-db
```

### Q: 生成的内容能商用吗？
生成的小说版权归属请参考 Anthropic 的[服务条款](https://www.anthropic.com/legal/terms)。通常 API 输出的版权归用户所有。

---

## 快速参考卡

```bash
# 安装
pip install -r requirements.txt

# 配置
copy .env.example .env && notepad .env

# 测试
python -m src.main test

# 创建
python -m src.main create 玄幻    # 指定类型
python -m src.main create          # AI 自动选择

# 写作
python -m src.main generate        # 生成下一章
python -m src.main start           # 全自动模式

# 输出
python -m src.main compile 1       # TXT
python -m src.main compile 1 epub  # EPUB

# 查看
python -m src.main status          # 系统状态
python -m src.main jobs            # 调度任务

# 日志
type logs\app.log
type logs\cost.log
```
