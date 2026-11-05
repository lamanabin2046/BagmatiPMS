# your_app/templatetags/number_to_words.py

from django import template
from accounts.utils import NumberToNepaliWordsEnglish  # Import your utility class

register = template.Library()

@register.filter
def to_nepali_words_in_english(value):
    """
    Converts a number to Nepali words in English font.
    Usage: {{ number|to_nepali_words_in_english }}
    """
    try:
        number = int(value)
        return NumberToNepaliWordsEnglish.convert_to_words(number)
    except (ValueError, TypeError):
        return "Invalid number"  # Return a message if the input is not a valid number
