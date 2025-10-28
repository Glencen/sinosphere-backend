from rest_framework import serializers
from .models import Word, Dictionary, DictionaryEntry

class WordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Word
        fields = '__all__'

class DictionarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Dictionary
        fields = '__all__'

class DictionaryEntrySerializer(serializers.ModelSerializer):
    word = WordSerializer(read_only=True)
    word_id = serializers.PrimaryKeyRelatedField(
        queryset=Word.objects.all(), 
        source='word',
        write_only=True
    )
    
    class Meta:
        model = DictionaryEntry
        fields = '__all__'
        read_only_fields = ('added_date',)

class DictionaryDetailSerializer(serializers.ModelSerializer):
    entries = DictionaryEntrySerializer(many=True, read_only=True)
    entries_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Dictionary
        fields = '__all__'
    
    def get_entries_count(self, obj):
        return obj.entries.count()