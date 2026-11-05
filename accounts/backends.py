from django.contrib.auth.backends import ModelBackend
from ambulance.models import CustomUser

class MobileBackend(ModelBackend):
    def authenticate(self, request, mobile=None, password=None, **kwargs):
        try:
            user = CustomUser.objects.get(mobile=mobile)
            if user.check_password(password):
                return user
        except CustomUser.DoesNotExist:
            return None