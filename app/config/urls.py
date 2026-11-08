from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.views.i18n import set_language
from django.conf import settings
from django.conf.urls.static import static
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions
from django_prometheus import exports

def health_check(request):
    return HttpResponse('OK', content_type='text/plain')

schema_view = get_schema_view(
    openapi.Info(
        title="RAG Search API",
        default_version='v1',
        description="API для поиска документов и чата с LLM",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('health/', health_check, name='health_check'),
    path('i18n/setlang/', set_language, name='set_language'),
    # FIX: был ещё path('api/', include(...)) — все маршруты rag.urls и так
    # начинаются с 'api/', двойное подключение порождало /api/api/search/ и т.п.
    path('', include('rag.urls')),
    path('metrics/', exports.ExportToDjangoView, name='prometheus-metrics'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    try:
        import debug_toolbar
        urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    except ImportError:
        pass