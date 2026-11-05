# cPanel मा Deploy र CI/CD

## १. Database: हरेक पालिकाका लागि छुट्टै database चाहिँदैन

यो SaaS **एउटै PostgreSQL database** मा चल्छ। हरेक पालिकाको भने त्यसभित्र **आफ्नै schema** हुन्छ
(आफ्नै तालिकाहरूको पूरा प्रति)।

```
database: sunkosh1_pms
├── public          ← SaaS Manager: पालिकाको सूची, domain, SaaS लगइन
├── bagmati         ← बागमती गाउँपालिकाका सबै तालिका
├── makawanpurgadhi ← मकवानपुरगढीका सबै तालिका
└── ...             ← SaaS Manager मा "+ नयाँ पालिका" गर्दा आफैं बन्छ
```

- cPanel मा database **एक पटक मात्र** बनाउने हो।
- नयाँ पालिका थप्दा schema, तालिका, सुरुको data र admin user आफैं बन्छन्।
- `migrate_schemas` ले नयाँ migration सबै पालिकामा एकैपटक लगाउँछ।
- Upload भएका फाइल पनि `media/<पालिका>/...` मा छुट्टै बस्छन्।
- एउटा पालिकाले अर्को पालिकाको फाइल वा data देख्न सक्दैन।

## २. सुरु गर्नुअघि hosting मा हेर्नुहोस्

| चाहिने | cPanel मा कहाँ | नभए |
|---|---|---|
| **PostgreSQL** (MySQL चल्दैन) | Databases → *PostgreSQL Databases* | hosting लाई PostgreSQL खोल्न भन्नुहोस्, वा VPS |
| **Python 3.10+** (यो server: 3.10) | Software → *Setup Python App* | hosting लाई सोध्नुहोस् |
| Terminal (पहिलो पटकका लागि) | Advanced → *Terminal* | SSH Access |

## ३. पहिलो पटक server तयार गर्ने (एक पटक मात्र)

### ३.१ Database
1. **PostgreSQL Databases** मा जानुहोस्:
   - database `pms` बनाउनुहोस् (पूरा नाम `sunkosh1_pms` हुन्छ)।
   - user `pms` बनाउनुहोस्, बलियो password राख्नुहोस्।
   - user लाई database मा थपेर **ALL PRIVILEGES** दिनुहोस्।
2. PostgreSQL **15 वा नयाँ** भए database user ले `public` schema मा तालिका बनाउन सक्दैन।
   - **phpPgAdmin** (cPanel को मुख्य लगइनले खुल्छ) बाट `sunkosh1_pms` database खोल्नुहोस्।
   - SQL मा एक पटक यो चलाउनुहोस्:
     ```sql
     GRANT ALL ON SCHEMA public TO sunkosh1_pms;
     ```
   - यसो नगरे migrate गर्दा `permission denied for schema public` आउँछ।

### ३.२ Domain
- `BASE_DOMAIN` (जस्तै `pms.example.com`) मा SaaS Manager चल्छ।
- हरेक पालिका `<code>.pms.example.com` मा चल्छ (जस्तै `bagmati.pms.example.com`)।
- cPanel → **Domains** मा `pms.example.com` subdomain बनाउनुहोस्।

### ३.३ Python App
cPanel → **Setup Python App** → *Create Application*:
- Python version: **3.10**
- Application root: **`ProjectManagement`** (Git repo भएकै फोल्डर)
- Application URL: `pms.example.com`
- Application startup file: **`passenger_wsgi.py`**, Entry point: **`application`**

बनाएपछि माथि देखिने `source /home2/sunkosh1/virtualenv/ProjectManagement/3.10/bin/activate`
बाटो टिप्नुहोस्।

### ३.४ `.env` (server मा मात्र, Git मा कहिल्यै होइन)
File Manager → `ProjectManagement/` भित्र `.env` बनाउनुहोस्:
```
DJANGO_SECRET_KEY=<लामो random string>
DJANGO_DEBUG=False
BASE_DOMAIN=pms.example.com
DJANGO_ALLOWED_HOSTS=pms.example.com,.pms.example.com
CSRF_TRUSTED_ORIGINS=https://pms.example.com,https://*.pms.example.com
SECURE_COOKIES=True
DB_NAME=sunkosh1_pms
DB_USER=sunkosh1_pms
DB_PASSWORD=<३.१ को password>
DB_HOST=localhost
DB_PORT=5432
DEPLOY_VENV=/home2/sunkosh1/virtualenv/ProjectManagement/3.10
NID_API_URL=
```
- Secret key बनाउन: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- फाइलको permission **600** राख्नुहोस्।

### ३.५ पहिलो install (cPanel Terminal)
```bash
cd ~/ProjectManagement
source ~/virtualenv/ProjectManagement/3.10/bin/activate
pip install -r requirements.txt
python manage.py migrate_schemas --shared
python manage.py setup_saas --mobile 98XXXXXXXX --password '<SaaS manager password>'
bash scripts/deploy.sh
```
अब `https://pms.example.com` मा SaaS Manager खुल्छ।

### ३.६ हरेक नयाँ पालिका — एकै command (सिफारिस)
```bash
cd ~/ProjectManagement
bash scripts/new_palika.sh --code sunapati --name सुनापती --district रामेछाप \
     --address हिलेदेवी --wards 5 --admin-mobile 98XXXXXXXX
```
यसले पालिका (schema, तालिका, वडा, admin) बनाउँछ, cPanel मा `<code>.<BASE_DOMAIN>` subdomain
(BASE_DOMAIN कै public फोल्डरमा) थप्छ र AutoSSL सुरु गर्छ। admin पासवर्ड अन्त्यमा **एकपटक मात्र** देखिन्छ।
`--type नगरपालिका` (default गाउँपालिका) पनि दिन मिल्छ। फेरि चलाउँदा भइसकेको चरण छोडिन्छ।

**ध्यान:** कुनै पनि domain को Document Root कहिल्यै `ProjectManagement` (code फोल्डर) नराख्नुहोस् —
सधैं BASE_DOMAIN कै public फोल्डर (जस्तै `pms.sunkoshimun.com`)।

### ३.६.१ हातैले गर्ने तरिका
1. **SaaS Manager → + नयाँ पालिका**, code: `bagmati`। Schema, तालिका र admin आफैं बन्छन्।
2. cPanel → **Domains** → Create → `bagmati.pms.example.com`। Document root **`pms.example.com`
   कै document root** राख्नुहोस्, ताकि उही Python app चलोस्। AutoSSL ले HTTPS आफैं दिन्छ।
   - hosting ले wildcard (`*.pms.example.com`) र wildcard SSL दिन्छ भने एकपटक गरे पुग्छ।
3. पालिकाको आफ्नै domain (जस्तै `pms.bagmatimun.gov.np`) चलाउने भए:
   - DNS server तर्फ point गर्नुहोस्।
   - cPanel मा उही document root भएको alias/domain थप्नुहोस्।
   - SaaS Manager → पालिका → domain थप्नुहोस्।

### ३.७ पुरानो (local) data सार्ने (चाहिए मात्र)
```bash
# आफ्नो कम्प्युटरमा
pg_dump -h 127.0.0.1 -p 5433 -U bpm --no-owner --no-privileges bpm | gzip > pms.sql.gz
# media फोल्डर zip गर्नुहोस्; दुवै File Manager बाट ~/ProjectManagement/ मा upload गर्नुहोस्
# server Terminal मा (३.५ को migrate अघि, खाली database मा)
gunzip -c pms.sql.gz | psql -h localhost -U sunkosh1_pms sunkosh1_pms
```
- त्यसपछि media zip extract गर्नुहोस्।
- SaaS Manager बाट हरेक पालिकाको production domain थप्नुहोस्।

## ४. CI/CD: GitHub मा push गरेपछि आफैं deploy

```
git push (main)
  → GitHub Actions: PostgreSQL मा जाँच (check, migration छुटेको?, नयाँ पालिका बन्छ?, static)
  → पास भए: cPanel API → Git "Update from Remote" (git pull)
  → cPanel API → "Deploy HEAD Commit" → .cpanel.yml → scripts/deploy.sh:
       database backup (~/backups/pms, पछिल्ला १४)
       → pip install → सबै पालिकामा migrate → collectstatic → app restart
```
SSH चाहिँदैन। cPanel को API token (HTTPS, port 2083) मात्र प्रयोग हुन्छ।

### ४.१ एक पटकको setup
1. cPanel → **Git Version Control** → ProjectManagement → **Manage**:
   - *Pull or Deploy* मा Remote URL `https://github.com/lamanabin2046/BagmatiPMS` देखिनुपर्छ।
   - repo **private** बनाउनुहुन्छ भने cPanel को SSH key लाई GitHub मा *Deploy key* बनाउनुहोस्।
   - remote लाई `git@github.com:...` बनाउनुहोस्।
2. cPanel → Security → **Manage API Tokens** → Create:
   - नाम `github-deploy` राख्नुहोस् र token copy गर्नुहोस्।
   - यो एकपटक मात्र देखिन्छ, password जस्तै गोप्य राख्नुहोस्।
3. GitHub repo → Settings → **Secrets and variables → Actions** → New repository secret:

| Secret | मान |
|---|---|
| `CPANEL_HOST` | `fishtail.mysecurecloudserver.com` |
| `CPANEL_USER` | `sunkosh1` |
| `CPANEL_TOKEN` | माथिको token |
| `CPANEL_REPO_PATH` | `/home2/sunkosh1/ProjectManagement` |
| `SITE_URL` | `https://pms.example.com` (ऐच्छिक — deploy पछि site चल्यो कि जाँच्न) |

### ४.२ दैनिक काम
```bash
git add -A
git commit -m "..."
git push
```
- GitHub → **Actions** मा प्रगति हेर्नुहोस्। हरियो भए deploy भयो।
- हातैले चलाउन: GitHub → Actions → *Test and deploy to cPanel* → Run workflow।
- cPanel बाटै गर्न: Git Version Control → Manage → Pull or Deploy → **Update from Remote** → **Deploy HEAD Commit**।

## ५. समस्या आए

| हेर्ने ठाउँ | के छ |
|---|---|
| `~/ProjectManagement/logs/deploy.log` | हरेक deploy को पूरा output |
| `~/ProjectManagement/logs/django.log` | app का त्रुटि |
| `~/ProjectManagement/stderr.log` | Passenger (app सुरु नै नभए) |
| `~/backups/pms/` | migration अघिका database backup |

- App restart: `touch ~/ProjectManagement/tmp/restart.txt`, वा Setup Python App → Restart।
- Backup फर्काउन: `gunzip -c ~/backups/pms/<file>.sql.gz | psql -h localhost -U sunkosh1_pms sunkosh1_pms`।
  यो खाली database मा मात्र गर्नुहोस्।
- **Server मा फाइल हातैले नसच्याउनुहोस्।** cPanel ले फाइल बदलिएको repo deploy गर्दैन। सधैं Git बाट पठाउनुहोस्।
- "Deploy HEAD Commit" बटन बन्द देखिए, वा API ले deploy नगरे: Terminal मा `cd ~/ProjectManagement && git status` चलाउनुहोस्।
  बदलिएको फाइल देखिए (जस्तै cPanel ले बदलेको `passenger_wsgi.py`) `git checkout -- <file>` गरेर फर्काउनुहोस्।
