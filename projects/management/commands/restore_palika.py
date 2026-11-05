"""ब्याकअपबाट खाली पालिकामा पुनर्स्थापना:
    python manage.py restore_palika <schema> <zip फाइल> --confirm
पहिले create_palika ले नयाँ (खाली) पालिका बनाउनुहोस्; योजना भएको पालिकामा चल्दैन।
"""
from django.core.management.base import BaseCommand, CommandError

from projects import backup


class Command(BaseCommand):
    help = "ब्याकअप zip बाट खाली पालिकामा डाटा र फाइल पुनर्स्थापना"

    def add_arguments(self, parser):
        parser.add_argument("schema")
        parser.add_argument("zip")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, schema, zip, **opts):
        if not opts["confirm"]:
            raise CommandError("--confirm बिना चल्दैन।")
        try:
            n, files = backup.restore(schema, zip)
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write(f"✓ {schema}: {n} रेकर्ड, {files} फाइल पुनर्स्थापना भयो।")
