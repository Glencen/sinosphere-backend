from rest_framework import serializers
from django.db import transaction
from .models import Word, WordComposition, Tag, PartOfSpeech, WordTag, WordPartOfSpeech, Topic, ExampleSentence

class TopicSerializer(serializers.ModelSerializer):
    subtopics_count = serializers.SerializerMethodField()
    tags_count = serializers.SerializerMethodField()
    words_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Topic
        fields = [
            'id', 'name', 'description', 'parent_topic', 'weight', 'icon',
            'difficulty_level', 'is_active', 'order', 'subtopics_count',
            'tags_count', 'words_count'
        ]
    
    def get_subtopics_count(self, obj):
        return obj.subtopics.count()
    
    def get_tags_count(self, obj):
        return obj.tags.count()
    
    def get_words_count(self, obj):
        from django.db.models import Count
        tag_ids = obj.tags.values_list('id', flat=True)
        return WordTag.objects.filter(tag_id__in=tag_ids).values('word').distinct().count()

class TagSerializer(serializers.ModelSerializer):
    topic_info = TopicSerializer(source='topic', read_only=True)
    words_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Tag
        fields = ['id', 'name', 'topic', 'topic_info', 'description', 
                 'weight', 'frequency_rank', 'words_count']
    
    def get_words_count(self, obj):
        return obj.tagged_words.count()

class PartOfSpeechSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartOfSpeech
        fields = ['name']

class WordCompositionSerializer(serializers.ModelSerializer):
    child_word_hanzi = serializers.CharField(write_only=True, required=True)
    parent_word_hanzi = serializers.CharField(write_only=True, required=True)
    
    child_word_display = serializers.CharField(source='child_word.hanzi', read_only=True)
    parent_word_display = serializers.CharField(source='parent_word.hanzi', read_only=True)
    child_word_id = serializers.IntegerField(source='child_word.id', read_only=True)
    parent_word_id = serializers.IntegerField(source='parent_word.id', read_only=True)
    
    class Meta:
        model = WordComposition
        fields = [
            'id', 'child_word_hanzi', 'parent_word_hanzi', 'position',
            'child_word_display', 'parent_word_display', 'child_word_id', 'parent_word_id'
        ]
        read_only_fields = ['child_word_display', 'parent_word_display', 'child_word_id', 'parent_word_id']
    
    def validate_parent_word_hanzi(self, value):
        if len(value) > 1:
            raise serializers.ValidationError(
                "Родительское слово должно содержать только один иероглиф"
            )
        return value
    
    def validate(self, data):
        child_word_hanzi = data.get('child_word_hanzi')
        parent_word_hanzi = data.get('parent_word_hanzi')
        position = data.get('position')
        
        child_word, _ = Word.objects.get_or_create(
            hanzi=child_word_hanzi,
            defaults={
                'pinyin_numeric': '',
                'pinyin_graphic': '',
                'translation': '',
                'difficulty': 0
            }
        )
        
        parent_word, _ = Word.objects.get_or_create(
            hanzi=parent_word_hanzi,
            defaults={
                'pinyin_numeric': '',
                'pinyin_graphic': '',
                'translation': '',
                'difficulty': 0
            }
        )
        
        if (len(child_word.hanzi) > 1) and (position > len(child_word.hanzi)):
            raise serializers.ValidationError({
                'position': f"Позиция {position} превышает длину слова '{child_word}'"
            })
        
        if WordComposition.objects.filter(
            child_word=child_word, position=position
        ).exists():
            if self.instance is None or self.instance.position != position:
                raise serializers.ValidationError({
                    'position': f"Позиция {position} уже занята для слова '{child_word}'"
                })
        
        data['child_word'] = child_word
        data['parent_word'] = parent_word
        
        return data
    
    def create(self, validated_data):
        validated_data.pop('child_word_hanzi', None)
        validated_data.pop('parent_word_hanzi', None)
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        validated_data.pop('child_word_hanzi', None)
        validated_data.pop('parent_word_hanzi', None)
        
        return super().update(instance, validated_data)


class BulkWordCompositionSerializer(serializers.Serializer):
    child_word_hanzi = serializers.CharField(required=True)
    compositions = serializers.ListField(
        child=serializers.DictField(),
        required=True
    )
    
    def validate_compositions(self, value):
        if not value:
            raise serializers.ValidationError("Список композиций не может быть пустым")
        
        for comp in value:
            if 'parent_word_hanzi' not in comp or 'position' not in comp:
                raise serializers.ValidationError(
                    "Каждая композиция должна содержать 'parent_word_hanzi' и 'position'"
                )
            
            if len(comp['parent_word_hanzi']) > 1:
                raise serializers.ValidationError(
                    f"Родительское слово '{comp['parent_word_hanzi']}' должно содержать только один иероглиф"
                )
        
        parent_words = [comp['parent_word_hanzi'] for comp in value]
        positions = [comp['position'] for comp in value]
        
        if len(parent_words) != len(positions):
            raise serializers.ValidationError(
                "Количество parent_word и position должно быть одинаковым"
            )
        
        if len(positions) != len(set(positions)):
            raise serializers.ValidationError(
                "Позиции должны быть уникальными"
            )
        
        return value
    
    def validate(self, data):
        child_word_hanzi = data['child_word_hanzi']
        compositions = data['compositions']
        child_word, _ = Word.objects.get_or_create(
            hanzi=child_word_hanzi,
            defaults={
                'pinyin_numeric': '',
                'pinyin_graphic': '',
                'translation': '',
                'difficulty': 0
            }
        )
        
        positions = set()
        
        for comp in compositions:
            parent_word_hanzi = comp['parent_word_hanzi']
            position = comp['position']
            
            if position in positions:
                raise serializers.ValidationError({
                    'compositions': f"Позиция {position} указана несколько раз"
                })
            positions.add(position)
            
            if (len(child_word.hanzi) > 1) and (position > len(child_word.hanzi)):
                raise serializers.ValidationError({
                    'compositions': f"Позиция {position} превышает длину слова '{child_word.hanzi}'"
                })
            
            parent_word, _ = Word.objects.get_or_create(
                hanzi=parent_word_hanzi,
                defaults={
                    'pinyin_numeric': '',
                    'pinyin_graphic': '',
                    'translation': '',
                    'difficulty': 0
                }
            )
            
            comp['child_word'] = child_word
            comp['parent_word'] = parent_word
        
        return data
    
    def create(self, validated_data):
        compositions_data = validated_data.pop('compositions')
        created_compositions = []
        
        with transaction.atomic():
            child_word = compositions_data[0]['child_word']
            WordComposition.objects.filter(child_word=child_word).delete()
            
            for comp_data in compositions_data:
                composition = WordComposition.objects.create(
                    child_word=comp_data['child_word'],
                    parent_word=comp_data['parent_word'],
                    position=comp_data['position']
                )
                created_compositions.append(composition)
        
        return created_compositions
    
    def to_representation(self, instance):
        return WordCompositionSerializer(instance, many=True).data

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
    components = WordCompositionSerializer(many=True, read_only=True)
    used_in_words = WordCompositionSerializer(many=True, read_only=True)
    topics = serializers.SerializerMethodField()
    
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
            'components', 'used_in_words', 'topics', 'tag_names', 
            'part_of_speech_names'
        ]
    
    def get_topics(self, obj):
        topics = Topic.objects.filter(
            tags__tagged_words__word=obj
        ).distinct()
        return TopicSerializer(topics, many=True).data
    
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

class WordTagsSerializer(serializers.ModelSerializer):
    tag_name = serializers.CharField(source='tag.name')
    
    class Meta:
        model = WordTag
        fields = ['id', 'tag_name']


class WordPartsOfSpeechSerializer(serializers.ModelSerializer):
    part_of_speech_name = serializers.CharField(source='part_of_speech.name')
    
    class Meta:
        model = WordPartOfSpeech
        fields = ['id', 'part_of_speech_name']

class ExampleSentenceSerializer(serializers.ModelSerializer):
    word_info = WordSerializer(source='word', read_only=True)
    
    class Meta:
        model = ExampleSentence
        fields = [
            'id', 'word', 'word_info', 'chinese_sentence', 'pinyin_sentence',
            'translation', 'difficulty'
        ]