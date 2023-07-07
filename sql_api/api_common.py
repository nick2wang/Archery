from rest_framework import viewsets, filters, views, serializers, status
from rest_framework.response import Response
from django.contrib.sessions.models import Session
from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from .serializers import SessionDeleteSerializer
from sql.models import Users
from datetime import datetime, timedelta
from mirage.crypto import Crypto
import logging

logger = logging.getLogger("default")


class SessionView(viewsets.ViewSetMixin, views.APIView):
    """
    SessionView
    """
    http_method_names = ["get", "post"]

    @extend_schema(
        summary="获取用户会话列表",
        description="获取用户会话列表",
        request=None,
        responses=None,
        parameters=[
            OpenApiParameter(name="is_online", description="是否在线", required=True, type=bool),
        ]
    )
    def list(self, request):
        is_online = request.query_params.get("is_online")

        if not is_online:
            raise serializers.ValidationError({"errors": "缺少必要参数：is_online"})

        if is_online == "true":
            sessions = Session.objects.filter(expire_date__gt=datetime.now()).order_by("-expire_date")
        else:
            sessions = Session.objects.filter(expire_date__lte=datetime.now()).order_by("-expire_date")
        session_list = []
        for s in sessions:
            extra = s.get_decoded()
            user_id = extra.get("_auth_user_id")
            if user_id:
                try:
                    user = Users.objects.get(pk=user_id)
                except Users.DoesNotExist:
                    continue
                else:
                    user_auth_backend = extra.get("_auth_user_backend").split(".")[-1]
                    if user_auth_backend == "LDAPBackend":
                        user_source = "LDAP"
                    elif user_auth_backend == "ModelBackend":
                        user_source = "本地数据库"
                    else:
                        user_source = "其他"
                    session = {
                        "userid": user.id,
                        "username": user.username,
                        "display": user.display,
                        "user_source": user_source,
                        "encrypted_session_key": Crypto().encrypt(s.session_key),
                        "expire_date": s.expire_date,
                        "recent_active": s.expire_date - timedelta(seconds=settings.SESSION_COOKIE_AGE),
                        "is_current_session": True if request.session.session_key == s.session_key else False,
                    }
                    session_list.append(session)

        result = {
            "status": 0,
            "msg": "ok",
            "count": len(session_list),
            "results": session_list,
        }

        return Response(result)

    @extend_schema(
        summary="终止用户会话",
        description="终止用户会话",
        request=SessionDeleteSerializer,
        responses=None,
    )
    def terminate(self, request):
        serializer = SessionDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        encrypted_session_key = request.data.get("encrypted_session_key")
        decrypted_session_key = Crypto().decrypt(encrypted_session_key)
        session = Session.objects.get(pk=decrypted_session_key)
        if request.session.session_key == decrypted_session_key:
            raise serializers.ValidationError({"errors": "无法终止当前自己的会话"})
        else:
            session.expire_date=datetime.now()
            session.save(update_fields=["expire_date"])

        result = {
            "status": 0,
            "msg": "ok",
            "count": 0,
            "results": [],
        }

        return Response(result)
