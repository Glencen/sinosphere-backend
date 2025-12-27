from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/dictionary/', include('dictionary.urls')),
    path('api/learning/', include('learning.urls')),
]
