from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Q
from .models import Word, Dictionary, DictionaryEntry
from .serializers import (
    WordSerializer, DictionaryDetailSerializer, DictionaryEntrySerializer
)
from .utils import add_to_personal_dictionary, is_word_in_personal_dictionary, get_user_personal_dictionary

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
        
        import re
        clean_query = re.sub(r'[1-5]', '', query)
        
        return Word.objects.filter(
            Q(simplified__icontains=query) |
            Q(traditional__icontains=query) |
            Q(pinyin__icontains=query) |
            Q(translation__icontains=query) |
            Q(pinyin__icontains=clean_query)
        ).distinct()[:100]

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
        
class CheckWordInDictionaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, word_id):
        try:
            word = Word.objects.get(id=word_id)
            is_in_dictionary = is_word_in_personal_dictionary(request.user, word)
            
            return Response({
                'word_id': word_id,
                'is_in_dictionary': is_in_dictionary
            })
            
        except Word.DoesNotExist:
            return Response(
                {"error": "Слово не найдено"},
                status=status.HTTP_404_NOT_FOUND
            )

class RemoveFromPersonalDictionaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request, entry_id):
        try:
            personal_dict = get_user_personal_dictionary(request.user)
            entry = DictionaryEntry.objects.get(
                id=entry_id,
                dictionary=personal_dict
            )
            word_simplified = entry.word.simplified
            entry.delete()
            
            return Response(
                {"message": f"Слово '{word_simplified}' удалено из вашего словаря"},
                status=status.HTTP_200_OK
            )
            
        except DictionaryEntry.DoesNotExist:
            return Response(
                {"error": "Запись не найдена в вашем словаре"},
                status=status.HTTP_404_NOT_FOUND
            )

class PersonalDictionaryView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DictionaryEntrySerializer
    
    def get_queryset(self):
        personal_dict = get_user_personal_dictionary(self.request.user)
        return DictionaryEntry.objects.filter(
            dictionary=personal_dict
        ).select_related('word').order_by('-added_date')
