"""Geocodifica em lote os endereços de beneficiários, no servidor.

Uso:
    python manage.py geocodificar_beneficiarios            # só os pendentes/sem coordenada
    python manage.py geocodificar_beneficiarios --forcar   # recalcula também os já geocodificados (exceto pino MANUAL)
    python manage.py geocodificar_beneficiarios --limite 100

Pensado para rodar de uma vez (sem o loop lento do navegador). Com --forcar,
reaplica a lógica atual de fallback (bairro antes da rua) nos pontos antigos
que ficaram no bairro errado.
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from api.models import Endereco
from api.services.geocoding import geocodificar_endereco

STATUS_REPROCESSAVEIS = ['PENDENTE', 'ERRO', 'NAO_ENCONTRADO']


class Command(BaseCommand):
    help = 'Geocodifica endereços de beneficiários (preenche latitude/longitude).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--forcar',
            action='store_true',
            help='Recalcula também quem já tem coordenada (exceto pino MANUAL).',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Máximo de endereços a processar (0 = todos).',
        )

    def handle(self, *args, **options):
        forcar = options['forcar']
        limite = options['limite']

        qs = (
            Endereco.objects
            .filter(cidadao__beneficios_recebidos__isnull=False)
            .exclude(precisao_geocodificacao='MANUAL')
            .filter(
                Q(logradouro__gt='')
                | Q(bairro__gt='')
                | Q(comunidade_localidade__gt='')
                | Q(distrito__gt='')
            )
        )
        if not forcar:
            qs = qs.filter(
                Q(geocodificacao_status__in=STATUS_REPROCESSAVEIS)
                | Q(latitude__isnull=True)
                | Q(longitude__isnull=True)
            )
        qs = qs.select_related('cidadao').distinct().order_by('pk')

        total = qs.count()
        if limite:
            total = min(total, limite)
            qs = qs[:limite]

        self.stdout.write(
            f'Processando {total} endereço(s) | forçar={forcar}'
        )

        cont = {'OK': 0, 'NAO_ENCONTRADO': 0, 'ERRO': 0}
        inicio = time.monotonic()
        for i, endereco in enumerate(qs.iterator(), start=1):
            # No modo forçar, zera a coordenada antiga antes de recalcular:
            # se a nova tentativa falhar, o ponto não fica "preso" no lugar errado.
            if forcar:
                Endereco.objects.filter(pk=endereco.pk).update(
                    latitude=None, longitude=None, geocodificacao_status='PENDENTE'
                )
                endereco.latitude = None
                endereco.longitude = None
                endereco.geocodificacao_status = 'PENDENTE'

            resultado = geocodificar_endereco(endereco)
            cont[resultado] = cont.get(resultado, 0) + 1

            if i % 25 == 0 or i == total:
                self.stdout.write(
                    f'  {i}/{total} | OK={cont["OK"]} '
                    f'nao_encontrado={cont["NAO_ENCONTRADO"]} erro={cont["ERRO"]}'
                )

        dur = time.monotonic() - inicio
        self.stdout.write(self.style.SUCCESS(
            f'Concluído em {dur:.0f}s — OK={cont["OK"]}, '
            f'não encontrados={cont["NAO_ENCONTRADO"]}, erros={cont["ERRO"]}'
        ))
