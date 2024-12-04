FROM library/python:3.9.10-bullseye
MAINTAINER wjy
ENV TZ Asia/Shanghai
SHELL ["/bin/bash", "-c"]
COPY . /data/archery/

WORKDIR /data/

COPY setup.sh /data/setup.sh
RUN chmod +x /data/setup.sh \
    && /data/setup.sh \
    && rm -rf /data/setup.sh

RUN apt-get install -yq --no-install-recommends \
    && apt-get install vim unixodbc-dev -y \
    && source venv4archery/bin/activate \
    && pip install --no-cache-dir -r /data/archery/requirements.txt -i https://mirrors.ustc.edu.cn/pypi/web/simple/ \
    && pip install --no-cache-dir "redis>=4.1.0" -i https://mirrors.ustc.edu.cn/pypi/web/simple/ \
    && cp -f /data/archery/supervisord.conf /etc/ \
    && mv /data/sqladvisor /data/archery/src/plugins/ \
    && mv /data/soar /data/archery/src/plugins/ \
    && mv /data/my2sql /data/archery/src/plugins/ \
    && apt-get -yq remove gcc curl \
    && apt-get clean \
    && rm -rf /var/cache/apt/* \
    && rm -rf /root/.cache \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf ~/.cache/pip

EXPOSE 8888

ENTRYPOINT ["bash", "/data/archery/startup.sh"]
