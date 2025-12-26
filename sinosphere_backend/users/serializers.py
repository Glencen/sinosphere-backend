from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from .models import UserProfile, UserWord
from dictionary.models import Word
from dictionary.serializers import WordSerializer

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'password_confirm')
        extra_kwargs = {
            'email': {'required': True},
        }
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Пароли не совпадают"})
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        return User.objects.create_user(**validated_data)

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserProfile
        fields = '__all__'

class UserWordSerializer(serializers.ModelSerializer):
    word_detail = WordSerializer(source='word', read_only=True)
    word_id = serializers.IntegerField(write_only=True, required=False)
    
    class Meta:
        model = UserWord
        fields = [
            'id', 'user', 'word', 'word_detail', 'word_id',
            'added_date', 'notes', 'is_learned', 'last_reviewed',
            'review_count', 'ease_factor'
        ]
        read_only_fields = [
            'user', 'added_date', 'last_reviewed', 
            'review_count', 'ease_factor'
        ]
        extra_kwargs = {
            'word': {'read_only': True},
        }
    
    def validate(self, attrs):
        request = self.context.get('request')
        if not request:
            return attrs
            
        if request.method == 'POST':
            user = request.user
            word_id = attrs.get('word_id')
            
            if word_id and UserWord.objects.filter(user=user, word_id=word_id).exists():
                raise serializers.ValidationError({
                    'word_id': 'Это слово уже есть в вашем словаре'
                })
        
        return attrs
    
    def create(self, validated_data):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            raise serializers.ValidationError("Пользователь не найден")
        
        word_id = validated_data.pop('word_id', None)
        if not word_id:
            raise serializers.ValidationError({"word_id": "Обязательное поле"})
        
        try:
            word = Word.objects.get(id=word_id)
        except Word.DoesNotExist:
            raise serializers.ValidationError({"word_id": "Слово не найдено"})
        
        return UserWord.objects.create(
            user=request.user,
            word=word,
            **validated_data
        )
    
    def update(self, instance, validated_data):
        validated_data.pop('word_id', None)
        
        if 'is_learned' in validated_data:
            is_learned = validated_data['is_learned']
            if is_learned and not instance.is_learned:
                instance.last_reviewed = timezone.now()
            elif not is_learned and instance.is_learned:
                instance.review_count = 0
        
        return super().update(instance, validated_data)

class UserWordReviewSerializer(serializers.Serializer):
    quality = serializers.IntegerField(min_value=0, max_value=5)
    
    def update(self, instance, validated_data):
        quality = validated_data['quality']
        
        if quality < 3:
            instance.review_count = 0
            instance.ease_factor = max(1.3, instance.ease_factor - 0.2)
        else:
            if instance.review_count == 0:
                interval = 1
            elif instance.review_count == 1:
                interval = 6
            else:
                interval = round(instance.review_count * instance.ease_factor)
            
            instance.ease_factor = instance.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            instance.ease_factor = max(1.3, instance.ease_factor)
            
            instance.last_reviewed = timezone.now()
            instance.review_count += 1
            
            if instance.review_count >= 5 and not instance.is_learned:
                instance.is_learned = True
        
        instance.save()
        return instance