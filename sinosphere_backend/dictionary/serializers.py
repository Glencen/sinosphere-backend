from rest_framework import serializers
from django.db import transaction
from .models import Word, WordComposition, Tag, PartOfSpeech, WordTag, WordPartOfSpeech

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['name']

class PartOfSpeechSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartOfSpeech
        fields = ['name']

class WordCompositionSerializer(serializers.ModelSerializer):
    child_word_id = serializers.PrimaryKeyRelatedField(
        queryset=Word.objects.all(),
        source='child_word',
        write_only=True
    )
    parent_word_id = serializers.PrimaryKeyRelatedField(
        queryset=Word.objects.all(),
        source='parent_word',
        write_only=True
    )
    
    child_word_hanzi = serializers.CharField(source='child_word.hanzi', read_only=True)
    parent_word_hanzi = serializers.CharField(source='parent_word.hanzi', read_only=True)
    
    class Meta:
        model = WordComposition
        fields = [
            'id', 'child_word_id', 'parent_word_id', 
            'position', 'child_word_hanzi', 'parent_word_hanzi'
        ]


class WordTagSerializer(serializers.ModelSerializer):
    word_id = serializers.PrimaryKeyRelatedField(
        queryset=Word.objects.all(),
        source='word',
        write_only=True
    )
    tag_name = serializers.CharField(source='tag.name')
    
    class Meta:
        model = WordTag
        fields = ['id', 'word_id', 'tag_name']


class WordPartOfSpeechSerializer(serializers.ModelSerializer):
    word_id = serializers.PrimaryKeyRelatedField(
        queryset=Word.objects.all(),
        source='word',
        write_only=True
    )
    part_of_speech_name = serializers.CharField(source='part_of_speech.name')
    
    class Meta:
        model = WordPartOfSpeech
        fields = ['id', 'word_id', 'part_of_speech_name']


class WordSerializer(serializers.ModelSerializer):
    tags = WordTagSerializer(many=True, read_only=True, source='wordtags')
    parts_of_speech = WordPartOfSpeechSerializer(many=True, read_only=True, source='wordpartsofspeech')
    as_child = WordCompositionSerializer(many=True, read_only=True)
    parent_words = WordCompositionSerializer(many=True, read_only=True)
    
    tag_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False
    )
    part_of_speech_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Word
        fields = [
            'id', 'hanzi', 'pinyin_numeric', 'pinyin_graphic', 
            'translation', 'difficulty', 'tags', 'parts_of_speech',
            'as_child', 'parent_words', 'tag_names', 'part_of_speech_names'
        ]
    
    @transaction.atomic
    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        part_of_speech_names = validated_data.pop('part_of_speech_names', [])
        word = Word.objects.create(**validated_data)
        self._create_related_records(word, tag_names, part_of_speech_names)
        
        return word
    
    @transaction.atomic
    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        part_of_speech_names = validated_data.pop('part_of_speech_names', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if tag_names is not None:
            instance.tags.all().delete()
            self._create_related_records(instance, tag_names, [])
        
        if part_of_speech_names is not None:
            instance.parts_of_speech.all().delete()
            self._create_related_records(instance, [], part_of_speech_names)
        
        return instance
    
    def _create_related_records(self, word, tag_names, part_of_speech_names):
        for tag_name in tag_names:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            WordTag.objects.create(word=word, tag=tag)
        
        for pos_name in part_of_speech_names:
            pos, created = PartOfSpeech.objects.get_or_create(name=pos_name)
            WordPartOfSpeech.objects.create(word=word, part_of_speech=pos)