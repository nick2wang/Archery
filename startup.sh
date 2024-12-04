#!/bin/bash

cd /data/archery

echo 切换python运行环境
source /data/venv4archery/bin/activate

echo 收集所有的静态文件到STATIC_ROOT
python3 manage.py collectstatic -v0 --noinput

echo 启动Django Q cluster
supervisord -c /etc/supervisord.conf

echo 启动服务
gunicorn -w 4 -b 0.0.0.0:8888 --timeout 600 archery.wsgi:application
