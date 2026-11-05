# Palika Project Management — SaaS

One installation serves many palikas. Each palika gets its **own PostgreSQL schema**
(its own copy of every table), created automatically when it is added.

| Site | URL (local) | Who |
|---|---|---|
| SaaS Manager | http://localhost:8000/ | You (service provider) |
| Palika site | http://&lt;code&gt;.localhost:8000/ | Each palika's staff |

## First-time setup (Windows, PowerShell)

```powershell
cd "D:\Django Project\BagmatiProjectManagement"

# 1. Database (port 5433, separate from GIWMS)
docker compose up -d

# 2. Python packages
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Shared tables + SaaS manager login
python manage.py migrate_schemas --shared
python manage.py setup_saas --mobile 98XXXXXXXX --password <your-password>

# 4. Bring the old Bagmati data across (optional)
python manage.py create_palika --code bagmati --name बागमती --district ललितपुर --address भट्टेडाँडा --admin-mobile 9845184845
python manage.py import_sqlite --code bagmati --sqlite db.sqlite3

# 5. Run
python manage.py runserver
```

After the import, Bagmati users log in with their **old** mobile numbers and passwords.

## Adding a new palika

SaaS Manager → **+ नयाँ पालिका**. Fill in the name, district and code (e.g. `bagmati`),
and the first admin's mobile number. On save the system automatically:

1. creates the schema `<code>` and all tables,
2. adds the domain `<code>.<BASE_DOMAIN>`,
3. adds default data (procurement types, budget types, project types, current fiscal year, wards),
4. creates the admin user and shows the password **once**.

Command-line alternative: `python manage.py create_palika --code ... --name ... --admin-mobile ...`

## From the SaaS Manager you can

- see all palikas with project and user counts,
- edit a palika's name, address, logo, CAO name, bank, plan and paid-until date,
- deactivate a palika (its site shows "inactive" and nobody can log in),
- reset a palika admin's password,
- add extra domains (e.g. `pms.bagmatimun.gov.np`).

## What changed from the single-palika version

- SQLite → PostgreSQL with `django-tenants`; secrets moved to `.env`.
- New app `tenants/` (Palika, Domain, provisioning, SaaS manager pages, commands).
- "बागमती गाउँपालिका", the address, district, गाउँसभा etc. in all letters now come from the
  palika's own settings (`{{ palika.full_name }}`, `{{ palika.executive_office }}` …).
  Choosing नगरपालिका switches to नगर कार्यपालिका / नगरसभा automatically.
- Uploaded files are stored per palika: `media/<code>/...`.
- **Every palika page now requires login.** Before this, most pages opened without logging in.
- A backup of the original project is in `_backup_before_saas/`.

## Production notes

- Set `DJANGO_DEBUG=False`, a real `BASE_DOMAIN` (e.g. `pms.example.com`) and
  `CSRF_TRUSTED_ORIGINS=https://pms.example.com,https://*.pms.example.com`.
- DNS: a wildcard record `*.pms.example.com` pointing to the server, plus a wildcard SSL certificate.
- Serve `/media/` through the web server only after login checks, or keep it behind Django.
- The old MySQL password that was written in `settings.py` should be changed on that server.

## Known limits to address in the workflow phase

- Role checks: logged-in users of one role can still open other roles' pages by URL.
- Some pages return a server error (500) instead of "not found" when an id does not exist.
- Procurement types must keep ids 1/2/3 (उपभोक्ता समिति / बोलपत्र / दरभाउपत्र); the code filters by these ids.
