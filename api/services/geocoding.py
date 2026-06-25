"""Serviço de geocodificação de endereços (Nominatim / OpenStreetMap).

Toda a geocodificação acontece no backend e o resultado é persistido no
``Endereco``. O frontend apenas consome ``latitude``/``longitude`` já salvas.

Estratégia de fallback (do mais preciso para o menos preciso):

    1. Rua + número + localidade + Tefé/AM  -> ENDERECO_EXATO
    2. Rua + localidade + Tefé/AM           -> RUA
    3. Localidade + Tefé/AM                  -> LOCALIDADE

Onde ``localidade`` = comunidade_localidade, ou bairro, ou distrito.
"""

import logging
import threading
import time
import unicodedata

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('api.services.geocoding')

GOOGLE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'BolsaTefe-Geocoder/1.0 (Prefeitura de Tefe/AM)'

# Nominatim exige no máximo 1 requisição por segundo.
_INTERVALO_MINIMO_S = 1.1
_lock = threading.Lock()
_ultimo_request = 0.0

# Cache em memória por string consultada (válido durante o processo).
_cache = {}

# Caixa aproximada do município de Tefé/AM para enviesar/restringir resultados.
# (esquerda, topo, direita, base) = (lon_min, lat_max, lon_max, lat_min)
_VIEWBOX = '-65.6,-2.7,-63.8,-4.2'

# Bounding box (generoso) do município de Tefé e suas localidades/comunidades
# (Caiambé, Porto Praia, Santo Isidoro, etc.). Resultados fora disso são descartados.
TEFE_LAT_MIN, TEFE_LAT_MAX = -5.0, -2.2
TEFE_LON_MIN, TEFE_LON_MAX = -66.0, -63.2
# Para o parâmetro 'bounds' do Google: "sul,oeste|norte,leste"
GOOGLE_BOUNDS = f'{TEFE_LAT_MIN},{TEFE_LON_MIN}|{TEFE_LAT_MAX},{TEFE_LON_MAX}'


def dentro_de_tefe(lat, lon):
    return (TEFE_LAT_MIN <= lat <= TEFE_LAT_MAX) and (TEFE_LON_MIN <= lon <= TEFE_LON_MAX)


def _normalizar(texto):
    """Minúsculas, sem acentos e sem espaços nas pontas — para comparar nomes de bairro."""
    if not texto:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(texto))
    sem_acento = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.casefold().strip()


def _localidade_confere(localidade, formatted):
    """True se o nome da localidade/bairro aparece no endereço retornado pelo provedor."""
    loc = _normalizar(localidade)
    if not loc:
        return True  # sem bairro para validar — não bloqueia
    return loc in _normalizar(formatted)


def montar_endereco_completo(endereco):
    """Monta a string de endereço principal (a tentativa mais específica)."""
    variacoes = montar_variacoes(endereco)
    return variacoes[0][0] if variacoes else ''


def montar_variacoes(endereco):
    """Retorna lista de (query, precisao) na ordem do fallback, sem duplicatas."""
    rua = (endereco.logradouro or '').strip()
    numero = (endereco.numero or '').strip()
    localidade = (
        (endereco.comunidade_localidade or '').strip()
        or (endereco.bairro or '').strip()
        or (endereco.distrito or '').strip()
    )

    variacoes = []

    # Tentativa 1 — endereço exato (rua + número + localidade)
    if rua and numero and localidade:
        variacoes.append((f'{rua}, {numero}, {localidade}, Tefé, AM, Brasil', 'ENDERECO_EXATO'))
    # Tentativa 2 — rua + localidade
    if rua and localidade:
        variacoes.append((f'{rua}, {localidade}, Tefé, AM, Brasil', 'RUA'))
    # Tentativa 3 — apenas localidade
    if localidade:
        variacoes.append((f'{localidade}, Tefé, AM, Brasil', 'LOCALIDADE'))
    # Fallbacks quando não há localidade, apenas rua
    if rua and not localidade:
        if numero:
            variacoes.append((f'{rua}, {numero}, Tefé, AM, Brasil', 'ENDERECO_EXATO'))
        variacoes.append((f'{rua}, Tefé, AM, Brasil', 'RUA'))

    # Remove duplicatas preservando a ordem.
    vistas = set()
    unicas = []
    for query, precisao in variacoes:
        if query not in vistas:
            vistas.add(query)
            unicas.append((query, precisao))
    return unicas


def _respeitar_rate_limit(intervalo):
    global _ultimo_request
    with _lock:
        agora = time.monotonic()
        espera = intervalo - (agora - _ultimo_request)
        if espera > 0:
            time.sleep(espera)
        _ultimo_request = time.monotonic()


def _consultar_google(query, api_key):
    """Consulta o Google Geocoding.

    Retorna dict ``{'lat', 'lon', 'partial_match', 'formatted'}``,
    ``None`` (sem resultado) ou lança em erro de API.
    """
    _respeitar_rate_limit(0.06)
    resposta = requests.get(
        GOOGLE_URL,
        params={
            'address': query,
            'key': api_key,
            'language': 'pt-BR',
            'region': 'br',
            'components': 'country:BR|administrative_area:AM',
            'bounds': GOOGLE_BOUNDS,
        },
        timeout=15,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    status = dados.get('status')
    if status == 'OK' and dados.get('results'):
        resultado = dados['results'][0]
        loc = resultado['geometry']['location']
        return {
            'lat': float(loc['lat']),
            'lon': float(loc['lng']),
            'partial_match': bool(resultado.get('partial_match', False)),
            'formatted': resultado.get('formatted_address', ''),
        }
    if status == 'ZERO_RESULTS':
        return None
    # OVER_QUERY_LIMIT, REQUEST_DENIED, INVALID_REQUEST... -> erro
    raise RuntimeError(f"Google Geocoding status={status}: {dados.get('error_message', '')}")


def _consultar_nominatim(query):
    """Consulta o Nominatim (OSM).

    Retorna dict ``{'lat', 'lon', 'partial_match', 'formatted'}`` ou ``None``.
    Lança em erro de API.
    """
    _respeitar_rate_limit(_INTERVALO_MINIMO_S)
    resposta = requests.get(
        NOMINATIM_URL,
        params={
            'q': query,
            'format': 'json',
            'limit': 1,
            'countrycodes': 'br',
            'viewbox': _VIEWBOX,
            'addressdetails': 0,
        },
        headers={'User-Agent': USER_AGENT, 'Accept-Language': 'pt-BR'},
        timeout=15,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados:
        return None
    item = dados[0]
    return {
        'lat': float(item['lat']),
        'lon': float(item['lon']),
        'partial_match': False,
        'formatted': item.get('display_name', ''),
    }


def _consultar(query):
    """Despacha para Google (se houver chave) ou Nominatim. Faz cache por string."""
    if query in _cache:
        return _cache[query]

    api_key = getattr(settings, 'GOOGLE_GEOCODING_API_KEY', '') or ''
    if api_key:
        resultado = _consultar_google(query, api_key)
    else:
        resultado = _consultar_nominatim(query)

    _cache[query] = resultado
    return resultado


def _persistir(endereco, **campos):
    """Atualiza o registro sem disparar ``save()`` (evita bump de atualizado_em
    e a lógica de reset por mudança de endereço)."""
    from ..models import Endereco

    Endereco.objects.filter(pk=endereco.pk).update(**campos)
    for chave, valor in campos.items():
        setattr(endereco, chave, valor)


def geocodificar_endereco(endereco):
    """Geocodifica um endereço, persiste o resultado e retorna o status final."""
    if endereco.precisao_geocodificacao == 'MANUAL':
        logger.info('geocoding.pulado_manual endereco_id=%s', endereco.pk)
        return endereco.geocodificacao_status

    variacoes = montar_variacoes(endereco)
    localidade = (
        (endereco.comunidade_localidade or '').strip()
        or (endereco.bairro or '').strip()
        or (endereco.distrito or '').strip()
    )
    logger.info(
        'geocoding.inicio endereco_id=%s cidadao=%s tentativas=%s',
        endereco.pk,
        getattr(endereco, 'cidadao_id', None),
        len(variacoes),
    )

    if not variacoes:
        _persistir(
            endereco,
            geocodificacao_status='NAO_ENCONTRADO',
            geocodificacao_erro='Endereço insuficiente para geocodificação',
            geocodificado_em=timezone.now(),
        )
        logger.warning('geocoding.sem_dados endereco_id=%s', endereco.pk)
        return 'NAO_ENCONTRADO'

    for query, precisao in variacoes:
        logger.info('geocoding.tentativa endereco_id=%s precisao=%s query=%r', endereco.pk, precisao, query)
        try:
            resultado = _consultar(query)
        except Exception as exc:  # erro de rede/API — aborta e marca ERRO
            mensagem = f'Erro ao consultar geocodificação: {exc}'
            _persistir(
                endereco,
                geocodificacao_status='ERRO',
                geocodificacao_erro=mensagem,
                geocodificado_em=timezone.now(),
            )
            logger.error('geocoding.erro endereco_id=%s query=%r erro=%s', endereco.pk, query, exc)
            return 'ERRO'

        if resultado:
            lat = resultado['lat']
            lon = resultado['lon']
            if not dentro_de_tefe(lat, lon):
                # Resultado fora do município de Tefé — descarta e tenta a próxima variação.
                logger.warning(
                    'geocoding.fora_de_tefe endereco_id=%s precisao=%s lat=%s lon=%s query=%r',
                    endereco.pk, precisao, lat, lon, query,
                )
                continue

            # Nas tentativas precisas (rua/número), o Google às vezes "casa parcialmente":
            # ignora o bairro e devolve a mesma rua em outra localidade. Descartamos esses
            # casos e caímos para a tentativa por localidade — pino no bairro correto.
            if precisao in ('ENDERECO_EXATO', 'RUA') and localidade:
                if resultado['partial_match']:
                    logger.warning(
                        'geocoding.partial_match endereco_id=%s precisao=%s query=%r formatted=%r',
                        endereco.pk, precisao, query, resultado['formatted'],
                    )
                    continue
                if not _localidade_confere(localidade, resultado['formatted']):
                    logger.warning(
                        'geocoding.bairro_divergente endereco_id=%s precisao=%s '
                        'esperado=%r formatted=%r',
                        endereco.pk, precisao, localidade, resultado['formatted'],
                    )
                    continue

            _persistir(
                endereco,
                latitude=lat,
                longitude=lon,
                endereco_geocodificado=query,
                precisao_geocodificacao=precisao,
                geocodificacao_status='OK',
                geocodificacao_erro='',
                geocodificado_em=timezone.now(),
            )
            logger.info(
                'geocoding.ok endereco_id=%s precisao=%s lat=%s lon=%s',
                endereco.pk, precisao, lat, lon,
            )
            return 'OK'

    _persistir(
        endereco,
        geocodificacao_status='NAO_ENCONTRADO',
        geocodificacao_erro='Endereço não encontrado',
        geocodificado_em=timezone.now(),
    )
    logger.warning('geocoding.nao_encontrado endereco_id=%s', endereco.pk)
    return 'NAO_ENCONTRADO'
