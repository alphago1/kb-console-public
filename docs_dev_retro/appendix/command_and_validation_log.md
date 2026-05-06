# 附录 B — 命令与验证日志

**用途**：记录开发过程中执行的关键命令、测试输出、验证结果。作为"修复确实生效了"的证据。

**读者**：自己（回顾时确认什么命令好用）/ 其他接手项目的人。

**怎么填**：每条包含：日期、命令、关键输出摘要、是否通过。

---

## 格式

```
### 2026-05-03 — BUG-001 验证

**命令**：
python -c "...模拟冷启动..."

**关键输出**：
BUG-001 CONFIRMED: ALTER TABLE fails: no such table: documents

**状态**：✅ 已确认 / ❌ 未复现
```

---

## 常用命令速查

### 语法检查
```bash
python -c "import py_compile; py_compile.compile('file.py', doraise=True)"
```

### 冷启动 DB 测试
```bash
python -c "
import tempfile, sqlite3
tmp = tempfile.mktemp(suffix='.sqlite3')
# ... test ...
os.unlink(tmp)
"
```

### 全文内容重复检查
```bash
python -c "
import hashlib
from extractor import extract_text
# ... scan all docs, group by full-text SHA256 ...
"
```

### 搜索功能端到端测试
```bash
python main.py find --config config.yaml --query "止损"
```

### Streamlit GUI 启动
```bash
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

---

## 测试结果汇总

| 日期 | 测试内容 | 通过/总数 | 备注 |
|------|----------|:---:|------|
| 2026-05-03 | GUI后端集成测试 | 38/39 | 1个Windows文件锁(非功能bug) |
| 2026-05-03 | CLI命令测试 | 33/33 | 全部32个命令 --help通过 |
| 2026-05-03 | 端到端搜索测试 | 5/5 | |
| 2026-05-03 | 系统健康检查 | 6/6 | DB/API/磁盘/目录全部OK |
| 2026-05-04 | 冷启动chunk表测试 | pass | find_idea自动创建FTS表 |
| 2026-05-04 | analyzefolder路径修复 | 43 docs found | |
