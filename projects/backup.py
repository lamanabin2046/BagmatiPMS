"""पालिकाको ब्याकअप — डाटा (JSON) + अपलोड गरिएका फाइल एउटै zip मा, पालिकाअनुसार छुट्टै फोल्डरमा.

  * BACKUP_DIR (पूर्वनिर्धारित <project>/backups/<schema>/) — media बाहिर, वेबबाट सिधै खुल्दैन
  * हरेक दिन cron: python manage.py backup_palikas   (सबै सक्रिय पालिका)
  * BACKUP_KEEP (पूर्वनिर्धारित १४) भन्दा पुराना आफैँ हट्छन्
  * पुनर्स्थापना: python manage.py restore_palika <schema> <zip> --confirm  (खाली पालिकामा मात्र)
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings

APPS = ["accounts", "projects", "usercommittee", "biddings", "quatation", "letters", "auth.group"]


def root():
    return Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))


def keep():
    return int(getattr(settings, "BACKUP_KEEP", 14))


def folder(schema):
    p = root() / schema
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_backups(schema):
    out = []
    for f in sorted(folder(schema).glob("*.zip"), reverse=True):
        st = f.stat()
        out.append({"name": f.name, "size": st.st_size, "at": datetime.fromtimestamp(st.st_mtime)})
    return out


def latest_age_hours(schema):
    b = list_backups(schema)
    return None if not b else (datetime.now() - b[0]["at"]).total_seconds() / 3600


def safe_path(schema, name):
    """डाउनलोड / मेटाउन — नाम यही फोल्डरभित्रको .zip मात्र."""
    if not name or "/" in name or "\\" in name or not name.endswith(".zip") or name.startswith("."):
        return None
    p = folder(schema) / name
    return p if p.is_file() else None


def make_backup(schema):
    """zip बनाउँछ र (path, counts) फर्काउँछ."""
    from django.core.management import call_command
    from django_tenants.utils import schema_context

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder(schema) / f"{schema}-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data.json")
        with schema_context(schema):
            call_command("dumpdata", *APPS, natural_foreign=True, output=data, verbosity=0)
        with open(data, encoding="utf-8") as fh:
            objs = json.load(fh)
        counts = {}
        for o in objs:
            counts[o["model"]] = counts.get(o["model"], 0) + 1
        media = Path(settings.MEDIA_ROOT) / schema
        n_files = 0
        partial = target.with_suffix(".part")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(data, "data.json")
            if media.is_dir():
                for f in media.rglob("*"):
                    if f.is_file():
                        z.write(f, "media/" + f.relative_to(media).as_posix())
                        n_files += 1
            z.writestr("meta.json", json.dumps({"schema": schema, "created": stamp, "objects": len(objs), "files": n_files,
                                                "counts": counts}, ensure_ascii=False, indent=1))
        partial.rename(target)
    prune(schema)
    return target, {"objects": len(objs), "files": n_files, "projects": counts.get("projects.project", 0)}


def prune(schema):
    files = sorted(folder(schema).glob("*.zip"), reverse=True)
    for f in files[keep():]:
        f.unlink(missing_ok=True)


def restore(schema, zip_path):
    """खाली पालिका schema मा मात्र — (objects, files)."""
    from django.core.management import call_command
    from django_tenants.utils import schema_context

    from .models import Project

    with schema_context(schema):
        if Project.objects.exists():
            raise ValueError(f"{schema} मा पहिले नै योजना छन् — खाली पालिकामा मात्र पुनर्स्थापना गर्न मिल्छ।")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as z:
        z.extract("data.json", tmp)
        with schema_context(schema):
            call_command("loaddata", os.path.join(tmp, "data.json"), verbosity=0)
        media = Path(settings.MEDIA_ROOT) / schema
        n = 0
        for name in z.namelist():
            if name.startswith("media/") and not name.endswith("/") and ".." not in name:
                dest = media / name[len("media/"):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(dest, "wb") as out:
                    out.write(src.read())
                n += 1
        meta = json.loads(z.read("meta.json"))
    return meta.get("objects", 0), n
