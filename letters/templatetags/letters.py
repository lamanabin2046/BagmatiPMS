"""{% editable_letter "uc.bank_letter" "बैंक पत्र" %} …मूल पाठ… {% endeditable_letter %}

देखाउने क्रम: १) यो पत्रको सम्पादित पाठ  २) पालिकाको ढाँचा (placeholder भरेर)  ३) मूल पाठ।
सम्पादन अनुमति भएकालाई पेजमा "प्रिन्ट गर्नुहोस् / सम्पादन" toolbar र editor पनि आउँछ (छापिँदैन)।
"""
import json

from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from ..placeholders import catalog, fill, tokenize

register = template.Library()


@register.tag
def editable_letter(parser, token):
    bits = token.split_contents()
    if len(bits) < 2:
        raise template.TemplateSyntaxError("editable_letter needs a key")
    key = bits[1].strip("\"'")
    title = bits[2].strip("\"'") if len(bits) > 2 else key
    nodelist = parser.parse(("endeditable_letter",))
    parser.delete_first_token()
    return EditableLetterNode(key, title, nodelist)


def _perms(user):
    try:
        from accounts.permissions import user_perms

        return user_perms(user)
    except Exception:
        return frozenset()


class EditableLetterNode(template.Node):
    def __init__(self, key, title, nodelist):
        self.key, self.title, self.nodelist = key, title, nodelist

    def render(self, context):
        from ..signers import kind_for_key, signer

        kind = kind_for_key(self.key)
        if not kind:
            return self._render(context)
        # पत्रमा हस्ताक्षर गर्ने (CAO वा प्रत्यायोजित अधिकृत) — ढाँचामा {{signer_name}}, {{signer_post}} पनि
        sg = signer(kind)
        with context.push(signer=sg, signer_name=sg["name"], signer_post=sg["post"], signer_note=sg["note"]):
            return self._render(context)

    def _render(self, context):
        from ..models import LetterOverride, LetterTemplate

        request = context.get("request")
        ref = request.path if request is not None else ""
        loop = context.get("forloop")
        if loop:
            ref += f"#{loop['counter']}"
        default_html = self.nodelist.render(context)

        override = LetterOverride.objects.filter(key=self.key, ref=ref).first()
        tpl = LetterTemplate.objects.filter(key=self.key).first()
        if override:
            body, state = override.html, "override"
        elif tpl:
            body, state = fill(tpl.html, context), "template"
        else:
            body, state = default_html, "default"

        out = (f'<div class="letter-editable" data-letter-key="{self.key}" data-letter-ref="{ref}" '
               f'data-letter-state="{state}">{body}</div>')

        user = getattr(request, "user", None)
        perms = _perms(user) if user is not None else frozenset()
        can_letter, can_tpl = "letters.edit" in perms, "letters.templates" in perms

        if can_letter or can_tpl:
            items = catalog(context)
            data = {
                "key": self.key, "ref": ref, "title": self.title, "state": state,
                "current": body,
                "template": tpl.html if tpl else tokenize(default_html, items),
                "template_saved": bool(tpl), "template_auto": not tpl,
                "override_saved": bool(override),
                "catalog": items,
                "can_letter": can_letter, "can_template": can_tpl,
            }
            payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            out += f'<script type="application/json" class="letter-data">{payload}</script>'

        # toolbar (प्रिन्ट गर्नुहोस् / फिर्ता / सम्पादन) + editor: एक पेजमा एक पटक मात्र
        if not context.render_context.get("letters_toolbar"):
            context.render_context["letters_toolbar"] = True
            out = render_to_string("letters/_toolbar.html", {
                "request": request, "can_edit": can_letter or can_tpl}) + out
        return mark_safe(out)
