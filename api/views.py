import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone as datetime_timezone

from rest_framework import viewsets, status, filters
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
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
    Escola,
    LocalTefe,
    Localidade,
    Rua,
)
from .serializers import (
    CidadaoSerializer,
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

    filter_backends = [filters.SearchFilter]
    search_fields = ['nome', 'nis', 'documentos__cpf']

    def get_queryset(self):
        queryset = (
            Cidadao.objects
            .select_related(
                'documentos',
                'endereco',
                'socioeconomico',
                'termo_responsabilidade',
            )
            .prefetch_related('membros_familia', 'documentos_anexados')
        )
        updated_since = _parse_updated_since(self.request)
        if updated_since is not None:
            queryset = queryset.filter(atualizado_em__gt=updated_since)
        if self.action == 'list':
            return queryset.order_by('nome')
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


def _validar_upload_documento(tipo_documento, arquivo):
    tipos_validos = {choice[0] for choice in DocumentoAnexo.TIPOS_CHOICES}
    tipo_documento = normalize_documento_anexo_tipo(tipo_documento)
    if tipo_documento not in tipos_validos:
        return 'Tipo de documento inválido.'

    if arquivo is None:
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

        erro = _validar_upload_documento(tipo_documento, arquivo)
        if erro:
            return Response({'detail': erro}, status=status.HTTP_400_BAD_REQUEST)

        existente = DocumentoAnexo.objects.filter(
            cidadao=cidadao,
            tipo_documento=tipo_documento,
        ).first()

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

        extensao = Path(arquivo.name).suffix.replace('.', '').lower().strip()
        nome_original = Path(arquivo.name).name

        with transaction.atomic():
            if existente:
                if existente.arquivo:
                    try:
                        existente.arquivo.delete(save=False)
                    except Exception:
                        pass
                existente.arquivo = arquivo
                existente.nome_arquivo = nome_original
                existente.extensao = extensao
                existente.tamanho_bytes = arquivo.size
                existente.status = 'ENVIADO'
                existente.sincronizado = True
                existente.status_sincronizacao = 'SINCRONIZADO'
                existente.sincronizado_em = timezone.now()
                existente.save()
                documento = existente
            else:
                documento = DocumentoAnexo.objects.create(
                    cidadao=cidadao,
                    tipo_documento=tipo_documento,
                    arquivo=arquivo,
                    nome_arquivo=nome_original,
                    extensao=extensao,
                    tamanho_bytes=arquivo.size,
                    status='ENVIADO',
                    sincronizado=True,
                    status_sincronizacao='SINCRONIZADO',
                    sincronizado_em=timezone.now(),
                )

        serializer = DocumentoAnexoSerializer(documento, context={'request': request})
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
            .select_related('cidadao', 'beneficio')
            .filter(beneficio_id=beneficio_id)
            .order_by('cidadao__nome')
        )
        serializer = BeneficioCidadaoSerializer(vinculos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BeneficiarioViewSet(viewsets.ModelViewSet):
    queryset = (
        Beneficiario.objects
        .select_related('cidadao', 'beneficio')
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

        return queryset.distinct()

    def perform_create(self, serializer):
        serializer.save(atualizado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(atualizado_por=self.request.user)


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
            .select_related('cidadao', 'beneficio')
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
