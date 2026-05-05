from dataclasses import dataclass
from datetime import date
from typing import Iterable

from django.db import transaction

from api.models import Cidadao, Documento, Endereco, Localidade, Rua
from api.serializers import normalize_localidade_nome, normalize_rua_nome, _normalize_text


@dataclass
class LinhaImportacaoCidadao:
    staging_uuid: str
    nome: str
    cpf: str | None = None
    data_nascimento: str | None = None
    telefone: str | None = None
    tipo_localizacao: str | None = None
    bairro: str | None = None
    distrito: str | None = None
    comunidade_localidade: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    cep: str | None = None
    complemento: str | None = None


def _normalizar_tipo_localidade(value):
    value = _normalize_text(value)
    return value.upper() if value else None


def _normalizar_data(value):
    value = _normalize_text(value)
    if not value:
        return None

    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None

    if parsed.year < 1900 or parsed.year > 2100:
        return None

    return parsed


def _garantir_localidade(nome, tipo):
    nome_normalizado = normalize_localidade_nome(nome)
    if not nome_normalizado or not tipo:
        return None
    localidade, _ = Localidade.objects.get_or_create(
        nome=nome_normalizado,
        defaults={
            'tipo': tipo,
            'criada_automaticamente': True,
            'sincronizado': True,
            'status_sincronizacao': 'SINCRONIZADO',
        },
    )
    return localidade


def _garantir_rua(nome, localidade):
    nome_normalizado = normalize_rua_nome(nome)
    if not nome_normalizado or localidade is None:
        return None
    rua, _ = Rua.objects.get_or_create(
        localidade=localidade,
        nome=nome_normalizado,
        defaults={
            'criada_automaticamente': True,
            'sincronizado': True,
            'status_sincronizacao': 'SINCRONIZADO',
        },
    )
    return rua


@transaction.atomic
def importar_linhas_cidadaos(linhas: Iterable[LinhaImportacaoCidadao]):
    resultado = []

    for linha in linhas:
        cidadao = Cidadao.objects.create(
            nome=' '.join((linha.nome or '').split()).upper(),
            data_nascimento=_normalizar_data(linha.data_nascimento),
            telefone=_normalize_text(linha.telefone),
            possui_deficiencia=False,
            autorizacao_uso_imagem=False,
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        Documento.objects.create(
            cidadao=cidadao,
            cpf=_normalize_text(linha.cpf),
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        tipo_localizacao = _normalizar_tipo_localidade(linha.tipo_localizacao)
        bairro = normalize_localidade_nome(linha.bairro) if linha.bairro else ''
        distrito = normalize_localidade_nome(linha.distrito) if linha.distrito else None
        comunidade = (
            normalize_localidade_nome(linha.comunidade_localidade)
            if linha.comunidade_localidade else None
        )
        logradouro = normalize_rua_nome(linha.logradouro) if linha.logradouro else None

        localidade_principal = None
        if bairro:
            localidade_principal = _garantir_localidade(bairro, 'BAIRRO')
        elif distrito:
            localidade_principal = _garantir_localidade(distrito, 'DISTRITO')
        elif comunidade:
            localidade_principal = _garantir_localidade(comunidade, 'COMUNIDADE')

        _garantir_rua(logradouro, localidade_principal)

        Endereco.objects.create(
            cidadao=cidadao,
            logradouro=logradouro or '',
            tipo_localizacao=tipo_localizacao,
            bairro=bairro,
            distrito=distrito,
            comunidade_localidade=comunidade,
            numero=_normalize_text(linha.numero),
            cep=_normalize_text(linha.cep),
            complemento=_normalize_text(linha.complemento),
            sincronizado=True,
            status_sincronizacao='SINCRONIZADO',
        )

        resultado.append(
            {
                'staging_uuid': linha.staging_uuid,
                'cidadao_id': cidadao.id,
                'documento_id': cidadao.documentos.id,
                'endereco_id': cidadao.endereco.id,
            }
        )

    return resultado
