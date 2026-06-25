from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CidadaoViewSet,
    CidadaoDocumentosView,
    CidadaoDocumentoDetailView,
    CidadaoDocumentoPdfView,
    BuscarCidadaoNoTefeView,
    ImportarCidadaoDoTefeView,
    LiberarOperadorView,
    RemoverOperadorView,
    BuscarOperadorView,
    BeneficioViewSet,
    BeneficiarioViewSet,
    BeneficioCidadaosView,
    CidadaoBeneficiosView,
    CidadaoBeneficioDetailView,
    DashboardStatsView,
    EscolaViewSet,
    LocalTefeViewSet,
    LocalidadeViewSet,
    RuaViewSet,
    GeocodificarBeneficiariosView,
    BeneficiariosPendentesView,
    MapaCalorBeneficiariosView,
    MapaCalorResumoView,
    EnderecoCoordManualView,
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
        'usuarios/operadores/buscar/',
        BuscarOperadorView.as_view(),
        name='buscar-operador',
    ),
    path(
        'usuarios/liberar-operador/',
        LiberarOperadorView.as_view(),
        name='liberar-operador',
    ),
    path(
        'usuarios/remover-operador/',
        RemoverOperadorView.as_view(),
        name='remover-operador',
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

    path(
        'dashboard/stats/',
        DashboardStatsView.as_view(),
        name='dashboard-stats'
    ),

    # 🗺️ Geocodificação / Mapa de calor
    path(
        'geocodificacao/beneficiarios/processar/',
        GeocodificarBeneficiariosView.as_view(),
        name='geocodificar-beneficiarios',
    ),
    path(
        'geocodificacao/beneficiarios/pendentes/',
        BeneficiariosPendentesView.as_view(),
        name='beneficiarios-pendentes',
    ),
    path(
        'geocodificacao/enderecos/<uuid:cidadao_id>/manual/',
        EnderecoCoordManualView.as_view(),
        name='endereco-coord-manual',
    ),
    path(
        'relatorios/mapa-calor-beneficiarios/',
        MapaCalorBeneficiariosView.as_view(),
        name='mapa-calor-beneficiarios',
    ),
    path(
        'relatorios/mapa-calor-beneficiarios/resumo/',
        MapaCalorResumoView.as_view(),
        name='mapa-calor-beneficiarios-resumo',
    ),

    # 🚀 APIs principais
    path('', include(router.urls)),
]
