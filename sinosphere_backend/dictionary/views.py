from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Word, WordComposition, Tag, PartOfSpeech, WordTag, WordPartOfSpeech
from .serializers import (
    WordSerializer, WordCompositionSerializer, TagSerializer, 
    PartOfSpeechSerializer, WordTagSerializer, WordPartOfSpeechSerializer,
    BulkWordCompositionSerializer
)

class WordListCreateView(APIView):
    """
    API для получения списка слов и создания нового слова
    """
    def get(self, request):
        words = Word.objects.all()
        serializer = WordSerializer(words, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = WordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordDetailView(APIView):
    """
    API для получения, обновления и удаления конкретного слова
    """
    def get(self, request, pk):
        word = get_object_or_404(Word, pk=pk)
        serializer = WordSerializer(word)
        return Response(serializer.data)
    
    def put(self, request, pk):
        word = get_object_or_404(Word, pk=pk)
        serializer = WordSerializer(word, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, pk):
        word = get_object_or_404(Word, pk=pk)
        serializer = WordSerializer(word, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        word = get_object_or_404(Word, pk=pk)
        word.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class WordCompositionListCreateView(APIView):
    """
    API для управления композициями слов
    """
    def get(self, request):
        compositions = WordComposition.objects.all()
        serializer = WordCompositionSerializer(compositions, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        if 'child_word_hanzi' in request.data and 'compositions' in request.data:
            serializer = BulkWordCompositionSerializer(data=request.data)
        else:
            serializer = WordCompositionSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BulkWordCompositionCreateView(APIView):
    """
    API для массового создания композиций слов
    """
    def post(self, request):
        serializer = BulkWordCompositionSerializer(data=request.data)
        if serializer.is_valid():
            compositions = serializer.save()
            return Response(
                WordCompositionSerializer(compositions, many=True).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class WordCompositionDetailView(APIView):
    """
    API для управления конкретной композицией слова
    """
    def get(self, request, pk):
        composition = get_object_or_404(WordComposition, pk=pk)
        serializer = WordCompositionSerializer(composition)
        return Response(serializer.data)
    
    def put(self, request, pk):
        composition = get_object_or_404(WordComposition, pk=pk)
        serializer = WordCompositionSerializer(composition, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        composition = get_object_or_404(WordComposition, pk=pk)
        composition.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WordTagListCreateView(APIView):
    """
    API для управления тегами слов
    """
    def get(self, request):
        word_tags = WordTag.objects.all()
        serializer = WordTagSerializer(word_tags, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = WordTagSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordTagDetailView(APIView):
    """
    API для управления конкретным тегом слова
    """
    def get(self, request, pk):
        word_tag = get_object_or_404(WordTag, pk=pk)
        serializer = WordTagSerializer(word_tag)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        word_tag = get_object_or_404(WordTag, pk=pk)
        word_tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WordPartOfSpeechListCreateView(APIView):
    """
    API для управления частями речи слов
    """
    def get(self, request):
        word_pos = WordPartOfSpeech.objects.all()
        serializer = WordPartOfSpeechSerializer(word_pos, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = WordPartOfSpeechSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordPartOfSpeechDetailView(APIView):
    """
    API для управления конкретной частью речи слова
    """
    def get(self, request, pk):
        word_pos = get_object_or_404(WordPartOfSpeech, pk=pk)
        serializer = WordPartOfSpeechSerializer(word_pos)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        word_pos = get_object_or_404(WordPartOfSpeech, pk=pk)
        word_pos.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TagListView(APIView):
    """
    API для получения списка всех тегов и добавления нового
    """
    def get(self, request):
        tags = Tag.objects.all()
        serializer = TagSerializer(tags, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = TagSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class TagDetailView(APIView):
    """
    API для получения, обновления и удаления конкретного тега
    """
    def get(self, request, name):
        tag = get_object_or_404(Tag, name=name)
        serializer = TagSerializer(tag)
        return Response(serializer.data)
    
    def put(self, request, name):
        tag = get_object_or_404(Tag, name=name)
        serializer = TagSerializer(tag, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, name):
        tag = get_object_or_404(Tag, name=name)
        serializer = TagSerializer(tag, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, name):
        tag = get_object_or_404(Tag, name=name)
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PartOfSpeechListView(APIView):
    """
    API для получения списка всех частей речи и добавления новой
    """
    def get(self, request):
        parts_of_speech = PartOfSpeech.objects.all()
        serializer = PartOfSpeechSerializer(parts_of_speech, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = PartOfSpeechSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class PartOfSpeechDetailView(APIView):
    """
    API для получения, обновления и удаления конкретной части речи
    """
    def get(self, request, name):
        part_of_speech = get_object_or_404(PartOfSpeech, name=name)
        serializer = PartOfSpeechSerializer(part_of_speech)
        return Response(serializer.data)
    
    def put(self, request, name):
        part_of_speech = get_object_or_404(PartOfSpeech, name=name)
        serializer = PartOfSpeechSerializer(part_of_speech, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, name):
        part_of_speech = get_object_or_404(PartOfSpeech, name=name)
        serializer = PartOfSpeechSerializer(part_of_speech, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, name):
        part_of_speech = get_object_or_404(PartOfSpeech, name=name)
        part_of_speech.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WordSearchView(APIView):
    """
    API для поиска слов по различным критериям
    """
    
    def get(self, request):
        query_params = request.query_params
        
        queryset = Word.objects.all()
        
        search_query = query_params.get('q')
        
        if search_query:
            queryset = queryset.filter(
                Q(hanzi__icontains=search_query) |
                Q(pinyin_numeric__icontains=search_query) |
                Q(pinyin_graphic__icontains=search_query) |
                Q(translation__icontains=search_query)
            )
        
        difficulty = query_params.get('difficulty')
        if difficulty:
            queryset = queryset.filter(difficulty=difficulty)
        
        tag = query_params.get('tag')
        if tag:
            queryset = queryset.filter(tags__tag__name=tag)
        
        part_of_speech = query_params.get('part_of_speech')
        if part_of_speech:
            queryset = queryset.filter(parts_of_speech__part_of_speech__name=part_of_speech)
        
        serializer = WordSerializer(queryset.distinct(), many=True)
        return Response(serializer.data)


class WordByDifficultyView(APIView):
    """
    API для получения слов по уровню сложности HSK
    """
    def get(self, request, difficulty):
        words = Word.objects.filter(difficulty=difficulty)
        serializer = WordSerializer(words, many=True)
        return Response(serializer.data)