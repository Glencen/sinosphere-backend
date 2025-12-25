from django.urls import path
from . import views

urlpatterns = [
    # Основные операции со словами
    path('words/', views.WordListCreateView.as_view(), name='word-list-create'),
    path('words/<int:pk>/', views.WordDetailView.as_view(), name='word-detail'),
    
    # Поиск и фильтрация слов
    path('words/search/', views.WordSearchView.as_view(), name='word-search'),
    path('words/difficulty/<int:difficulty>/', views.WordByDifficultyView.as_view(), name='word-by-difficulty'),
    
    # Композиции слов
    path('word-compositions/', views.WordCompositionListCreateView.as_view(), name='word-composition-list-create'),
    path('word-compositions/<int:pk>/', views.WordCompositionDetailView.as_view(), name='word-composition-detail'),
    
    # Теги слов
    path('word-tags/', views.WordTagListCreateView.as_view(), name='word-tag-list-create'),
    path('word-tags/<int:pk>/', views.WordTagDetailView.as_view(), name='word-tag-detail'),
    
    # Части речи слов
    path('word-parts-of-speech/', views.WordPartOfSpeechListCreateView.as_view(), name='word-pos-list-create'),
    path('word-parts-of-speech/<int:pk>/', views.WordPartOfSpeechDetailView.as_view(), name='word-pos-detail'),
    
    # Тэги (справочник) - ТЕПЕРЬ С ВОЗМОЖНОСТЬЮ ИЗМЕНЕНИЯ
    path('tags/', views.TagListView.as_view(), name='tag-list'),
    path('tags/<str:name>/', views.TagDetailView.as_view(), name='tag-detail'),
    
    # Части речи (справочник) - ТЕПЕРЬ С ВОЗМОЖНОСТЬЮ ИЗМЕНЕНИЯ
    path('parts-of-speech/', views.PartOfSpeechListView.as_view(), name='part-of-speech-list'),
    path('parts-of-speech/<str:name>/', views.PartOfSpeechDetailView.as_view(), name='part-of-speech-detail'),
]