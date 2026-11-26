# wot-data-analysis

坦克世界数据接口。FastAPI + SQLite。

## 开发

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn wotapp.main:app --port 7001
```

接口仍是原来的路径：`/apiVersion`、`/preData`、`/tankList`、`/history`、`/bindUser`、`/manual`、`/modVersion`、`/upload`、`/download`。评论已移除。

`POST /upload` 使用 multipart，字段名为 `dds` 和 `xml`。成功时 `data` 是输出文件名。`GET /download?n=&t=` 下载对应结果，`t` 为 `dds` 或 `xml`，下载完成后删除该文件。DDS 转换调用宿主提供的 `dds2png`，不随镜像安装。程序默认从 PATH 查找，也可用环境变量 `DDS2PNG` 指向映射进容器的可执行文件。

数据库文件默认是 `data/wot.db`，可用环境变量 `SQLITE_PATH` 修改。每天 12:00（上海时区）拉取官方百科和击杀环。设置 `SCHEDULER_ENABLED=0` 可关闭定时任务。`GET /manual` 会立刻返回并在后台跑同一套更新。

插件版本接口默认请求 `http://host.docker.internal:7003/wot/?json`，可用 `MOD_VERSION_URL` 覆盖。

## 从 MongoDB 迁移

只导入 `all_tanks` 和 `history_mastery`。评论和 `tanksgg_list` 不导入。脚本可重复执行。

```bash
MONGO_URL=mongodb://127.0.0.1:27017/wot SQLITE_PATH=data/wot.db python scripts/migrate_mongo.py
```

连接串里没有库名时，再设置 `MONGO_DB`。

## Docker

```bash
docker build -t wot-data-analysis .
docker run -p 7001:7001 -v wot-data:/wds/data wot-data-analysis
```

## 测试

```bash
pytest
```
