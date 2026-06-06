# Novel Writer Agent — AI 智能小说创作系统

基于 Claude API 驱动的小说创作智能体，自动学习热门网文趋势并每日定时产出章节。

## 功能特性

- **AI 驱动创作**: 世界观构建 → 角色设计 → 大纲规划 → 每日章节生成
- **趋势学习**: 爬取番茄小说 & 起点中文网榜单，分析热门标签/类型/套路
- **定时发布**: 每日 08:00 + 20:00 自动生成两章 (~2000字/章)
- **长篇小说连贯**: 分层上下文管理 + Story Bible + Prompt 缓存
- **自我进化**: 趋势分析→融入热门元素→风格优化→质量追踪
- **多格式输出**: TXT + EPUB（带 CSS 排版、目录、封面）
- **成本可控**: API 调用追踪 + 月度预算告警 + Prompt 缓存节省 90%

## 系统架构

```
数据采集层(爬虫) → 趋势分析层 → 小说生成引擎
                                  ↓
     调度器 ← 共享数据层(SQLite) → 发布接口
                                  ↓
    Claude API              本地文件(TXT/EPUB)
```

## 快速开始

### 1. 环境要求

- Python 3.12+
- Claude API Key ([获取](https://console.anthropic.com/))

### 2. 安装

```bash
cd F:\novel-writer-agent
pip install -r requirements.txt
```

### 3. 配置

```bash
# 复制环境配置
copy .env.example .env

# 编辑 .env，填入你的 API Key
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 4. 使用

```bash
# 测试 API 连接
python -m src.main test

# 创建新小说（自动选择热门类型）
python -m src.main create

# 创建指定类型的小说
python -m src.main create 都市

# 手动生成下一章
python -m src.main generate

# 编译全文（TXT）
python -m src.main compile 1

# 编译 EPUB（带排版）
python -m src.main compile 1 epub

# 启动自动调度（每日 08:00 + 20:00 定时生成）
python -m src.main start

# 查看系统状态
python -m src.main status
```

## 项目结构

```
novel-writer-agent/
├── config/
│   ├── settings.yaml              # 主配置（模型/调度/预算）
│   ├── genres.yaml                # 7大类型定义+热门标签
│   └── prompts/                   # 5个 LLM Prompt 模板
│       ├── world_building.yaml    # 世界观构建
│       ├── character_design.yaml  # 角色设计
│       ├── chapter_outline.yaml   # 大纲规划
│       ├── chapter_write.yaml     # 章节写作
│       └── trend_analysis.yaml    # 趋势分析
├── src/
│   ├── core/models.py             # 数据模型 (6 ORM + 7 Pydantic)
│   ├── config.py                  # 配置加载器
│   ├── main.py                    # CLI 入口
│   ├── data_collection/           # 爬虫模块
│   │   ├── base.py                # 基类 + 数据模型
│   │   ├── fanqie_scraper.py      # 番茄小说爬虫
│   │   ├── qidian_scraper.py      # 起点中文网爬虫
│   │   └── rate_limiter.py        # Token Bucket 限速
│   ├── trend_analysis/            # 趋势分析
│   │   ├── analyzer.py            # 总控分析器
│   │   ├── tag_extractor.py       # 标签提取+共现矩阵
│   │   └── genre_classifier.py    # 类型热度排名
│   ├── generation/                # 生成引擎
│   │   ├── planner.py             # 总控编排器
│   │   ├── world_builder.py       # 世界观构建
│   │   ├── character_designer.py  # 角色设计
│   │   ├── plot_outliner.py       # 大纲生成
│   │   ├── chapter_writer.py      # 章节写作
│   │   ├── context_manager.py     # 分层上下文管理
│   │   ├── story_bible.py         # 故事圣经
│   │   └── quality_checker.py     # 质量检查(5项)
│   ├── scheduler/                 # 定时调度
│   │   ├── scheduler_service.py   # APScheduler 封装
│   │   └── jobs.py                # 5个定时任务
│   ├── llm/                       # LLM 客户端
│   │   ├── client.py              # Anthropic SDK 封装
│   │   ├── cost_tracker.py        # 成本追踪
│   │   └── prompt_manager.py      # Prompt 模板管理
│   ├── storage/                   # 持久化
│   │   ├── database.py            # SQLAlchemy 引擎
│   │   ├── file_store.py          # 文件输出管理
│   │   └── repositories/          # 3个数据仓库
│   ├── publishing/                # 发布接口
│   │   ├── local_publisher.py     # 本地发布器
│   │   └── format_epub.py         # EPUB 格式化
│   └── utils/                     # 工具
├── output/                        # 生成的小说
├── data/                          # 数据库+缓存
└── logs/                          # 日志
```

## 定时任务调度

| 任务 | 时间 | 说明 |
|------|------|------|
| 上午章节 | 每日 08:00 CST | 生成第 N 章 (~2000字) |
| 下午章节 | 每日 20:00 CST | 生成第 N+1 章 |
| 趋势刷新 | 每周日 03:00 | 爬取榜单+分析趋势 |
| 成本报告 | 每日 23:00 | API成本/预算汇总 |
| 健康检查 | 每 30 分钟 | DB+输出目录状态 |

## 上下文管理策略

长篇小说面临的最大挑战是保持 100+ 章的连贯性。本系统采用分层上下文：

| 层级 | 内容 | Token 估算 |
|------|------|-----------|
| Layer 1 | Story Bible（世界观+角色+情节线+时间线） | ~7K |
| Layer 2 | 最近 3 章全文 | ~9K |
| Layer 3 | 第 4-N 章摘要 (~100字/章) | ~14K |
| Layer 4 | 已完结故事弧摘要 | ~1K |
| Layer 5 | 当前章节大纲 | ~2K |
| **合计** | | **~33K** |

配合 Anthropic Prompt Caching，上午/下午两章在一小时内生成时，第二章节省 ~90% 输入成本。

## 模型选择

| 生成阶段 | 模型 | 原因 |
|----------|------|------|
| 世界观构建 | Opus 4.8 | 深度创意，需内在一致性 |
| 角色设计 | Opus 4.8 | 细腻人格塑造 |
| 大纲规划 | Opus 4.8 | 结构性复杂度 |
| 章节写作 | Sonnet 4.6 | 日更量大，性价比最优 |
| 趋势分类 | Haiku 4.5 | 大量简单分类，成本敏感 |
| 质量检查 | Haiku 4.5 | 简单验证任务 |

## 成本预估

- 每日 2 章 (Sonnet + Prompt Caching): ~$0.12/天
- 每月写作 (~60章): ~$7.20
- 月度规划+分析 (Opus): ~$5-8
- **总计**: ~$15-25/月

## License

MIT
