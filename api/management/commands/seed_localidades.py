"""Popula a tabela de localidades e tenta o geocode confiável do Google.

    python manage.py seed_localidades            # cria as faltantes + geocoda
    python manage.py seed_localidades --aplicar   # já estampa as confiáveis no mapa

As localidades que o Google não resolve com confiança ficam PENDENTE para
você marcar na mão pela tela do mapa.
"""

import time

from django.core.management.base import BaseCommand

from api.models import LocalidadeBeneficiario
from api.services.localidades import (
    aplicar_todas,
    geocodificar_localidade,
    sincronizar_localidades,
)


class Command(BaseCommand):
    help = 'Popula localidades dos beneficiários e geocodifica as confiáveis.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar',
            action='store_true',
            help='Após geocodificar, estampa as coordenadas confiáveis nos beneficiários.',
        )

    def handle(self, *args, **options):
        criadas, total = sincronizar_localidades()
        self.stdout.write(f'Localidades: {total} no total ({criadas} criadas agora).')

        confiaveis = 0
        for loc in LocalidadeBeneficiario.objects.all():
            try:
                fonte = geocodificar_localidade(loc)
                if fonte == LocalidadeBeneficiario.FONTE_GOOGLE:
                    confiaveis += 1
                    self.stdout.write(f'  ✓ {loc.nome}')
                else:
                    self.stdout.write(f'  ⚠ {loc.nome} — {loc.google_formatted}')
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(f'  ! {loc.nome} — erro: {exc}'))
            time.sleep(0.08)

        pendentes = LocalidadeBeneficiario.objects.filter(
            latitude__isnull=True
        ).count()
        self.stdout.write(self.style.SUCCESS(
            f'Geocode confiável: {confiaveis} | pendentes de revisão manual: {pendentes}'
        ))

        if options['aplicar']:
            resumo = aplicar_todas()
            self.stdout.write(self.style.SUCCESS(
                f'Aplicado: {resumo["enderecos"]} endereços em '
                f'{resumo["localidades"]} localidades.'
            ))
