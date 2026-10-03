# DSH 会话记忆智能检索工具 — 架构设计

> 版本：1.0 · 日期：2026-10-03 · 作者：architect

## 1. 项目概述

扫描 `D:\dsh\workspaces\<日期>\<会话id>\session.md` 下的所有 DSH 会话文件，利用 SQLite FTS5 建立全文索引，通过 CLI 提供高速智能检索。

**核心约束：** Python 3.14 · 仅标准库（sqlite3、argparse、hashlib、pathlib、datetime）· 零外部依赖

---

## 2. 目录结构

```
dsh-memory-search/
├── ARCHITECTURE.md          ← 本文档（架构说明）
├── src/
│   ├── __init__.py          │ 包标识
│   ├── main.py              │ CLI 入口（argparse 子命令分发）
│   ├── database.py          │ SQLite 连接管理 + Schema 创建/迁移
│   ├── models.py            │ 数据模型（Session 数据类）
│   ├── indexer.py           │ 文件扫描 + 入库 + 增量更新
│   └── search_engine.py     │ FTS5 查询封装 + 结果格式化
├── data/
│   └── .gitkeep             │ 数据库文件存放位置（默认 memory.db）
└── tests/
    └── .gitkeep             │ 测试占位
```

---

## 3. SQLite Schema 设计

### 3.1 sessions 表（主存储）

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL UNIQUE,        -- 会话 ID（如 session-4fe146c8-...）
    session_date TEXT NOT NULL,              -- 日期目录名（如 2026-10-03）
    title       TEXT,                        -- 从 session.md 首行 H1 提取
    file_path   TEXT NOT NULL UNIQUE,        -- session.md 绝对路径
    content     TEXT NOT NULL,               -- 完整 Markdown 内容
    content_hash TEXT NOT NULL,              -- SHA-256 内容指纹（变更检测）
    file_mtime  REAL NOT NULL,               -- 文件修改时间（os.stat st_mtime）
    indexed_at  REAL NOT NULL,               -- 入库时间（unixepoch）
    created_at  REAL DEFAULT (unixepoch())   -- 记录创建时间
);

CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON sessions(content_hash);
```

### 3.2 sessions_fts 表（FTS5 全文索引）

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_id,                              -- 会话标识（可搜索）
    title,                                   -- 标题
    content,                                 -- 正文
    tokenize='trigram'                       -- 三元组分词，最优中文子串匹配
);
```

> **为什么选 trigram？**
> - `unicode61`：将连续中文字符合并为一个 token，只能整词匹配，搜"记"找不到"记忆检索"
> - `trigram`：每 3 字符生成重叠 token（"记忆检索"→"记忆检"/"忆检索"），中文子串匹配最优
> - 查询 ≥ 3 字符走 FTS5 索引；< 3 字符时 trigram 无法建索引，**搜索引擎自动回退 LIKE 全表扫描**
>
> **实测发现（冒烟测试验证）：** 2 字符 MATCH 查询在 FTS5 trigram 下返回 0 条（非自动退化），因此 `search_engine.py` 对 < 3 字符查询显式走 LIKE 回退路径。

### 3.3 触发器（自动同步 FTS）

```sql
-- 插入时同步进 FTS
CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, session_id, title, content)
    VALUES (new.id, new.session_id, new.title, new.content);
END;

-- 删除时同步出 FTS
CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, session_id, title, content)
    VALUES ('delete', old.id, old.session_id, old.title, old.content);
END;

-- 更新时同步（删旧+插新）
CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, session_id, title, content)
    VALUES ('delete', old.id, old.session_id, old.title, old.content);
    INSERT INTO sessions_fts(rowid, session_id, title, content)
    VALUES (new.id, new.session_id, new.title, new.content);
END;
```

### 3.4 index_meta 表（索引元数据）

```sql
CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

用途：记录最后扫描时间、已索引文件数等运行时状态。

---

## 4. CLI 命令定义

入口脚本：`python -m src.main`

```
dsh-memory index [OPTIONS]      扫描并索引会话文件
  -p, --path PATH              工作区路径（默认 D:\dsh\workspaces）
  -f, --force                  强制全量重建（忽略增量检测）
  -d, --db PATH               数据库路径（默认 ./data/memory.db）

dsh-memory search <QUERY> [OPTIONS]   全文检索
  -n, --limit N               返回条数（默认 10）
  -d, --db PATH               数据库路径
  --json                       JSON 格式输出（供程序消费）

dsh-memory stats [OPTIONS]      索引统计
  -d, --db PATH               数据库路径

dsh-memory show <SESSION_ID> [OPTIONS]  查看单条会话内容
  -d, --db PATH               数据库路径

dsh-memory clean [OPTIONS]      清理已不存在的会话记录
  -d, --db PATH               数据库路径
```

---

## 5. 增量索引策略

1. **首次全量：** 扫描所有 `session.md`，计算 SHA-256，全部入库
2. **增量更新：** 对每个文件：
   - 读取 `content_hash` 与 DB 中记录对比
   - 若 hash 不同 → 触发 UPDATE（触发器自动同步 FTS）
   - 若 `file_path` 在 DB 中不存在 → INSERT
   - 若 `file_path` 在 DB 中存在但文件已删除 → 标记待清理
3. **变更检测：** `content_hash = sha256(content_bytes)`，比单纯对比 mtime 更可靠

---

## 6. 搜索排序

FTS5 原生支持 `bm25()` 排序函数：

```sql
SELECT s.session_id, s.session_date, s.title,
       bm25(sessions_fts) AS rank
FROM sessions_fts
JOIN sessions s ON s.id = sessions_fts.rowid
WHERE sessions_fts MATCH ?
ORDER BY rank
LIMIT ?;
```

- `bm25()` 值越小越相关（FTS5 约定）
- 中文场景下 bm25 权重可能不够精细，后续可引入标题加权

---

## 7. 模块职责边界

| 模块 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `database.py` | SQL 语句 | 连接/cursor | 连接池管理、schema 初始化、WAL 模式 |
| `models.py` | 字典 | Session 对象 | 数据校验与序列化 |
| `indexer.py` | 文件系统路径 | DB 记录 | 遍历目录、读文件、hash 比对、入库 |
| `search_engine.py` | 查询字符串 | 结果列表 | FTS5 查询构建、bm25 排序、结果截取摘要 |
| `main.py` | CLI 参数 | stdout | argparse 子命令分发、调用各模块 |

---

## 8. 后续扩展点（不在 v1 范围）

- 标题权重提升（title 命中加权）
- 日期范围过滤
- 结果摘要片段高亮（FTS5 snippet() 函数）
- 多字段独立权重 bm25(title, content) 调参
- 自动定时索引（结合 Windows 计划任务）
