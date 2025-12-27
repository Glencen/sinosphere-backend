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
    path('word-compositions/bulk/', views.BulkWordCompositionCreateView.as_view(), name='word-composition-bulk-create'),
    path('word-compositions/<int:pk>/', views.WordCompositionDetailView.as_view(), name='word-composition-detail'),
    
    # Теги слов
    path('word-tags/', views.WordTagListCreateView.as_view(), name='word-tag-list-create'),
    path('word-tags/<int:pk>/', views.WordTagDetailView.as_view(), name='word-tag-detail'),
    
    # Части речи слов
    path('word-parts-of-speech/', views.WordPartOfSpeechListCreateView.as_view(), name='word-pos-list-create'),
    path('word-parts-of-speech/<int:pk>/', views.WordPartOfSpeechDetailView.as_view(), name='word-pos-detail'),
    
    # Тэги
    path('tags/', views.TagListView.as_view(), name='tag-list'),
    path('tags/<str:name>/', views.TagDetailView.as_view(), name='tag-detail'),
    
    # Части речи
    path('parts-of-speech/', views.PartOfSpeechListView.as_view(), name='part-of-speech-list'),
    path('parts-of-speech/<str:name>/', views.PartOfSpeechDetailView.as_view(), name='part-of-speech-detail'),
    
    # Тэги конкретного слова
    path('words/<int:word_id>/tags/', views.WordTagsView.as_view(), name='word-tags'),
    path('words/<int:word_id>/tags/<str:tag_name>/', views.WordTagDetailByWordView.as_view(), name='word-tag-detail'),
    
    # Части речи конкретного слова
    path('words/<int:word_id>/parts-of-speech/', views.WordPartsOfSpeechView.as_view(), name='word-parts-of-speech'),
    path('words/<int:word_id>/parts-of-speech/<str:pos_name>/', views.WordPartOfSpeechDetailByWordView.as_view(), name='word-pos-detail'),

    # Темы
    path('topics/', views.TopicListView.as_view(), name='topic-list'),
    path('topics/<int:pk>/', views.TopicDetailView.as_view(), name='topic-detail'),
    path('topics/tree/', views.TopicTreeView.as_view(), name='topic-tree'),
    path('topics/<int:topic_id>/tags/', views.TopicTagsView.as_view(), name='topic-tags'),
    path('topics/<int:topic_id>/words/', views.WordsByTopicView.as_view(), name='words-by-topic'),
    
    # Примеры предложений
    path('example-sentences/', views.ExampleSentenceListView.as_view(), name='example-sentence-list'),
    path('example-sentences/<int:pk>/', views.ExampleSentenceDetailView.as_view(), name='example-sentence-detail'),
]