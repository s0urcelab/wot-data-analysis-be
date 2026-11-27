FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    SQLITE_PATH=/wds/data/wot.db

# libdevil1c2 是 dds2png.deb 的运行库，与 master 分支的安装方式一致。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata libdevil1c2 libgcc-s1 libstdc++6 \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo Asia/Shanghai > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wds

COPY requirements.txt /wds/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY badgesModifier/dds2png.deb /tmp/dds2png.deb
RUN dpkg -i /tmp/dds2png.deb \
    || (apt-get update && apt-get install -y --no-install-recommends -f) \
    && rm -f /tmp/dds2png.deb \
    && rm -rf /var/lib/apt/lists/*

COPY . /wds
RUN mkdir -p /wds/data

EXPOSE 7001

CMD ["uvicorn", "wotapp.main:app", "--host", "0.0.0.0", "--port", "7001"]
