import logging
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone as datetime_timezone

import requests

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q, Count, Value
from django.db.models import Prefetch
from django.db.models.functions import Coalesce, NullIf, TruncMonth
from django.shortcuts import get_object_or_404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from .models import (
    Beneficiario,
    Beneficio,
    Cidadao,
    Documento,
    DocumentoAnexo,
    Endereco,
    Escola,
    LocalTefe,
    Localidade,
    LocalidadeBeneficiario,
    Rua,
)
from .serializers import (
    CidadaoSerializer,
    CidadaoListSerializer,
    DocumentoAnexoSerializer,
    BeneficioSerializer,
    BeneficiarioSerializer,
    BeneficioCidadaoSerializer,
    EscolaSerializer,
    LocalTefeSerializer,
    LocalidadeSerializer,
    RuaSerializer,
    normalize_documento_anexo_tipo,
)
from .permissions import HasRequiredRole
from .services.keycloak_admin_service import (
    KeycloakAdminError,
    KeycloakAdminInputError,
    KeycloakAdminNotFoundError,
    KeycloakAdminPermissionError,
    buscar_usuario_operador,
    liberar_operador,
    remover_operador,
)
from .services.tefe_cidadao_service import buscar_cidadao_por_cpf


ADMIN_ROLE = 'USER-BOLSA-TEFE-ADMIN'
logger = logging.getLogger(__name__)
ALLOWED_DOCUMENT_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTO_PDF_SIZE_BYTES = 25 * 1024 * 1024


def _request_roles(request):
    roles = []
    if getattr(request, 'user', None) and getattr(request.user, 'is_authenticated', False):
        keycloak_data = getattr(request.user, 'keycloak_data', None)
        if keycloak_data:
            roles = keycloak_data.roles or []
    if not roles:
        roles = getattr(request, 'jwt_roles', [])
    return set(roles)


def _parse_updated_since(request):
    raw = request.query_params.get('updated_since') or request.query_params.get(
        'updated_after'
    )
    if not raw:
        return None

    try:
        updated_since_ms = int(str(raw).strip())
    except (TypeError, ValueError):
        return None

    return datetime.fromtimestamp(updated_since_ms / 1000, tz=datetime_timezone.utc)


class CidadaoViewSet(viewsets.ModelViewSet):
    serializer_class = CidadaoSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status_atualizacao']
    search_fields = ['nome', 'nis', 'documentos__cpf']

    def get_serializer_class(self):
        if self.action == 'list':
            return CidadaoListSerializer
        return CidadaoSerializer

    def get_queryset(self):
        if self.action == 'list':
            queryset = Cidadao.objects.select_related('endereco').only(
                'id',
                'nome',
                'nis',
                'data_nascimento',
                'telefone',
                'email',
                'identidade_genero',
                'sincronizado',
                'status_sincronizacao',
                'sincronizado_em',
                'status_atualizacao',
                'criado_em',
                'atualizado_em',
                'endereco__id',
                'endereco__tipo_localizacao',
                'endereco__logradouro',
                'endereco__bairro',
                'endereco__distrito',
                'endereco__comunidade_localidade',
                'endereco__numero',
                'endereco__cep',
                'endereco__complemento',
                'endereco__situacao_imovel',
                'endereco__valor_aluguel',
                'endereco__material_parede',
                'endereco__qtd_comodos',
                'endereco__possui_luz',
                'endereco__possui_asfalto',
                'endereco__possui_lixo',
                'endereco__abastecimento_agua',
                'endereco__abastecimento_agua_outro',
                'endereco__possui_saneamento',
                'endereco__sincronizado',
                'endereco__status_sincronizacao',
                'endereco__sincronizado_em',
                'endereco__criado_em',
                'endereco__atualizado_em',
            )
            updated_since = _parse_updated_since(self.request)
            if updated_since is not None:
                queryset = queryset.filter(atualizado_em__gt=updated_since)
            beneficio_id = self.request.query_params.get('beneficio_id') or self.request.query_params.get('beneficio')
            sem_beneficio = str(self.request.query_params.get('sem_beneficio', '')).lower() in ('1', 'true', 'sim')
            if sem_beneficio:
                queryset = queryset.filter(beneficios_recebidos__isnull=True)
            elif beneficio_id:
                queryset = queryset.filter(beneficios_recebidos__beneficio_id=beneficio_id).distinct()
            return queryset.order_by('nome')

        queryset = (
            Cidadao.objects
            .select_related(
                'documentos',
                'endereco',
                'socioeconomico',
                'termo_responsabilidade',
                'atualizado_por',
            )
            .prefetch_related(
                'membros_familia',
                'documentos_anexados',
                Prefetch(
                    'beneficios_recebidos',
                    queryset=Beneficiario.objects.only(
                        'id',
                        'cidadao_id',
                        'status',
                        'criado_em',
                    ).order_by('criado_em'),
                    to_attr='beneficios_recebidos_ordenados',
                ),
            )
        )
        updated_since = _parse_updated_since(self.request)
        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
        return queryset

    def destroy(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para excluir cidadão.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.warning('POST /api/cidadaos/ payload inválido: %s', request.data)
            logger.warning('POST /api/cidadaos/ serializer.errors: %s', serializer.errors)
            return Response(
                {
                    'detail': 'Dados inválidos para criar cidadão.',
                    'errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        if not serializer.is_valid():
            logger.warning(
                '%s %s payload inválido para cidadao=%s usuario=%s: %s',
                request.method,
                request.path,
                instance.pk,
                getattr(request.user, 'username', None),
                request.data,
            )
            logger.warning(
                '%s %s serializer.errors para cidadao=%s: %s',
                request.method,
                request.path,
                instance.pk,
                serializer.errors,
            )
            return Response(
                {
                    'detail': 'Dados inválidos para atualizar cidadão.',
                    'errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.perform_update(serializer)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(atualizado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(atualizado_por=self.request.user)


class EscolaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EscolaSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    filter_backends = [filters.SearchFilter]
    search_fields = ['nome', 'codigo', 'tipo', 'zona']

    def get_queryset(self):
        queryset = Escola.objects.all()
        updated_since = _parse_updated_since(self.request)
        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
        return queryset.order_by('nome')


class LocalTefeViewSet(viewsets.ModelViewSet):
    serializer_class = LocalTefeSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    filter_backends = [filters.SearchFilter]
    search_fields = ['nome', 'tipo']

    def get_queryset(self):
        queryset = LocalTefe.objects.all().order_by('ordem', 'nome')
        tipo = self.request.query_params.get('tipo')
        ativo = self.request.query_params.get('ativo')
        updated_since = _parse_updated_since(self.request)

        if tipo:
            queryset = queryset.filter(tipo=tipo)

        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)

        if ativo is None and self.action == 'list':
            queryset = queryset.filter(ativo=True)
        elif ativo is not None:
            queryset = queryset.filter(ativo=ativo.lower() == 'true')

        return queryset

    def create(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para criar local de Tefé.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar local de Tefé.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar local de Tefé.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para excluir local de Tefé.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)


class LocalidadeViewSet(viewsets.ModelViewSet):
    serializer_class = LocalidadeSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    filter_backends = [filters.SearchFilter]
    search_fields = ['nome', 'tipo']

    def get_queryset(self):
        queryset = Localidade.objects.all().order_by('nome')
        tipo = self.request.query_params.get('tipo')
        updated_since = _parse_updated_since(self.request)
        if tipo:
            queryset = queryset.filter(tipo=tipo)
        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
        return queryset

    def create(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para criar localidade.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar localidade.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar localidade.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para excluir localidade.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)


class RuaViewSet(viewsets.ModelViewSet):
    serializer_class = RuaSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    filter_backends = [filters.SearchFilter]
    search_fields = ['nome', 'localidade__nome']

    def get_queryset(self):
        queryset = Rua.objects.select_related('localidade').all().order_by('nome')
        localidade_id = self.request.query_params.get('localidade_id')
        updated_since = _parse_updated_since(self.request)
        if localidade_id:
            queryset = queryset.filter(localidade_id=localidade_id)
        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
        return queryset

    def create(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para criar rua.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar rua.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar rua.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para excluir rua.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)


def _request_flag_true(data, *keys):
    truthy = {'true', '1', 'sim', 's', 'yes', 'on'}
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if str(value).strip().lower() in truthy:
            return True
    return False


def _validar_upload_documento(tipo_documento, arquivo, sem_documento_no_momento=False):
    tipos_validos = {choice[0] for choice in DocumentoAnexo.TIPOS_CHOICES}
    tipo_documento = normalize_documento_anexo_tipo(tipo_documento)
    if tipo_documento not in tipos_validos:
        return 'Tipo de documento inválido.'

    if arquivo is None:
        if sem_documento_no_momento:
            return None
        return 'Arquivo é obrigatório.'

    extensao = Path(arquivo.name).suffix.replace('.', '').lower().strip()
    if extensao not in ALLOWED_DOCUMENT_EXTENSIONS:
        return 'Formato inválido. Envie um arquivo JPG, JPEG, PNG ou PDF.'

    tamanho = getattr(arquivo, 'size', 0) or 0
    if tamanho <= 0:
        return 'O arquivo enviado está vazio.'
    if tamanho > MAX_DOCUMENT_SIZE_BYTES:
        return 'Arquivo excede o tamanho máximo de 10 MB.'

    return None


def _validar_upload_documento_pdf(arquivo):
    if arquivo is None:
        return 'Arquivo é obrigatório.'

    extensao = Path(arquivo.name).suffix.replace('.', '').lower().strip()
    if extensao != 'pdf':
        return 'Envie um arquivo PDF válido.'

    tamanho = getattr(arquivo, 'size', 0) or 0
    if tamanho <= 0:
        return 'O arquivo enviado está vazio.'
    if tamanho > MAX_DOCUMENTO_PDF_SIZE_BYTES:
        return 'Arquivo excede o tamanho máximo de 25 MB.'

    return None


class CidadaoDocumentosView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, cidadao_id):
        cidadao = get_object_or_404(
            Cidadao.objects.prefetch_related('documentos_anexados'),
            pk=cidadao_id,
        )
        serializer = DocumentoAnexoSerializer(
            cidadao.documentos_anexados.all().order_by('data_envio'),
            many=True,
            context={'request': request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, cidadao_id):
        cidadao = get_object_or_404(Cidadao, pk=cidadao_id)
        tipo_documento = normalize_documento_anexo_tipo(
            (request.data.get('tipo_documento') or '').strip()
        )
        substituir = str(request.data.get('substituir', '')).strip().lower() == 'true'
        arquivo = request.FILES.get('arquivo')
        sem_documento_no_momento = _request_flag_true(
            request.data,
            'sem_documento_no_momento',
            'nao_apresentado',
            'naoApresentado',
            'documento_nao_apresentado',
            'documentoNaoApresentado',
            'sem_documento',
            'semDocumento',
            'semDocumentoNoMomento',
        )

        logger.info(
            'documentos.post cidadao_id=%s tipo=%s substituir=%s sem_documento=%s arquivo=%s',
            cidadao_id,
            tipo_documento,
            substituir,
            sem_documento_no_momento,
            bool(arquivo),
        )

        erro = _validar_upload_documento(
            tipo_documento,
            arquivo,
            sem_documento_no_momento=sem_documento_no_momento,
        )
        if erro:
            return Response({'detail': erro}, status=status.HTTP_400_BAD_REQUEST)

        permite_multiplos = tipo_documento == DocumentoAnexo.TIPO_FOTO_RESIDENCIA
        existente = (
            None
            if permite_multiplos and not substituir
            else DocumentoAnexo.objects.filter(
                cidadao=cidadao,
                tipo_documento=tipo_documento,
            ).first()
        )

        if existente and not substituir:
            return Response(
                {
                    'detail': (
                        'Já existe um documento anexado para este tipo. '
                        'Envie substituir=true para trocar o arquivo.'
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        extensao = ''
        nome_original = ''
        if arquivo is not None:
            extensao = Path(arquivo.name).suffix.replace('.', '').lower().strip()
            nome_original = Path(arquivo.name).name

        with transaction.atomic():
            if existente:
                if existente.arquivo and existente.arquivo.name:
                    try:
                        existente.arquivo.delete(save=False)
                    except Exception:
                        pass
                documento = existente
            else:
                documento = DocumentoAnexo(
                    cidadao=cidadao,
                    tipo_documento=tipo_documento,
                )

            if sem_documento_no_momento and arquivo is None:
                documento.arquivo = None
                documento.nome_arquivo = ''
                documento.extensao = ''
                documento.tamanho_bytes = 0
                documento.status = 'SEM_DOCUMENTO_NO_MOMENTO'
                documento.sem_documento_no_momento = True
            else:
                documento.arquivo = arquivo
                documento.nome_arquivo = nome_original
                documento.extensao = extensao
                documento.tamanho_bytes = arquivo.size
                documento.status = 'ENVIADO'
                documento.sem_documento_no_momento = False

            documento.sincronizado = True
            documento.status_sincronizacao = 'SINCRONIZADO'
            documento.sincronizado_em = timezone.now()
            documento.save()

        serializer = DocumentoAnexoSerializer(documento, context={'request': request})
        logger.info(
            'documentos.post salvo cidadao_id=%s documento_id=%s tipo=%s status=%s sem_documento=%s sincronizado=%s',
            cidadao_id,
            documento.id,
            documento.tipo_documento,
            documento.status,
            documento.sem_documento_no_momento,
            documento.status_sincronizacao,
        )
        return Response(
            serializer.data,
            status=status.HTTP_200_OK if existente else status.HTTP_201_CREATED,
        )


class CidadaoDocumentoDetailView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    def delete(self, request, cidadao_id, documento_ref):
        cidadao = get_object_or_404(Cidadao, pk=cidadao_id)
        documento = None

        try:
            documento_uuid = uuid.UUID(str(documento_ref))
            documento = DocumentoAnexo.objects.filter(
                id=documento_uuid,
                cidadao=cidadao,
            ).first()
        except ValueError:
            tipo_documento = normalize_documento_anexo_tipo(documento_ref)
            documento = DocumentoAnexo.objects.filter(
                cidadao=cidadao,
                tipo_documento=tipo_documento,
            ).first()

        if documento is None:
            return Response(
                {'detail': 'Documento anexado não encontrado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        documento.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CidadaoDocumentoPdfView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        cidadao_id = (request.data.get('cidadao_id') or '').strip()
        arquivo = request.FILES.get('arquivo')

        if not cidadao_id:
            return Response(
                {'detail': 'cidadao_id é obrigatório.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        erro = _validar_upload_documento_pdf(arquivo)
        if erro:
            return Response({'detail': erro}, status=status.HTTP_400_BAD_REQUEST)

        cidadao = get_object_or_404(Cidadao, pk=cidadao_id)

        with transaction.atomic():
            documento_antigo = cidadao.documento_pdf
            if documento_antigo:
                try:
                    documento_antigo.delete(save=False)
                except Exception:
                    pass

            cidadao.sincronizado = True
            cidadao.status_sincronizacao = 'SINCRONIZADO'
            cidadao.sincronizado_em = timezone.now()
            cidadao.atualizado_por = request.user

            nome_original = Path(arquivo.name).name
            cidadao.documento_pdf_nome_arquivo = nome_original
            cidadao.documento_pdf.save(nome_original, arquivo, save=True)

        serializer = CidadaoSerializer(cidadao, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class BuscarCidadaoNoTefeView(APIView):
    serializer_class = CidadaoSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    @extend_schema(
        responses={200: CidadaoSerializer},
    )
    def get(self, request):
        cpf = request.query_params.get("cpf")

        if not cpf:
            return Response(
                {"detail": "CPF é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            dados = buscar_cidadao_por_cpf(cpf)

            attributes = dados.get("attributes", {})

            first_name = (
                dados.get("firstName")
                or dados.get("first_name")
                or ""
            ).strip()
            last_name = (
                dados.get("lastName")
                or dados.get("last_name")
                or ""
            ).strip()

            nome = f"{first_name} {last_name}".strip()
            email = (dados.get("email") or "").strip()

            cpf_attr = attributes.get("cpf", [""])
            data_nascimento_attr = attributes.get("data_nascimento", [None])
            telefone_attr = attributes.get("telefone1", [""])
            nis_attr = attributes.get("nis", [""])

            cpf_final = cpf_attr[0] if cpf_attr and len(cpf_attr) > 0 else cpf
            data_nascimento = (
                data_nascimento_attr[0]
                if data_nascimento_attr and len(data_nascimento_attr) > 0
                else None
            )
            telefone = (
                telefone_attr[0]
                if telefone_attr and len(telefone_attr) > 0
                else ""
            )
            nis = (
                nis_attr[0]
                if nis_attr and len(nis_attr) > 0
                else None
            )

            return Response(
                {
                    "nome": nome,
                    "email": email,
                    "cpf": cpf_final,
                    "data_nascimento": data_nascimento,
                    "telefone": telefone,
                    "nis": nis,
                    "dados_tefe": dados,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            mensagem = str(e)

            if "não encontrado" in mensagem.lower():
                return Response(
                    {"detail": mensagem},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {"detail": mensagem},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ImportarCidadaoDoTefeView(APIView):
    serializer_class = CidadaoSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    @extend_schema(
        request=None,
        responses={200: CidadaoSerializer, 201: CidadaoSerializer},
    )
    def post(self, request):
        cpf = request.data.get("cpf")

        if not cpf:
            return Response(
                {"detail": "CPF é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            dados = buscar_cidadao_por_cpf(cpf)
            attributes = dados.get("attributes", {})

            first_name = (
                dados.get("firstName")
                or dados.get("first_name")
                or ""
            ).strip()
            last_name = (
                dados.get("lastName")
                or dados.get("last_name")
                or ""
            ).strip()

            nome = f"{first_name} {last_name}".strip()
            email = (dados.get("email") or "").strip() or None

            cpf_attr = attributes.get("cpf", [""])
            data_nascimento_attr = attributes.get("data_nascimento", [None])
            telefone_attr = attributes.get("telefone1", [""])
            nis_attr = attributes.get("nis", [""])

            cpf_final = cpf_attr[0] if cpf_attr and len(cpf_attr) > 0 else cpf
            data_nascimento = (
                data_nascimento_attr[0]
                if data_nascimento_attr and len(data_nascimento_attr) > 0
                else None
            )
            telefone = (
                telefone_attr[0]
                if telefone_attr and len(telefone_attr) > 0
                else ""
            )
            nis = (
                nis_attr[0]
                if nis_attr and len(nis_attr) > 0
                else None
            )
            nis = (nis or '').strip() or None

            with transaction.atomic():
                documento = Documento.objects.select_related('cidadao').filter(
                    cpf=cpf_final
                ).first()
                cidadao_existente = None

                if documento:
                    cidadao_existente = documento.cidadao
                else:
                    filtros = Q()
                    if email:
                        filtros |= Q(email=email)
                    if nis:
                        filtros |= Q(nis=nis)

                    if filtros:
                        cidadao_existente = (
                            Cidadao.objects
                            .filter(filtros)
                            .order_by('criado_em')
                            .first()
                        )

                if cidadao_existente:
                    cidadao = cidadao_existente
                    criado = False
                    updated_fields = []

                    novos_dados = {
                        'nome': nome,
                        'email': email,
                        'data_nascimento': data_nascimento,
                        'telefone': telefone,
                        'nis': nis,
                        'sincronizado': True,
                        'status_sincronizacao': 'SINCRONIZADO',
                    }
                    for field, value in novos_dados.items():
                        if getattr(cidadao, field) != value:
                            setattr(cidadao, field, value)
                            updated_fields.append(field)

                    if cidadao.sincronizado_em is None:
                        cidadao.sincronizado_em = timezone.now()
                        updated_fields.append('sincronizado_em')

                    if cidadao.atualizado_por_id != request.user.id:
                        cidadao.atualizado_por = request.user
                        updated_fields.append('atualizado_por')

                    if updated_fields:
                        cidadao.save(update_fields=updated_fields)

                    documento_existente = getattr(cidadao, 'documentos', None)
                    if documento_existente is None:
                        Documento.objects.create(
                            cidadao=cidadao,
                            cpf=cpf_final,
                            sincronizado=True,
                            status_sincronizacao='SINCRONIZADO',
                            sincronizado_em=cidadao.sincronizado_em or timezone.now(),
                        )
                    else:
                        documento_updates = []
                        if documento_existente.cpf != cpf_final:
                            documento_existente.cpf = cpf_final
                            documento_updates.append('cpf')
                        if not documento_existente.sincronizado:
                            documento_existente.sincronizado = True
                            documento_updates.append('sincronizado')
                        if (
                            documento_existente.status_sincronizacao
                            != 'SINCRONIZADO'
                        ):
                            documento_existente.status_sincronizacao = 'SINCRONIZADO'
                            documento_updates.append('status_sincronizacao')
                        if documento_existente.sincronizado_em is None:
                            documento_existente.sincronizado_em = timezone.now()
                            documento_updates.append('sincronizado_em')
                        if documento_updates:
                            documento_existente.save(update_fields=documento_updates)
                else:
                    sincronizado_em = timezone.now()
                    cidadao = Cidadao.objects.create(
                        nome=nome,
                        email=email,
                        data_nascimento=data_nascimento,
                        telefone=telefone,
                        nis=nis,
                        sincronizado=True,
                        status_sincronizacao='SINCRONIZADO',
                        sincronizado_em=sincronizado_em,
                        atualizado_por=request.user,
                    )
                    Documento.objects.create(
                        cidadao=cidadao,
                        cpf=cpf_final,
                        sincronizado=True,
                        status_sincronizacao='SINCRONIZADO',
                        sincronizado_em=sincronizado_em,
                    )
                    criado = True

            serializer = CidadaoSerializer(cidadao)

            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED if criado else status.HTTP_200_OK,
            )

        except Exception as e:
            mensagem = str(e)

            if "não encontrado" in mensagem.lower():
                return Response(
                    {"detail": mensagem},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {"detail": mensagem},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LiberarOperadorView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE-ADMIN'

    def post(self, request):
        cpf = request.data.get('cpf')
        email = request.data.get('email')

        try:
            resultado = liberar_operador(cpf=cpf, email=email)
            return Response(resultado, status=status.HTTP_200_OK)
        except KeycloakAdminInputError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except KeycloakAdminNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except KeycloakAdminPermissionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except requests.RequestException as exc:
            logger.exception('liberar_operador.keycloak_erro erro=%s', exc)
            return Response(
                {'detail': 'Não foi possível consultar o Keycloak agora.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except KeycloakAdminError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception('liberar_operador.erro inesperado erro=%s', exc)
            return Response(
                {'detail': 'Não foi possível liberar o operador agora.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def _responder_acao_operador(log_prefix, mensagem_erro_generico, acao):
    """Executa uma ação administrativa no Keycloak mapeando erros para respostas HTTP."""
    try:
        resultado = acao()
        return Response(resultado, status=status.HTTP_200_OK)
    except KeycloakAdminInputError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except KeycloakAdminNotFoundError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
    except KeycloakAdminPermissionError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except requests.RequestException as exc:
        logger.exception('%s.keycloak_erro erro=%s', log_prefix, exc)
        return Response(
            {'detail': 'Não foi possível consultar o Keycloak agora.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except KeycloakAdminError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        logger.exception('%s.erro inesperado erro=%s', log_prefix, exc)
        return Response(
            {'detail': mensagem_erro_generico},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class BuscarOperadorView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def get(self, request):
        cpf = request.query_params.get('cpf')
        email = request.query_params.get('email')

        return _responder_acao_operador(
            'buscar_operador',
            'Não foi possível consultar o usuário agora.',
            lambda: buscar_usuario_operador(cpf=cpf, email=email),
        )


class RemoverOperadorView(APIView):
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def post(self, request):
        cpf = request.data.get('cpf')
        email = request.data.get('email')

        return _responder_acao_operador(
            'remover_operador',
            'Não foi possível remover o acesso do operador agora.',
            lambda: remover_operador(cpf=cpf, email=email),
        )


class BeneficioViewSet(viewsets.ModelViewSet):
    queryset = Beneficio.objects.select_related('atualizado_por').all().order_by('nome')
    serializer_class = BeneficioSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    filter_backends = [filters.SearchFilter]
    search_fields = ['nome']

    def get_queryset(self):
        queryset = super().get_queryset().select_related('atualizado_por')
        ativo = self.request.query_params.get('ativo')
        updated_since = _parse_updated_since(self.request)

        if ativo is not None:
            queryset = queryset.filter(ativo=ativo.lower() == 'true')

        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)

        return queryset

    def update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar benefício.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para editar benefício.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if ADMIN_ROLE not in _request_roles(request):
            return Response(
                {'detail': 'Você não tem permissão para excluir benefício.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        beneficio = self.get_object()
        vinculados = Beneficiario.objects.filter(beneficio=beneficio)
        total_vinculos = vinculados.count()

        if total_vinculos:
            vinculados.delete()

        beneficio.delete()
        return Response(
            {
                'detail': 'Benefício excluído com sucesso.',
                'vinculos_removidos': total_vinculos,
            },
            status=status.HTTP_200_OK,
        )

    def perform_create(self, serializer):
        serializer.save(atualizado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(atualizado_por=self.request.user)


class BeneficioCidadaosView(APIView):
    serializer_class = BeneficioCidadaoSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    @extend_schema(
        responses={200: BeneficioCidadaoSerializer(many=True)},
    )
    def get(self, request, beneficio_id):
        get_object_or_404(Beneficio, pk=beneficio_id)
        vinculos = (
            Beneficiario.objects
            .select_related('cidadao', 'cidadao__documentos', 'beneficio')
            .filter(beneficio_id=beneficio_id)
            .order_by('cidadao__nome')
        )
        serializer = BeneficioCidadaoSerializer(vinculos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BeneficiarioViewSet(viewsets.ModelViewSet):
    queryset = (
        Beneficiario.objects
        .select_related('cidadao', 'beneficio', 'atualizado_por')
        .all()
        .order_by('-id')
    )
    serializer_class = BeneficiarioSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ['cidadao__nome', 'cidadao__documentos__cpf', 'beneficio__nome']
    filterset_fields = ['status', 'beneficio', 'cidadao']

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'cidadao',
            'cidadao__documentos',
            'beneficio',
            'atualizado_por',
        )

        cidadao_id = self.request.query_params.get('cidadao')
        beneficio_id = self.request.query_params.get('beneficio')
        status_param = self.request.query_params.get('status')
        updated_since = _parse_updated_since(self.request)

        if cidadao_id:
            queryset = queryset.filter(cidadao_id=cidadao_id)

        if beneficio_id:
            queryset = queryset.filter(beneficio_id=beneficio_id)

        if status_param:
            queryset = queryset.filter(status=status_param)

        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
            return queryset.order_by('atualizado_em', 'id')

        return queryset

    def perform_create(self, serializer):
        serializer.save(atualizado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(atualizado_por=self.request.user)

    @extend_schema(
        request=BeneficiarioSerializer(many=True),
        responses={200: BeneficiarioSerializer(many=True)},
    )
    @action(detail=False, methods=['post'], url_path='sincronizar')
    def sincronizar(self, request):
        payload = request.data
        if isinstance(payload, dict):
            payload = payload.get('vinculos') or payload.get('beneficiarios') or []

        if not isinstance(payload, list):
            return Response(
                {'detail': 'Envie uma lista de vínculos para sincronizar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        normalized_items = {}
        errors = []

        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                errors.append({'index': index, 'detail': 'Vínculo inválido.'})
                continue

            cidadao_id = item.get('cidadao') or item.get('cidadao_id') or item.get('cidadaoId')
            beneficio_id = (
                item.get('beneficio')
                or item.get('beneficio_id')
                or item.get('beneficioId')
            )

            if not cidadao_id or not beneficio_id:
                errors.append(
                    {
                        'index': index,
                        'detail': 'Informe cidadao e beneficio para o vínculo.',
                    }
                )
                continue

            try:
                cidadao_uuid = uuid.UUID(str(cidadao_id))
                beneficio_uuid = uuid.UUID(str(beneficio_id))
            except (TypeError, ValueError):
                errors.append({'index': index, 'detail': 'IDs de vínculo inválidos.'})
                continue

            status_vinculo = item.get('status') or 'EM_ANALISE'
            valid_statuses = {choice[0] for choice in Beneficiario.STATUS_CHOICES}
            if status_vinculo not in valid_statuses:
                errors.append({'index': index, 'detail': 'Status de vínculo inválido.'})
                continue

            normalized_items[(cidadao_uuid, beneficio_uuid)] = {
                'cidadao_id': cidadao_uuid,
                'beneficio_id': beneficio_uuid,
                'status': status_vinculo,
                'valor_recebido': item.get('valor_recebido'),
                'sincronizado': item.get('sincronizado', True),
                'status_sincronizacao': item.get(
                    'status_sincronizacao',
                    'SINCRONIZADO',
                ),
            }

        if errors:
            return Response(
                {
                    'detail': 'Alguns vínculos são inválidos.',
                    'errors': errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not normalized_items:
            return Response([], status=status.HTTP_200_OK)

        cidadao_ids = {item['cidadao_id'] for item in normalized_items.values()}
        beneficio_ids = {item['beneficio_id'] for item in normalized_items.values()}

        existing_cidadaos = set(
            Cidadao.objects.filter(id__in=cidadao_ids).values_list('id', flat=True)
        )
        existing_beneficios = set(
            Beneficio.objects.filter(id__in=beneficio_ids).values_list('id', flat=True)
        )

        missing_cidadaos = sorted(str(item) for item in cidadao_ids - existing_cidadaos)
        missing_beneficios = sorted(str(item) for item in beneficio_ids - existing_beneficios)
        if missing_cidadaos or missing_beneficios:
            return Response(
                {
                    'detail': 'Há vínculos apontando para cidadão ou benefício inexistente.',
                    'cidadaos_inexistentes': missing_cidadaos,
                    'beneficios_inexistentes': missing_beneficios,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        vinculos = [
            Beneficiario(
                cidadao_id=item['cidadao_id'],
                beneficio_id=item['beneficio_id'],
                status=item['status'],
                situacao_cadastro=item['status'],
                valor_recebido=item['valor_recebido'],
                atualizado_por=request.user,
                sincronizado=item['sincronizado'],
                status_sincronizacao=item['status_sincronizacao'],
                sincronizado_em=now if item['status_sincronizacao'] == 'SINCRONIZADO' else None,
                criado_em=now,
                atualizado_em=now,
            )
            for item in normalized_items.values()
        ]

        with transaction.atomic():
            Beneficiario.objects.bulk_create(
                vinculos,
                update_conflicts=True,
                update_fields=[
                    'status',
                    'situacao_cadastro',
                    'valor_recebido',
                    'atualizado_por',
                    'sincronizado',
                    'status_sincronizacao',
                    'sincronizado_em',
                    'atualizado_em',
                ],
                unique_fields=['cidadao', 'beneficio'],
            )

        pair_keys = set(normalized_items)
        queryset = (
            self.get_queryset()
            .filter(cidadao_id__in=cidadao_ids, beneficio_id__in=beneficio_ids)
            .order_by('atualizado_em', 'id')
        )
        synced_vinculos = [
            vinculo
            for vinculo in queryset
            if (vinculo.cidadao_id, vinculo.beneficio_id) in pair_keys
        ]
        serializer = self.get_serializer(synced_vinculos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CidadaoBeneficiosView(APIView):
    serializer_class = BeneficiarioSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    @extend_schema(
        responses={200: BeneficiarioSerializer(many=True)},
    )
    def get(self, request, cidadao_id):
        get_object_or_404(Cidadao, pk=cidadao_id)
        queryset = (
            Beneficiario.objects
            .select_related('cidadao', 'beneficio', 'atualizado_por')
            .filter(cidadao_id=cidadao_id)
            .order_by('-id')
        )
        serializer = BeneficiarioSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={201: BeneficiarioSerializer},
    )
    def post(self, request, cidadao_id):
        get_object_or_404(Cidadao, pk=cidadao_id)

        payload = request.data.copy()
        payload['cidadao'] = cidadao_id
        payload['beneficio'] = (
            payload.get('beneficio')
            or payload.get('beneficio_id')
            or payload.get('beneficioId')
        )

        serializer = BeneficiarioSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(atualizado_por=request.user)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CidadaoBeneficioDetailView(APIView):
    serializer_class = BeneficiarioSerializer
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = 'USER-BOLSA-TEFE'

    @extend_schema(
        responses={200: BeneficiarioSerializer},
    )
    def patch(self, request, cidadao_id, beneficio_id):
        vinculo = get_object_or_404(
            Beneficiario,
            cidadao_id=cidadao_id,
            beneficio_id=beneficio_id,
        )
        serializer = BeneficiarioSerializer(
            vinculo,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(atualizado_por=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={204: None},
    )
    def delete(self, request, cidadao_id, beneficio_id):
        vinculo = get_object_or_404(
            Beneficiario,
            cidadao_id=cidadao_id,
            beneficio_id=beneficio_id,
        )
        vinculo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]
    required_role = 'USER-BOLSA-TEFE-ADMIN'

    @extend_schema(
        responses={200: dict},
    )
    def get(self, request):
        beneficio_id = request.query_params.get('beneficio_id') or request.query_params.get('beneficio')
        sem_beneficio = str(request.query_params.get('sem_beneficio', '')).lower() in ('1', 'true', 'sim')

        cidadaos_qs = Cidadao.objects.all()
        beneficiarios_qs = Beneficiario.objects.all()

        if sem_beneficio:
            cidadaos_qs = cidadaos_qs.filter(beneficios_recebidos__isnull=True)
            beneficiarios_qs = beneficiarios_qs.none()
            total_beneficios = 0
        elif beneficio_id:
            cidadaos_qs = cidadaos_qs.filter(beneficios_recebidos__beneficio_id=beneficio_id).distinct()
            beneficiarios_qs = beneficiarios_qs.filter(beneficio_id=beneficio_id)
            total_beneficios = 1 if Beneficio.objects.filter(id=beneficio_id).exists() else 0
        else:
            total_beneficios = Beneficio.objects.count()

        total_cidadaos = cidadaos_qs.count()
        total_beneficiarios = beneficiarios_qs.values('cidadao_id').distinct().count()
        inicio_hoje = timezone.localtime(timezone.now()).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        fim_hoje = inicio_hoje + timedelta(days=1)
        atualizados_hoje = cidadaos_qs.filter(
            atualizado_em__gte=inicio_hoje,
            atualizado_em__lt=fim_hoje,
        ).count()

        cidadaos_por_status = cidadaos_qs.values('status_atualizacao').annotate(
            total=Count('id', distinct=True)
        )

        cidadaos_por_mes_qs = (
            cidadaos_qs
            .annotate(mes_data=TruncMonth('criado_em'))
            .values('mes_data')
            .annotate(total=Count('id', distinct=True))
            .order_by('mes_data')
        )

        atualizacoes_por_mes_qs = (
            cidadaos_qs
            .annotate(mes_data=TruncMonth('atualizado_em'))
            .values('mes_data')
            .annotate(total=Count('id', distinct=True))
            .order_by('mes_data')
        )

        cidadaos_por_mes = [
            {'mes': item['mes_data'].strftime('%Y-%m'), 'total': item['total']}
            for item in cidadaos_por_mes_qs
            if item['mes_data']
        ]
        atualizacoes_por_mes = [
            {'mes': item['mes_data'].strftime('%Y-%m'), 'total': item['total']}
            for item in atualizacoes_por_mes_qs
            if item['mes_data']
        ]

        beneficios_por_status = beneficiarios_qs.values('status').annotate(
            total=Count('id')
        )

        cidadaos_por_genero = cidadaos_qs.values('identidade_genero').annotate(
            total=Count('id', distinct=True)
        )

        atualizacao_por_bairro = (
            cidadaos_qs
            .filter(endereco__isnull=False)
            .annotate(
                bairro_label=Coalesce(
                    NullIf('endereco__bairro', Value('')),
                    NullIf('endereco__comunidade_localidade', Value('')),
                    NullIf('endereco__distrito', Value('')),
                    Value('Não informado'),
                )
            )
            .values('bairro_label')
            .annotate(
                total=Count('id', distinct=True),
                atualizados=Count('id', filter=Q(status_atualizacao='ATUALIZADO'), distinct=True),
                pendentes=Count('id', filter=Q(status_atualizacao='PENDENTE'), distinct=True),
                desatualizados=Count('id', filter=Q(status_atualizacao='DESATUALIZADO'), distinct=True),
            )
            .order_by('-total')
        )

        return Response({
            'total_cidadaos': total_cidadaos,
            'total_beneficios': total_beneficios,
            'total_beneficiarios': total_beneficiarios,
            'atualizados_hoje': atualizados_hoje,
            'cidadaos_por_status': list(cidadaos_por_status),
            'cidadaos_por_mes': cidadaos_por_mes,
            'atualizacoes_por_mes': atualizacoes_por_mes,
            'beneficios_por_status': list(beneficios_por_status),
            'cidadaos_por_genero': list(cidadaos_por_genero),
            'atualizacao_por_bairro': list(atualizacao_por_bairro),
        })


# ============================================================
# Geocodificação / Mapa de calor dos beneficiários
# ============================================================

GEO_STATUS_REPROCESSAVEIS = ['PENDENTE', 'ERRO', 'NAO_ENCONTRADO']


def _enderecos_para_geocodificar():
    """Endereços de beneficiários que precisam (ou podem) ser geocodificados.

    - pertencem a cidadãos com ao menos um benefício;
    - não são coordenadas manuais;
    - estão sem coordenada OU com status reprocessável;
    - possuem algum dado de endereço utilizável.
    """
    return (
        Endereco.objects
        .filter(cidadao__beneficios_recebidos__isnull=False)
        .filter(
            Q(geocodificacao_status__in=GEO_STATUS_REPROCESSAVEIS)
            | Q(latitude__isnull=True)
            | Q(longitude__isnull=True)
        )
        .exclude(precisao_geocodificacao='MANUAL')
        .filter(
            Q(logradouro__gt='')
            | Q(bairro__gt='')
            | Q(comunidade_localidade__gt='')
            | Q(distrito__gt='')
        )
        .select_related('cidadao')
        .distinct()
    )


class GeocodificarBeneficiariosView(APIView):
    """POST /api/geocodificacao/beneficiarios/processar/

    Geocodifica em lote os beneficiários pendentes e retorna um resumo.
    Aceita ``limit`` (padrão 50) para controlar quantos processar por chamada.
    """
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def post(self, request):
        from .services.geocoding import geocodificar_endereco

        try:
            limit = int(request.data.get('limit', 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))

        enderecos = list(_enderecos_para_geocodificar()[:limit])
        contadores = {'processados': 0, 'sucesso': 0, 'nao_encontrado': 0, 'erro': 0}

        logger.info('geocoding.lote_inicio total=%s limit=%s', len(enderecos), limit)
        for endereco in enderecos:
            resultado = geocodificar_endereco(endereco)
            contadores['processados'] += 1
            if resultado == 'OK':
                contadores['sucesso'] += 1
            elif resultado == 'NAO_ENCONTRADO':
                contadores['nao_encontrado'] += 1
            elif resultado == 'ERRO':
                contadores['erro'] += 1

        contadores['restantes'] = _enderecos_para_geocodificar().count()
        logger.info('geocoding.lote_fim %s', contadores)
        return Response(contadores)


class BeneficiariosPendentesView(APIView):
    """GET /api/geocodificacao/beneficiarios/pendentes/"""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def get(self, request):
        from .services.geocoding import montar_endereco_completo

        enderecos = _enderecos_para_geocodificar()[:500]
        dados = []
        for endereco in enderecos:
            dados.append({
                'id': str(endereco.cidadao_id),
                'nome': endereco.cidadao.nome,
                'bairro': endereco.comunidade_localidade or endereco.bairro or '',
                'rua': endereco.logradouro,
                'numero': endereco.numero or '',
                'endereco_geocodificado': (
                    endereco.endereco_geocodificado or montar_endereco_completo(endereco)
                ),
                'geocodificacao_status': endereco.geocodificacao_status,
                'geocodificacao_erro': endereco.geocodificacao_erro or '',
            })
        return Response(dados)


def _filtrar_enderecos_beneficiarios(params):
    """Aplica os filtros do mapa (exceto precisão/coordenada) sobre endereços
    de cidadãos beneficiários. Retorna o queryset (com .distinct())."""
    qs = Endereco.objects.filter(
        cidadao__beneficios_recebidos__isnull=False
    ).select_related('cidadao')

    beneficio_id = params.get('beneficio_id')
    if beneficio_id:
        qs = qs.filter(cidadao__beneficios_recebidos__beneficio_id=beneficio_id)

    status_benef = params.get('status')
    if status_benef:
        qs = qs.filter(cidadao__beneficios_recebidos__status=status_benef)

    zona = params.get('zona')
    if zona:
        qs = qs.filter(tipo_localizacao=zona)

    bairro = params.get('bairro')
    if bairro:
        qs = qs.filter(
            Q(bairro__icontains=bairro) | Q(comunidade_localidade__icontains=bairro)
        )

    visitado_por = params.get('visitado_por')
    if visitado_por:
        qs = qs.filter(cidadao__atualizado_por_id=visitado_por)

    data_inicio = params.get('data_inicio')
    if data_inicio:
        qs = qs.filter(cidadao__atualizado_em__date__gte=data_inicio)

    data_fim = params.get('data_fim')
    if data_fim:
        qs = qs.filter(cidadao__atualizado_em__date__lte=data_fim)

    return qs.distinct()


class MapaCalorBeneficiariosView(APIView):
    """GET /api/relatorios/mapa-calor-beneficiarios/

    Retorna beneficiários (cidadãos únicos) com coordenada válida. Sem CPF.
    """
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def get(self, request):
        params = request.query_params
        qs = _filtrar_enderecos_beneficiarios(params).filter(
            latitude__isnull=False, longitude__isnull=False
        )

        precisao = params.get('precisao')
        if precisao:
            qs = qs.filter(precisao_geocodificacao=precisao)

        try:
            limit = int(params.get('limit', 10000))
        except (TypeError, ValueError):
            limit = 10000
        limit = max(1, min(limit, 20000))

        qs = qs.prefetch_related(
            Prefetch(
                'cidadao__beneficios_recebidos',
                queryset=Beneficiario.objects.select_related('beneficio'),
            )
        )

        beneficio_id = params.get('beneficio_id')
        dados = []
        for endereco in qs[:limit]:
            cidadao = endereco.cidadao
            beneficiarios = list(cidadao.beneficios_recebidos.all())
            if beneficio_id:
                selecionado = next(
                    (b for b in beneficiarios if str(b.beneficio_id) == str(beneficio_id)),
                    None,
                )
            else:
                selecionado = next(
                    (b for b in beneficiarios if b.status == 'APROVADO'),
                    beneficiarios[0] if beneficiarios else None,
                )
            dados.append({
                'id': str(cidadao.id),
                'nome': cidadao.nome,
                'bairro': endereco.comunidade_localidade or endereco.bairro or '',
                'rua': endereco.logradouro,
                'numero': endereco.numero or '',
                'latitude': float(endereco.latitude),
                'longitude': float(endereco.longitude),
                'beneficio': selecionado.beneficio.nome if selecionado else '',
                'status': selecionado.status if selecionado else '',
                'status_atualizacao': cidadao.status_atualizacao,
                'precisao': endereco.precisao_geocodificacao,
                'geocodificacao_status': endereco.geocodificacao_status,
                'beneficios': [b.beneficio.nome for b in beneficiarios],
                'zona': endereco.tipo_localizacao or '',
            })

        return Response(dados)


class MapaCalorResumoView(APIView):
    """GET /api/relatorios/mapa-calor-beneficiarios/resumo/"""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def get(self, request):
        params = request.query_params
        base = _filtrar_enderecos_beneficiarios(params)

        total = base.count()
        com_coord_qs = base.filter(latitude__isnull=False, longitude__isnull=False)

        precisao = params.get('precisao')
        if precisao:
            com_coord_qs = com_coord_qs.filter(precisao_geocodificacao=precisao)

        registros = list(
            com_coord_qs.values(
                'bairro', 'comunidade_localidade', 'precisao_geocodificacao'
            )
        )
        com_coordenada = len(registros)

        por_bairro_map = {}
        por_precisao_map = {}
        for reg in registros:
            bairro = reg['comunidade_localidade'] or reg['bairro'] or 'Não informado'
            por_bairro_map[bairro] = por_bairro_map.get(bairro, 0) + 1
            prec = reg['precisao_geocodificacao'] or 'NAO_INFORMADO'
            por_precisao_map[prec] = por_precisao_map.get(prec, 0) + 1

        por_bairro = sorted(
            ({'bairro': k, 'total': v} for k, v in por_bairro_map.items()),
            key=lambda item: item['total'],
            reverse=True,
        )
        por_precisao = sorted(
            ({'precisao': k, 'total': v} for k, v in por_precisao_map.items()),
            key=lambda item: item['total'],
            reverse=True,
        )

        return Response({
            'total': total,
            'com_coordenada': com_coordenada,
            'sem_coordenada': total - com_coordenada,
            'maior_concentracao': por_bairro[0] if por_bairro else None,
            'por_bairro': por_bairro,
            'por_precisao': por_precisao,
        })


class EnderecoCoordManualView(APIView):
    """POST /api/geocodificacao/enderecos/<cidadao_id>/manual/

    Define manualmente a coordenada de um endereço (precisão MANUAL),
    que não será sobrescrita pelo reprocessamento automático.
    """
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def post(self, request, cidadao_id):
        endereco = get_object_or_404(Endereco, cidadao_id=cidadao_id)
        try:
            latitude = float(request.data.get('latitude'))
            longitude = float(request.data.get('longitude'))
        except (TypeError, ValueError):
            return Response(
                {'detail': 'latitude e longitude válidas são obrigatórias.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return Response(
                {'detail': 'Coordenadas fora do intervalo válido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Endereco.objects.filter(pk=endereco.pk).update(
            latitude=latitude,
            longitude=longitude,
            precisao_geocodificacao='MANUAL',
            geocodificacao_status='OK',
            geocodificacao_erro='',
            endereco_geocodificado='Coordenada definida manualmente',
            geocodificado_em=timezone.now(),
        )
        logger.info(
            'geocoding.manual cidadao=%s lat=%s lon=%s user=%s',
            cidadao_id, latitude, longitude, getattr(request.user, 'id', None),
        )
        return Response({
            'id': str(cidadao_id),
            'latitude': latitude,
            'longitude': longitude,
            'precisao': 'MANUAL',
            'geocodificacao_status': 'OK',
        })


class EnderecoReverseGeocodeView(APIView):
    """POST /api/geocodificacao/reverse/ — dado lat/long, retorna o endereço
    sugerido pelo Google (reverse geocoding). NÃO salva nada."""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def post(self, request):
        from .services.geocoding import reverse_geocode

        try:
            lat = float(request.data.get('latitude'))
            lon = float(request.data.get('longitude'))
        except (TypeError, ValueError):
            return Response({'detail': 'latitude e longitude válidas são obrigatórias.'}, status=400)

        sugestao = reverse_geocode(lat, lon)
        if not sugestao:
            return Response({'detail': 'O Google não retornou endereço para esse ponto.'}, status=404)
        return Response(sugestao)


class EnderecoCamposView(APIView):
    """PATCH /api/geocodificacao/enderecos/<cidadao_id>/campos/ — atualiza campos
    de endereço escolhidos (logradouro, numero, bairro, cep, complemento) sem
    mexer na coordenada nem disparar o reset de geocodificação."""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    CAMPOS_PERMITIDOS = ('logradouro', 'numero', 'bairro', 'cep', 'complemento')

    def patch(self, request, cidadao_id):
        endereco = get_object_or_404(Endereco, cidadao_id=cidadao_id)
        campos = {
            f: (request.data.get(f) or '')
            for f in self.CAMPOS_PERMITIDOS
            if f in request.data
        }
        if not campos:
            return Response({'detail': 'Nenhum campo para atualizar.'}, status=400)

        Endereco.objects.filter(pk=endereco.pk).update(**campos)
        return Response({'atualizados': list(campos.keys()), **campos})


# ============================================================
# Localidades do mapa de calor (coordenada curada por bairro)
# ============================================================

def _serializar_localidade(loc, total):
    return {
        'id': str(loc.id),
        'nome': loc.nome,
        'latitude': float(loc.latitude) if loc.latitude is not None else None,
        'longitude': float(loc.longitude) if loc.longitude is not None else None,
        'fonte': loc.fonte,
        'total_beneficiarios': total,
        'google_formatted': loc.google_formatted,
        'google_partial': loc.google_partial,
        'dentro_de_tefe': loc.dentro_de_tefe,
    }


class LocalidadesView(APIView):
    """GET /api/relatorios/localidades/ — lista as localidades com coordenada e contagem."""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def get(self, request):
        from .services.localidades import contagem_por_localidade, sincronizar_localidades

        sincronizar_localidades()
        contagem = contagem_por_localidade()
        locs = LocalidadeBeneficiario.objects.all()
        dados = [_serializar_localidade(loc, contagem.get(loc.nome, 0)) for loc in locs]
        dados.sort(key=lambda d: (d['latitude'] is not None, -d['total_beneficiarios']))
        return Response(dados)


class LocalidadeDetailView(APIView):
    """PATCH /api/relatorios/localidades/<id>/ — define a coordenada (manual) e
    aplica em todos os beneficiários da localidade."""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def patch(self, request, pk):
        from .services.localidades import aplicar_coordenada, contagem_por_localidade

        loc = get_object_or_404(LocalidadeBeneficiario, pk=pk)
        try:
            lat = float(request.data['latitude'])
            lon = float(request.data['longitude'])
        except (KeyError, TypeError, ValueError):
            return Response({'detail': 'latitude e longitude são obrigatórias.'}, status=400)

        loc.latitude = lat
        loc.longitude = lon
        loc.fonte = LocalidadeBeneficiario.FONTE_MANUAL
        loc.save()
        aplicados = aplicar_coordenada(loc)

        total = contagem_por_localidade().get(loc.nome, 0)
        resposta = _serializar_localidade(loc, total)
        resposta['enderecos_aplicados'] = aplicados
        return Response(resposta)


class LocalidadesAplicarView(APIView):
    """POST /api/relatorios/localidades/aplicar/ — reaplica todas as coordenadas
    definidas nos beneficiários (preservando pinos manuais por pessoa)."""
    permission_classes = [IsAuthenticated, HasRequiredRole]
    required_role = ADMIN_ROLE

    def post(self, request):
        from .services.localidades import aplicar_todas

        return Response(aplicar_todas())
