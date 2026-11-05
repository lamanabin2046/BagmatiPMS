from django.contrib import admin

# Register your models here.
from projects.models import *
from .models import *
admin.site.register(UserCommittee)
admin.site.register(CostEstimate)
admin.site.register(FinalPayment)
admin.site.register(WardRecommendation)