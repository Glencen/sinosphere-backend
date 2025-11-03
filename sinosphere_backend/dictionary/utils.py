from django.core.exceptions import ObjectDoesNotExist, ValidationError
from .models import Dictionary, Word, DictionaryEntry

def get_or_create_global_dictionary():
    try:
        global_dict = Dictionary.objects.get(dictionary_type='global')
    except Dictionary.DoesNotExist:
        global_dict = Dictionary.objects.create(
            name='Глобальный словарь',
            dictionary_type='global'
        )
    return global_dict

def add_to_global_dictionary(word_data):
    global_dict = get_or_create_global_dictionary()
    word = Word.objects.create(**word_data)
    DictionaryEntry.objects.create(
        dictionary=global_dict,
        word=word
    )
    return word

def get_user_personal_dictionary(user):
    return user.profile.personal_dictionary

def get_global_dictionary():
    return get_or_create_global_dictionary()

def is_word_in_personal_dictionary(user, word):
    personal_dict = get_user_personal_dictionary(user)
    return DictionaryEntry.objects.filter(
        dictionary=personal_dict,
        word=word
    ).exists()

def add_to_personal_dictionary(user, word, notes=''):
    personal_dict = get_user_personal_dictionary(user)
    entry, created = DictionaryEntry.objects.get_or_create(
        dictionary=personal_dict,
        word=word,
        defaults={'notes': notes}
    )
    return entry, created
