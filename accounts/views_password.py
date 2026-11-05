"""पासवर्ड बिर्सँदा — मोबाइलमा SMS कोड (OTP) पठाएर आफैँ नयाँ पासवर्ड बनाउने (लगइन नचाहिने)."""
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from . import security as sec

SESSION_KEY = "pw_reset_mobile"


def forgot(request):
    sms_on = sec.sms_settings() is not None
    if request.method == "POST" and sms_on:
        mobile = sec.norm_mobile(request.POST.get("mobile"))
        if len(mobile) != 10:
            messages.error(request, "१० अङ्कको मोबाइल नम्बर लेख्नुहोस्।")
            return redirect("forgot_password")
        status, secs = sec.request_otp(mobile, sec.client_ip(request))
        if status == "wait":
            messages.warning(request, f"कोड भर्खरै पठाइएको छ — {sec._np(secs)} सेकेन्डपछि मात्र फेरि माग्न सकिन्छ।")
        elif status == "limit":
            messages.error(request, "धेरै पटक कोड मागियो — एक घण्टापछि प्रयास गर्नुहोस् वा Admin लाई सम्पर्क गर्नुहोस्।")
            return redirect("forgot_password")
        elif status == "failed":
            messages.error(request, "SMS पठाउन सकिएन — केही बेरपछि प्रयास गर्नुहोस् वा Admin लाई सम्पर्क गर्नुहोस्।")
            return redirect("forgot_password")
        else:   # sent / unknown — दर्ता छ कि छैन नखुलाउने
            messages.success(request, "यो नम्बर प्रणालीमा दर्ता भएको भए ६ अङ्कको कोड SMS मा पठाइएको छ (१० मिनेट मान्य)।")
        request.session[SESSION_KEY] = mobile
        return redirect("forgot_password_verify")
    return render(request, "accounts/forgot_password.html", {"sms_on": sms_on})


def verify(request):
    mobile = request.session.get(SESSION_KEY)
    if not mobile:
        return redirect("forgot_password")
    errors = []
    if request.method == "POST":
        code = request.POST.get("code", "")
        p1, p2 = request.POST.get("password1", ""), request.POST.get("password2", "")
        if p1 != p2:
            errors.append("नयाँ पासवर्ड र पुष्टि मिलेन।")
        user = None
        if not errors:
            user, err = sec.verify_otp(mobile, code)
            if err:
                errors.append(err)
        if user is not None and not errors:
            try:
                validate_password(p1, user)
            except ValidationError as e:
                errors += [_np_msg(m) for m in e.messages]
        if user is not None and not errors:
            user.set_password(p1)          # अन्य सबै उपकरणको पुरानो लगइन आफैँ समाप्त हुन्छ (session hash बदलिन्छ)
            user.save(update_fields=["password"])
            sec.consume_otp(user)
            sec.clear_failures(user.mobile)
            try:
                from usercommittee.models import ActivityLog
                ActivityLog.objects.create(user=user, action="update", model_name="प्रयोगकर्ता (पासवर्ड रिसेट)", object_id=user.pk,
                                           object_repr=user.mobile, note=f"SMS OTP बाट आफैँ पासवर्ड बदलियो · {sec.client_ip(request)}")
            except Exception:
                pass
            request.session.pop(SESSION_KEY, None)
            if request.user.is_authenticated:
                logout(request)
            messages.success(request, "पासवर्ड बदलियो ✅ — नयाँ पासवर्डले लगइन गर्नुहोस्। अरू उपकरणमा खुला लगइन बन्द भयो।")
            return redirect("login")
    return render(request, "accounts/forgot_password_verify.html", {"mobile": mobile, "errors": errors,
                                                                     "masked": mobile[:3] + "****" + mobile[-3:]})


def _np_msg(m):
    """Django को अङ्ग्रेजी पासवर्ड सन्देश → नेपाली."""
    low = m.lower()
    if "too short" in low:
        return "पासवर्ड कम्तीमा ८ अक्षरको हुनुपर्छ।"
    if "too common" in low:
        return "यो पासवर्ड धेरै सामान्य छ — अर्को छान्नुहोस्।"
    if "entirely numeric" in low:
        return "पासवर्डमा अङ्क मात्र हुनु हुँदैन — अक्षर पनि राख्नुहोस्।"
    if "too similar" in low:
        return "पासवर्ड मोबाइल नम्बर / नामसँग धेरै मिल्यो — अर्को छान्नुहोस्।"
    return m
