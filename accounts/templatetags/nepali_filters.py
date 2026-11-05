from django import template
from accounts.utils import NumberToNepaliWords


register = template.Library()

@register.filter
def to_devanagari_words(value):
    """
    Converts a number to Nepali words.
    Usage: {{ number|to_nepali_words }}
    """
    try:
        number = int(value)
        return NumberToNepaliWords.convert_to_words(number)
    except (ValueError, TypeError):
        return "अमान्य संख्या"  # Invalid number in Nepali
        

@register.filter
def get_item(dictionary, key):
    if dictionary:
        return dictionary.get(key)
    return None
