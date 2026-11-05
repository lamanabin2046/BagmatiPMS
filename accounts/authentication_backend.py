# ambulance/authentication_backend.py

from django.contrib.auth.backends import BaseBackend
from .models import CustomUser

class MobileAuthenticationBackend(BaseBackend):
    def authenticate(self, request, mobile=None, password=None):
        try:
            user = CustomUser.objects.get(mobile=mobile)
            if user.check_password(password):
                return user
        except CustomUser.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return None
