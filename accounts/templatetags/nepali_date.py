# templatetags/nepali_date.py
from django import template
from datetime import datetime

register = template.Library()

# Nepali number dictionary for conversion
nepali_numbers = {
    "0": "०",
    "1": "१",
    "2": "२",
    "3": "३",
    "4": "४",
    "5": "५",
    "6": "६",
    "7": "७",
    "8": "८",
    "9": "९",
}

# Function to convert English numbers to Nepali
def english_to_nepali(date_str):
    if not date_str:
        return ""
    # Replace English numbers with Nepali numbers
    for en, np in nepali_numbers.items():
        date_str = date_str.replace(en, np)
    return date_str

# Register the 'nepali_date' filter
@register.filter
def nepali_date(value):
    """
    Custom template filter to convert an English date (YYYY-MM-DD) to Nepali numbers.
    """
    try:
        # Convert the date to a string if it's a date object
        if isinstance(value, datetime):
            value = value.strftime("%Y-%m-%d")
        return english_to_nepali(value)
    except Exception:
        return value

# Register the 'to_nepali_number' filter
@register.filter
def to_nepali_number(value):
    eng_to_nepali_digits = str.maketrans("0123456789", "०१२३४५६७८९")
    return str(value).translate(eng_to_nepali_digits)
