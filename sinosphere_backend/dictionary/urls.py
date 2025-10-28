from django.urls import path
from .views import (
    GlobalDictionaryView, WordListView,
    WordSearchView, AddToPersonalDictionaryView
)

urlpatterns = [
    path('global/', GlobalDictionaryView.as_view(), name='global_dictionary'),
    path('words/', WordListView.as_view(), name='words_list'),
    path('words/search/', WordSearchView.as_view(), name='word_search'),
    path('personal/add/', AddToPersonalDictionaryView.as_view(), name='add_to_personal'),
]