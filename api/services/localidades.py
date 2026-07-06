"""Coordenadas por localidade para o mapa de calor.

Em vez de geocodificar cada endereço (o Google erra com os nomes informais
de Tefé), mantemos uma coordenada curada por localidade e estampamos essa
coordenada em todos os beneficiários daquela localidade. Pinos manuais
(precisão MANUAL) por pessoa são preservados.
"""

import logging

import requests
from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from ..models import Endereco, LocalidadeBeneficiario
from .geocoding import GOOGLE_BOUNDS, GOOGLE_URL, dentro_de_tefe

logger = logging.getLogger('api.services.localidades')

SEM_NOME = '(sem nome)'


def rotulo(comunidade, bairro, distrito):
    """Mesmo critério do dashboard: comunidade -> bairro -> distrito."""
    return (
        (comunidade or '').strip()
        or (bairro or '').strip()
        or (distrito or '').strip()
        or SEM_NOME
    )


def filtro_enderecos(nome):
    """Q que casa endereços cujo rótulo de localidade é ``nome``."""
    vazio_com = Q(comunidade_localidade__isnull=True) | Q(comunidade_localidade='')
    vazio_bairro = Q(bairro__isnull=True) | Q(bairro='')
    if nome == SEM_NOME:
        vazio_dist = Q(distrito__isnull=True) | Q(distrito='')
        return vazio_com & vazio_bairro & vazio_dist
    return (
        Q(comunidade_localidade=nome)
        | (vazio_com & Q(bairro=nome))
        | (vazio_com & vazio_bairro & Q(distrito=nome))
    )


def enderecos_beneficiarios_da(nome):
    return (
        Endereco.objects
        .filter(cidadao__beneficios_recebidos__isnull=False)
        .filter(filtro_enderecos(nome))
        .distinct()
    )


def contagem_por_localidade():
    """{nome: total_beneficiarios} a partir dos endereços de beneficiários."""
    qs = (
        Endereco.objects
        .filter(cidadao__beneficios_recebidos__isnull=False)
        .values('bairro', 'comunidade_localidade', 'distrito')
        .annotate(n=Count('id'))
    )
    contagem = {}
    for r in qs:
        nome = rotulo(r['comunidade_localidade'], r['bairro'], r['distrito'])
        contagem[nome] = contagem.get(nome, 0) + r['n']
    return contagem


def sincronizar_localidades():
    """Garante uma linha em LocalidadeBeneficiario para cada localidade distinta
    existente nos endereços de beneficiários. Retorna (criadas, total)."""
    contagem = contagem_por_localidade()
    existentes = set(LocalidadeBeneficiario.objects.values_list('nome', flat=True))
    criadas = 0
    for nome in contagem:
        if nome not in existentes:
            LocalidadeBeneficiario.objects.create(nome=nome)
            criadas += 1
    return criadas, len(contagem)


def geocodificar_localidade(loc, sobrescrever=False):
    """Geocodifica a localidade pelo Google e grava o diagnóstico.
    Não mexe em localidades já definidas manualmente (fonte=MANUAL), a menos
    que ``sobrescrever=True``. Retorna a fonte resultante."""
    if loc.nome == SEM_NOME:
        return loc.fonte
    if loc.fonte == LocalidadeBeneficiario.FONTE_MANUAL and not sobrescrever:
        return loc.fonte

    key = getattr(settings, 'GOOGLE_GEOCODING_API_KEY', '') or ''
    if not key:
        return loc.fonte

    resp = requests.get(
        GOOGLE_URL,
        params={
            'address': f'{loc.nome}, Tefé, AM, Brasil',
            'key': key,
            'language': 'pt-BR',
            'region': 'br',
            'components': 'country:BR|administrative_area:AM',
            'bounds': GOOGLE_BOUNDS,
        },
        timeout=15,
    )
    resp.raise_for_status()
    dados = resp.json()
    if dados.get('status') == 'OK' and dados.get('results'):
        res = dados['results'][0]
        g = res['geometry']['location']
        lat, lon = float(g['lat']), float(g['lng'])
        loc.google_formatted = res.get('formatted_address', '')[:300]
        loc.google_partial = bool(res.get('partial_match', False))
        loc.dentro_de_tefe = dentro_de_tefe(lat, lon)
        # Só pré-preenche a coordenada quando o resultado é confiável:
        # dentro de Tefé e sem partial match (chute). Senão fica PENDENTE
        # para revisão manual, mas guardamos o diagnóstico do Google.
        if loc.dentro_de_tefe and not loc.google_partial:
            loc.latitude = lat
            loc.longitude = lon
            loc.fonte = LocalidadeBeneficiario.FONTE_GOOGLE
    else:
        loc.google_formatted = f'Google: {dados.get("status")}'
        loc.google_partial = False
        loc.dentro_de_tefe = False
    loc.save()
    return loc.fonte


def aplicar_coordenada(loc):
    """Estampa a coordenada da localidade em todos os endereços de beneficiários
    dela (exceto pinos MANUAIS por pessoa). Retorna quantos endereços atualizou."""
    if loc.latitude is None or loc.longitude is None:
        return 0
    atualizados = (
        enderecos_beneficiarios_da(loc.nome)
        .exclude(precisao_geocodificacao='MANUAL')
        .update(
            latitude=loc.latitude,
            longitude=loc.longitude,
            precisao_geocodificacao='LOCALIDADE',
            geocodificacao_status='OK',
            geocodificacao_erro='',
            geocodificado_em=timezone.now(),
        )
    )
    logger.info('localidade.aplicada nome=%r enderecos=%s', loc.nome, atualizados)
    return atualizados


def aplicar_todas():
    """Aplica a coordenada de todas as localidades já definidas. Retorna resumo."""
    locs = LocalidadeBeneficiario.objects.exclude(latitude__isnull=True)
    total_locs = 0
    total_enderecos = 0
    for loc in locs:
        n = aplicar_coordenada(loc)
        if n:
            total_locs += 1
            total_enderecos += n
    return {'localidades': total_locs, 'enderecos': total_enderecos}
