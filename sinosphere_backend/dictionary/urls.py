from django.urls import path
from .views import (
    GlobalDictionaryView, WordListView,
    WordSearchView, AddToPersonalDictionaryView,
    PersonalDictionaryView, CheckWordInDictionaryView,
    RemoveFromPersonalDictionaryView
)

urlpatterns = [
    path('global/', GlobalDictionaryView.as_view(), name='global_dictionary'),
    path('words/', WordListView.as_view(), name='words_list'),
    path('words/search/', WordSearchView.as_view(), name='word_search'),
    path('personal/add/', AddToPersonalDictionaryView.as_view(), name='add_to_personal'),
    path('personal/', PersonalDictionaryView.as_view(), name='personal_dictionary'),
    path('personal/check/<int:word_id>/', CheckWordInDictionaryView.as_view(), name='check_word_in_dictionary'),
    path('personal/remove/<int:entry_id>/', RemoveFromPersonalDictionaryView.as_view(), name='remove_from_personal'),
]