#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import requests
from django.http import JsonResponse
from django_redis import get_redis_connection
from common.config import SysConfig
from common.utils.permission import superuser_required
from sql.models import Users
from sql.utils.tasks import add_sync_ding_user_schedule

logger = logging.getLogger("default")
rs = get_redis_connection("default")


def get_access_token():
    """获取access_token:https://ding-doc.dingtalk.com/doc#/serverapi2/eev437"""
    # 优先获取缓存
    try:
        access_token = rs.execute_command(f"get ding_access_token")
    except Exception as e:
        logger.error(f"获取钉钉access_token缓存出错:{e}")
        access_token = None
    if access_token:
        return access_token.decode()
    # 请求钉钉接口获取
    sys_config = SysConfig()
    app_key = sys_config.get("ding_app_key")
    app_secret = sys_config.get("ding_app_secret")
    url = f"https://oapi.dingtalk.com/gettoken?appkey={app_key}&appsecret={app_secret}"
    resp = requests.get(url, timeout=3).json()
    if resp.get("errcode") == 0:
        access_token = resp.get("access_token")
        expires_in = resp.get("expires_in")
        rs.execute_command(f"SETEX ding_access_token {expires_in-60} {access_token}")
        return access_token
    else:
        logger.error(f"获取钉钉access_token出错:{resp}")
        return None


def get_unionid_by_userid(userid):
    """通过userid获取unionid"""
    access_token = get_access_token()
    url = f"https://oapi.dingtalk.com/user/get?access_token={access_token}&userid={userid}"
    resp = requests.get(url, timeout=3).json()
    if resp.get("errcode") == 0:
        unionid = resp.get("unionid")
        return unionid
    else:
        logger.error(f"获取钉钉用户unionid出错:{resp}")
        return None


def add_dingding_todo(title, workflow_url, user_from, user_to):
    """创建钉钉待办事项"""
    access_token = get_access_token()
    unionid_creator = get_unionid_by_userid(user_from)
    unionid_to = [get_unionid_by_userid(userid) for userid in user_to]
    api_url = f"https://api.dingtalk.com/v1.0/todo/users/{unionid_creator}/tasks"
    data = {
        "subject": title,
        "creatorId": unionid_creator,
        "executorIds": unionid_to,
        "detailUrl": {
            "appUrl": f"dingtalk://dingtalkclient/page/link?url={workflow_url}&pc_slide=false",
            "pcUrl": f"dingtalk://dingtalkclient/page/link?url={workflow_url}&pc_slide=false",
        },
        "isOnlyShowExecutor": "true",
        "priority": 20,
        "notifyConfigs": {"dingNotify": "1"},
    }
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": access_token,
    }
    resp = requests.post(url=api_url, json=data, headers=headers, timeout=5)
    resp_json = resp.json()
    logger.info(resp_json)
    if resp.status_code == 200:
        taskid = resp_json.get("id")
        return taskid
    else:
        logger.error(f"创建钉钉待办出错:{resp}")
        return None


def update_dingding_todo(taskid, user_from):
    """更新钉钉待办事项"""
    access_token = get_access_token()
    unionid_creator = get_unionid_by_userid(user_from)
    api_url = (
        f"https://api.dingtalk.com/v1.0/todo/users/{unionid_creator}/tasks/{taskid}"
    )
    data = {"done": "true"}
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": access_token,
    }
    resp = requests.put(url=api_url, json=data, headers=headers, timeout=5)
    resp_json = resp.json()
    logger.info(resp_json)
    if resp.status_code == 200:
        result = resp_json.get("result")
        return result
    else:
        logger.error(f"更新钉钉待办出错:{resp}")
        return None


def get_ding_user_id(username):
    """更新用户ding_user_id"""
    try:
        ding_user_id = rs.execute_command("GET {}".format(username.lower()))
        if ding_user_id:
            user = Users.objects.get(username=username)
            if user.ding_user_id != str(ding_user_id, encoding="utf8"):
                user.ding_user_id = str(ding_user_id, encoding="utf8")
                user.save(update_fields=["ding_user_id"])
    except Exception as e:
        logger.error(f"更新用户ding_user_id失败:{e}")


def get_dept_list_id_fetch_child(token, parent_dept_id):
    """获取所有子部门列表"""
    ids = [int(parent_dept_id)]
    url = (
        "https://oapi.dingtalk.com/department/list_ids?id={0}&access_token={1}".format(
            parent_dept_id, token
        )
    )
    resp = requests.get(url, timeout=3).json()
    if resp.get("errcode") == 0:
        for dept_id in resp.get("sub_dept_id_list"):
            ids.extend(get_dept_list_id_fetch_child(token, dept_id))
    return list(set(ids))


def sync_ding_user_id():
    """
    使用工号（username）登陆archery，并且工号对应钉钉系统中字段 "jobnumber"。
    所以可根据钉钉中 jobnumber 查到该用户的 ding_user_id。
    """
    sys_config = SysConfig()
    ding_dept_ids = sys_config.get("ding_dept_ids", "")
    username2ding = sys_config.get("ding_archery_username")
    token = get_access_token()
    if not token:
        return False
    # 获取全部部门列表
    sub_dept_id_list = []
    for dept_id in list(set(ding_dept_ids.split(","))):
        sub_dept_id_list.extend(get_dept_list_id_fetch_child(token, dept_id))
    # 遍历部门下的用户
    user_ids = []
    for sdi in sub_dept_id_list:
        url = f"https://oapi.dingtalk.com/user/getDeptMember?access_token={token}&deptId={sdi}"
        try:
            resp = requests.get(url, timeout=3).json()
            if resp.get("errcode") == 0:
                user_ids.extend(resp.get("userIds"))
            else:
                raise Exception(f"获取部门用户出错:{resp}")
        except Exception as e:
            raise Exception(f"获取部门用户出错:{e}")
    # 获取所有用户信息并缓存
    for user_id in list(set(user_ids)):
        url = (
            f"https://oapi.dingtalk.com/user/get?access_token={token}&userid={user_id}"
        )
        try:
            resp = requests.get(url, timeout=3).json()
            if resp.get("errcode") == 0:
                if not resp.get(username2ding):
                    logger.error(
                        f"钉钉用户信息不包含{username2ding}字段，无法获取id信息，请确认ding_archery_username配置{resp}"
                    )
                else:
                    rs.execute_command(
                        f"SETEX {resp.get(username2ding).lower()} 86400 {resp.get('userid')}"
                    )
            else:
                raise Exception(f"获取用户信息出错:{resp}")
        except Exception as e:
            raise Exception(f"获取用户信息出错:{e}")
    return True


@superuser_required
def sync_ding_user(request):
    """主动触发同步接口，同时写入schedule每天进行同步"""
    try:
        # 添加schedule并触发同步
        add_sync_ding_user_schedule()
        return JsonResponse({"status": 0, "msg": f"触发同步成功"})
    except Exception as e:
        return JsonResponse({"status": 1, "msg": f"触发同步异常:{e}"})
