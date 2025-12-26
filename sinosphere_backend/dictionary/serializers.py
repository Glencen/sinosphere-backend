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
        
        if position > len(child_word.hanzi):
            raise serializers.ValidationError({
                'position': f"Позиция {position} превышает длину слова '{child_word.hanzi}'"
            })
        
        expected_hanzi = child_word.hanzi[position - 1]
        if parent_word.hanzi != expected_hanzi:
            raise serializers.ValidationError({
                'parent_word_hanzi': (
                    f"Иероглиф '{parent_word.hanzi}' не совпадает с иероглифом "
                    f"'{expected_hanzi}' на позиции {position} в слове '{child_word.hanzi}'"
                )
            })
        
        if WordComposition.objects.filter(
            child_word=child_word, position=position
        ).exists():
            if self.instance is None or self.instance.position != position:
                raise serializers.ValidationError({
                    'position': f"Позиция {position} уже занята для слова '{child_word.hanzi}'"
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
        
        for comp in compositions:
            parent_word_hanzi = comp['parent_word_hanzi']
            position = comp['position']
            
            if position > len(child_word.hanzi):
                raise serializers.ValidationError({
                    'compositions': f"Позиция {position} превышает длину слова '{child_word.hanzi}'"
                })
            
            expected_hanzi = child_word.hanzi[position - 1]
            if parent_word_hanzi != expected_hanzi:
                raise serializers.ValidationError({
                    'compositions': (
                        f"Иероглиф '{parent_word_hanzi}' не совпадает с иероглифом "
                        f"'{expected_hanzi}' на позиции {position} в слове '{child_word.hanzi}'"
                    )
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
            'components', 'used_in_words', 'tag_names', 'part_of_speech_names'
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