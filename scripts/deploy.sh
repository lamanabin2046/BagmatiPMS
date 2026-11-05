#!/bin/bash
# cPanel server मा नयाँ code लागू गर्ने: backup → packages → migrate (सबै पालिका) → static → restart.
#
# .cpanel.yml बाट (cPanel "Deploy HEAD Commit" / GitHub Actions) आफैं चल्छ।
# हातैले:  bash scripts/deploy.sh
#
# virtualenv: .env मा DEPLOY_VENV=/home2/<user>/virtualenv/ProjectManagement/3.11
#             (नराखे ~/virtualenv/<फोल्डरको नाम>/*/ मा आफैं खोजिन्छ)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(stamp)] ===== deploy $(git rev-parse --short HEAD 2>/dev/null || echo '?') in $APP_DIR ====="

if [ ! -f .env ]; then
  echo "ERROR: $APP_DIR/.env छैन। .env.example बाट बनाउनुहोस्।" >&2
  exit 1
fi
# .env बाट मान पढ्ने (source नगरी — मानमा space/चिन्ह भए पनि सुरक्षित)
envval() { { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

VENV="${DEPLOY_VENV:-$(envval DEPLOY_VENV || true)}"
if [ -z "$VENV" ]; then
  VENV="$(ls -d "$HOME"/virtualenv/"$(basename "$APP_DIR")"/*/ 2>/dev/null | sort -V | tail -1 || true)"
fi
VENV="${VENV%/}"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "ERROR: virtualenv भेटिएन ($VENV)। cPanel → Setup Python App बनाएपछि .env मा DEPLOY_VENV राख्नुहोस्।" >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "[$(stamp)] python: $(python --version 2>&1) ($VENV)"

# १. database backup (migration अघि) — ~/backups/pms, पछिल्ला १४ वटा राखिन्छ
if command -v pg_dump >/dev/null 2>&1; then
  BK_DIR="$HOME/backups/pms"; mkdir -p "$BK_DIR"; chmod 700 "$BK_DIR"
  BK="$BK_DIR/pms-$(date +%Y%m%d-%H%M%S).sql.gz"
  if PGPASSWORD="$(envval DB_PASSWORD)" pg_dump -h "$(envval DB_HOST)" -p "$(envval DB_PORT)" \
       -U "$(envval DB_USER)" "$(envval DB_NAME)" | gzip > "$BK"; then
    chmod 600 "$BK"
    echo "[$(stamp)] backup: $BK ($(du -h "$BK" | cut -f1))"
  else
    echo "[$(stamp)] WARNING: backup असफल — deploy जारी छ" >&2; rm -f "$BK"
  fi
  ls -1t "$BK_DIR"/pms-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
else
  echo "[$(stamp)] WARNING: pg_dump छैन, backup भएन" >&2
fi

# २. packages
pip install --quiet --disable-pip-version-check -r requirements.txt

# ३. जाँच र migration — public schema + हरेक पालिकाको schema
python manage.py check --fail-level ERROR
python manage.py migrate_schemas --noinput

# ४. static
python manage.py collectstatic --noinput --verbosity 0

# ५. Passenger restart
mkdir -p tmp logs
touch tmp/restart.txt
echo "[$(stamp)] ===== deploy सकियो ====="
