from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CidadaoViewSet,
    CidadaoDocumentosView,
    CidadaoDocumentoDetailView,
    CidadaoDocumentoPdfView,
    BuscarCidadaoNoTefeView,
    ImportarCidadaoDoTefeView,
    BeneficioViewSet,
    BeneficiarioViewSet,
    BeneficioCidadaosView,
    CidadaoBeneficiosView,
    CidadaoBeneficioDetailView,
    EscolaViewSet,
    LocalTefeViewSet,
    LocalidadeViewSet,
    RuaViewSet,
)

router = DefaultRouter()
router.register(r'cidadaos', CidadaoViewSet, basename='cidadao')
router.register(r'beneficios', BeneficioViewSet, basename='beneficio')
router.register(r'beneficiarios', BeneficiarioViewSet, basename='beneficiario')
router.register(r'escolas', EscolaViewSet, basename='escola')
router.register(r'locais-tefe', LocalTefeViewSet, basename='local-tefe')
router.register(r'localidades', LocalidadeViewSet, basename='localidade')
router.register(r'ruas', RuaViewSet, basename='rua')

urlpatterns = [
    # 🔎 Integração Tefé
    path(
        'cidadaos/buscar-no-tefe/',
        BuscarCidadaoNoTefeView.as_view(),
        name='buscar-cidadao-no-tefe'
    ),
    path(
        'cidadaos/importar-do-tefe/',
        ImportarCidadaoDoTefeView.as_view(),
        name='importar-cidadao-do-tefe'
    ),
    path(
        'cidadaos/<uuid:cidadao_id>/documentos/',
        CidadaoDocumentosView.as_view(),
        name='cidadao-documentos',
    ),
    path(
        'cidadaos/<uuid:cidadao_id>/documentos/<str:documento_ref>/',
        CidadaoDocumentoDetailView.as_view(),
        name='cidadao-documento-detail',
    ),
    path(
        'documentos/pdf/',
        CidadaoDocumentoPdfView.as_view(),
        name='documento-pdf',
    ),
    path(
        'cidadaos/<uuid:cidadao_id>/beneficios/',
        CidadaoBeneficiosView.as_view(),
        name='cidadao-beneficios'
    ),
    path(
        'cidadaos/<uuid:cidadao_id>/beneficios/<uuid:beneficio_id>/',
        CidadaoBeneficioDetailView.as_view(),
        name='cidadao-beneficio-detail'
    ),
    path(
        'beneficios/<uuid:beneficio_id>/cidadaos/',
        BeneficioCidadaosView.as_view(),
        name='beneficio-cidadaos'
    ),

    # 🚀 APIs principais
    path('', include(router.urls)),
]
