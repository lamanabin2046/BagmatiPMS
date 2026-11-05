#!/bin/bash
# नयाँ पालिका एकै command मा: (१) पालिका + schema + admin  (२) cPanel subdomain  (३) HTTPS (AutoSSL)
#
# प्रयोग (cPanel Terminal):
#   bash scripts/new_palika.sh --code sunapati --name सुनापती --district रामेछाप \
#        --address हिलेदेवी --wards 5 --admin-mobile 98XXXXXXXX
#
# ऐच्छिक: --type नगरपालिका (default गाउँपालिका)  --province "बागमती प्रदेश"  --name-en Sunapati
#         --admin-password '...' (नदिए random बन्छ र अन्त्यमा देखाइन्छ)
# फेरि चलाउँदा: पालिका पहिले नै भए त्यो चरण छोडेर subdomain / HTTPS मात्र मिलाउँछ।
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
die() { echo "✗ $*" >&2; exit 1; }
envval() { { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

# ---------- arguments ----------
CODE="" ; ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --code) CODE="${2:-}"; ARGS+=("$1" "${2:-}"); shift 2 ;;
    --name|--type|--name-en|--district|--address|--province|--wards|--admin-mobile|--admin-password)
      [ $# -ge 2 ] || die "$1 को मान दिनुहोस्"; ARGS+=("$1" "$2"); shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) die "अज्ञात option: $1  (मद्दत: bash scripts/new_palika.sh --help)" ;;
  esac
done
[ -n "$CODE" ] || die "--code चाहिन्छ (जस्तै --code sunapati)"
[[ "$CODE" =~ ^[a-z][a-z0-9]{1,30}$ ]] || die "--code मा अंग्रेजी सानो अक्षर/अङ्क मात्र (जस्तै sunapati)"
printf '%s\n' "${ARGS[@]}" | grep -qx -- '--name' || die "--name चाहिन्छ (जस्तै --name सुनापती)"
printf '%s\n' "${ARGS[@]}" | grep -qx -- '--admin-mobile' || die "--admin-mobile चाहिन्छ"

[ -f .env ] || die ".env छैन"
BASE="$(envval BASE_DOMAIN)"; [ -n "$BASE" ] || die ".env मा BASE_DOMAIN छैन"
FQDN="$CODE.$BASE"

VENV="$(envval DEPLOY_VENV)"; VENV="${VENV%/}"
[ -f "$VENV/bin/activate" ] || VENV="$(ls -d "$HOME"/virtualenv/"$(basename "$APP_DIR")"/*/ 2>/dev/null | sort -V | tail -1)"; VENV="${VENV%/}"
[ -f "$VENV/bin/activate" ] || die "virtualenv भेटिएन — .env मा DEPLOY_VENV राख्नुहोस्"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "== $FQDN =="

# ---------- १. पालिका (schema + तालिका + सुरुको data + admin) ----------
EXISTS="$(python manage.py shell -c "from tenants.models import Palika; print(Palika.objects.filter(schema_name='$CODE').exists())" 2>&1 | tail -1)"
case "$EXISTS" in True|False) ;; *) die "database मा जोडिन सकिएन: $EXISTS";; esac
if [ "$EXISTS" = "True" ]; then
  echo "• पालिका '$CODE' पहिले नै छ — यो चरण छोडियो (admin पासवर्ड चाहिए SaaS Manager बाट reset गर्नुहोस्)।"
else
  echo "• पालिका बनाउँदै (एक-दुई मिनेट लाग्न सक्छ)…"
  python manage.py create_palika "${ARGS[@]}" || die "पालिका बन्न सकेन (माथिको त्रुटि हेर्नुहोस्)"
fi

# ---------- २. cPanel subdomain (BASE_DOMAIN कै public फोल्डरमा) ----------
command -v uapi >/dev/null 2>&1 || die "uapi भेटिएन — cPanel → Domains मा $FQDN हातैले बनाउनुहोस् (Document Root: $BASE को जस्तै)"
DOCROOT="$(uapi DomainInfo single_domain_data domain="$BASE" 2>/dev/null | awk '/documentroot:/{print $2; exit}')"
[ -n "$DOCROOT" ] || die "$BASE को document root भेटिएन"
[ "$DOCROOT" != "$APP_DIR" ] || die "$BASE को document root code फोल्डर ($APP_DIR) छ — पहिले public फोल्डरमा सार्नुहोस्"
MAIN="$(uapi DomainInfo list_domains 2>/dev/null | awk '/main_domain:/{print $2; exit}')"
[ -n "$MAIN" ] || die "मुख्य domain भेटिएन"
case "$FQDN" in *".$MAIN") ;; *) die "$FQDN मुख्य domain $MAIN अन्तर्गत छैन — cPanel मा हातैले थप्नुहोस्";; esac
LABEL="${FQDN%.$MAIN}"
REL="${DOCROOT#$HOME/}"

if uapi DomainInfo single_domain_data domain="$FQDN" 2>/dev/null | grep -q "documentroot:"; then
  HAVE="$(uapi DomainInfo single_domain_data domain="$FQDN" | awk '/documentroot:/{print $2; exit}')"
  if [ "$HAVE" = "$DOCROOT" ]; then
    echo "• subdomain $FQDN पहिले नै छ (document root ठीक)।"
  else
    die "subdomain $FQDN पहिले नै छ तर document root फरक ($HAVE)। cPanel → Domains मा मेटाएर फेरि चलाउनुहोस्।"
  fi
else
  echo "• subdomain $FQDN बनाउँदै (document root: $REL)…"
  OUT="$(uapi SubDomain addsubdomain domain="$LABEL" rootdomain="$MAIN" dir="$REL" disallowdot=0 2>&1)"
  echo "$OUT" | grep -q "status: 1" || { echo "$OUT" >&2; die "subdomain बन्न सकेन"; }
fi

# ---------- ३. HTTPS ----------
echo "• AutoSSL सुरु गर्दै…"
uapi SSL start_autossl_check >/dev/null 2>&1 && echo "  (certificate आउन २–५ मिनेट लाग्छ)" \
  || echo "  AutoSSL सुरु भएन — cPanel → SSL/TLS Status → Run AutoSSL गर्नुहोस्।"

touch tmp/restart.txt 2>/dev/null || true
echo
echo "✓ तयार: https://$FQDN"
echo "  माथि देखिएको admin मोबाइल र पासवर्डले लगइन गर्नुहोस् (पासवर्ड एकपटक मात्र देखिन्छ)।"
