# DSH Memory Search

DSH 会话记忆智能检索工具 — 扫描所有 `session.md`，利用 SQLite FTS5 建立全文索引，通过 CLI 提供高速智能检索。

## 特性

- **零依赖**：仅 Python 标准库（sqlite3、argparse、hashlib、pathlib）
- **FTS5 全文检索**：trigram 分词，中文子串匹配
- **BM25 相关性排序**：标题命中权重翻倍，结果更精准
- **搜索结果摘要**：自动提取含关键词的上下文片段
- **增量索引**：基于 SHA-256 内容指纹，只索引变更文件
- **批量提交**：大量文件入库时分批 commit，避免内存膨胀
- **FTS5 安全转义**：含特殊字符（引号、括号等）的查询不会报错

## 安装

```bash
cd D:\code\dsh-memory-search
pip install -e .
```

## 使用

### 索引会话文件

```bash
dsh-memory index
```

### 搜索

```bash
dsh-memory search "关键词"
dsh-memory search "Python 开发" --limit 20
dsh-memory search "数据库" --json
```

### 查看统计

```bash
dsh-memory stats
```

### 查看单条会话

```bash
dsh-memory show session-4fe146c8-...
```

### 清理已删除的记录

```bash
dsh-memory clean
```

## 项目结构

```
dsh-memory-search/
├── src/
│   ├── __init__.py
│   ├── main.py           # CLI 入口（argparse 子命令分发）
│   ├── database.py       # SQLite 连接 + Schema + WAL
│   ├── models.py         # Session / SearchResult 数据模型
│   ├── indexer.py        # 文件扫描 + 增量入库 + 批量提交
│   └── search_engine.py  # FTS5 查询 + BM25 排序 + snippet 摘要
├── tests/
│   └── test_smoke.py     # 冒烟测试（9 个用例）
├── ARCHITECTURE.md       # 架构设计文档
└── setup.py
```

## 技术细节

- **FTS5 trigram**：每 3 字符生成重叠 token，中文子串匹配最优
- **BM25 加权**：`bm25(fts, title_weight=2.0, content_weight=1.0)`
- **WAL 模式**：提升并发读写性能
- **触发器同步**：INSERT/UPDATE/DELETE 自动同步 FTS 索引
- **SHA-256 增量**：比 mtime 更可靠的变更检测
- **批量 commit**：每 50 条提交一次，大目录不爆内存
- **snippet 摘要**：FTS5 snippet() 提取上下文，关键词用 【】 标记

## 测试

```bash
python -m tests.test_smoke
# 9 个用例：schema、BM25 排序、LIKE 回退、FTS5 转义、snippet、增量索引、标题提取、事件提取、hash
```

## License

MIT
