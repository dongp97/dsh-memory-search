# DSH Memory Search

DSH 会话记忆智能检索工具 — 扫描所有 `session.md`，利用 SQLite FTS5 建立全文索引，通过 CLI 提供高速智能检索。

## 特性

- **零依赖**：仅 Python 标准库（sqlite3、argparse、hashlib、pathlib）
- **FTS5 全文检索**：trigram 分词，中文子串匹配
- **BM25 相关性排序**：搜索结果按相关度排序
- **增量索引**：基于 SHA-256 内容指纹，只索引变更文件
- **短查询回退**：<3 字符自动回退 LIKE 全表扫描

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
│   ├── main.py           # CLI 入口
│   ├── database.py       # SQLite 连接 + Schema
│   ├── models.py         # 数据模型
│   ├── indexer.py        # 文件扫描 + 增量入库
│   └── search_engine.py  # FTS5 查询 + BM25 排序
├── tests/
│   └── test_smoke.py     # 冒烟测试
├── ARCHITECTURE.md       # 架构设计文档
└── setup.py
```

## 技术细节

- **FTS5 trigram**：每 3 字符生成重叠 token，中文子串匹配最优
- **WAL 模式**：提升并发读写性能
- **触发器同步**：INSERT/UPDATE/DELETE 自动同步 FTS 索引
- **SHA-256 增量**：比 mtime 更可靠的变更检测

## License

MIT
