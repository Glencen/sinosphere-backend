from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import Word, Dictionary, DictionaryEntry

@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ('simplified', 'traditional', 'pinyin', 'translation')
    search_fields = ('simplified', 'traditional', 'pinyin', 'translation')
    list_filter = ('pinyin',)

@admin.register(Dictionary)
class DictionaryAdmin(admin.ModelAdmin):
    list_display = ('name', 'dictionary_type')
    list_filter = ('dictionary_type',)
    search_fields = ('name',)
    readonly_fields = ('dictionary_type',)

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            self.message_user(request, str(e), level='ERROR')

@admin.register(DictionaryEntry)
class DictionaryEntryAdmin(admin.ModelAdmin):
    list_display = ('dictionary', 'word', 'added_date')
    list_filter = ('added_date',)
    search_fields = ('dictionary__name', 'word__simplified')
