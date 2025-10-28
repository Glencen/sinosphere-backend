from django.contrib import admin
from .models import Word, Dictionary, DictionaryEntry

@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ('simplified', 'traditional', 'pinyin', 'translation')
    search_fields = ('simplified', 'traditional', 'pinyin', 'translation')
    list_filter = ('pinyin',)

@admin.register(Dictionary)
class DictionaryAdmin(admin.ModelAdmin):
    list_display = ('name', 'dictionary_type', 'is_public', 'created_at')
    list_filter = ('dictionary_type', 'is_public')
    search_fields = ('name', 'description')

@admin.register(DictionaryEntry)
class DictionaryEntryAdmin(admin.ModelAdmin):
    list_display = ('dictionary', 'word', 'added_date')
    list_filter = ('added_date')
    search_fields = ('dictionary__name', 'word__simplified')