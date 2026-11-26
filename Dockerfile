FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    SQLITE_PATH=/wds/data/wot.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo Asia/Shanghai > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wds

COPY requirements.txt /wds/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /wds
RUN mkdir -p /wds/data

EXPOSE 7001

CMD ["uvicorn", "wotapp.main:app", "--host", "0.0.0.0", "--port", "7001"]
