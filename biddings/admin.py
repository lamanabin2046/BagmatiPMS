from django.contrib import admin



from .models import *


# Register your models here.





admin.site.register(SealedBid)  
admin.site.register(Contract)
admin.site.register(PerformanceBondRequirement) 
admin.site.register(PerformanceBondIssued)
admin.site.register(AdvancePayment)
admin.site.register(AdvanceBankGuarantee)
admin.site.register(PerformanceBondExtension)
admin.site.register(FinalPayment) 

admin.site.register(RunningEvaluation)









