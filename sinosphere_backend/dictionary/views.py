from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Q
from .models import Word, Dictionary
from .serializers import (
    WordSerializer, DictionaryDetailSerializer
)
from .utils import add_to_personal_dictionary

class GlobalDictionaryView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = DictionaryDetailSerializer
    
    def get_queryset(self):
        return Dictionary.objects.filter(dictionary_type='global')

class WordListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WordSerializer
    queryset = Word.objects.all()

class WordSearchView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WordSerializer
    
    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        if not query:
            return Word.objects.none()
        
        return Word.objects.filter(
            Q(simplified__icontains=query) |
            Q(traditional__icontains=query) |
            Q(pinyin__icontains=query) |
            Q(translation__icontains=query)
        )

class AddToPersonalDictionaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        word_id = request.data.get('word_id')
        notes = request.data.get('notes', '')
        
        try:
            word = Word.objects.get(id=word_id)
            entry, created = add_to_personal_dictionary(request.user, word, notes)
            
            if created:
                return Response(
                    {"message": "Слово добавлено в словарь"},
                    status=status.HTTP_201_CREATED
                )
            else:
                return Response(
                    {"error": "Слово уже есть в словаре"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Word.DoesNotExist:
            return Response(
                {"error": "Слово не найдено"},
                status=status.HTTP_404_NOT_FOUND
            )