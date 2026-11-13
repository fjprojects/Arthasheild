from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({
        "status": "healthy",
        "service": "ArthaShield Backend API",
        "version": "1.0.0",
        "privacy_mode": "ZERO_KNOWLEDGE_PII_PROTECTED"
    })

urlpatterns = [
    path('', health_check, name='health-check'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('api.urls')),
]
