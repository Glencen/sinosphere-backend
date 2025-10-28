from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from dictionary.models import DictionaryEntry
from dictionary.serializers import DictionaryEntrySerializer
from .models import UserProfile
from .serializers import UserSerializer, UserProfileSerializer

User = get_user_model()

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserSerializer

class UserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        profile = UserProfile.objects.get(user=request.user)
        serializer = UserProfileSerializer(profile)
        return Response(serializer.data)

class PersonalDictionaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        personal_dict = request.user.profile.personal_dictionary
        entries = DictionaryEntry.objects.filter(
            dictionary=personal_dict
        ).select_related('word')
        serializer = DictionaryEntrySerializer(entries, many=True)
        return Response(serializer.data)