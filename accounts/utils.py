class NumberToNepaliWords:
    NUMBER_WORDS = [
        "शून्य", "एक", "दुई", "तीन", "चार", "पाँच", "छ", "सात", "आठ", "नौ",
        "दश", "एघार", "बाह्र", "तेह्र", "चौध", "पन्ध्र", "सोह्र", "सत्र", "अठार", "उन्नाइस",
        "बीस", "एक्काइस", "बाइस", "तेइस", "चौबीस", "पच्चिस", "छब्बिस", "सत्ताइस", "अठ्ठाइस", "उनन्तीस",
        "तीस", "एकतीस", "बत्तीस", "तेत्तीस", "चौतीस", "पैंतीस", "छत्तीस", "सैतीस", "अठतीस", "उनन्चालीस",
        "चालीस", "एक चालिस", "बयालीस", "त्रिचालीस", "चवालीस", "पैंतालीस", "छयालीस", "सच्चालीस", "अठचालीस", "उनन्चास",
        "पचास", "एकाउन्न", "बाउन्न", "त्रिपन्न", "चौवन्न", "पचपन्न", "छपन्न", "सन्ताउन्न", "अन्ठाउन्न", "उनन्साठी",
        "साठी", "एकसाठी", "बयसाठी", "त्रिसाठी", "चौंसाठी", "पैंसाठी", "छयसाठी", "सडसाठी", "अठसाठी", "उनन्सत्तरी",
        "सत्तरी", "एकहत्तर", "बहत्तर", "त्रिहत्तर", "चौहत्तर", "पचहत्तर", "छयहत्तर", "सतहत्तर", "अठहत्तर", "उनासी",
        "असी", "एकासी", "बयासी", "त्रियासी", "चौरासी", "पचासी", "छयासी", "सत्तासी", "अठासी", "उनान्नब्बे",
        "नब्बे", "एकान्नब्बे", "बान्नब्बे", "त्रियान्नब्बे", "चौरान्नब्बे", "पन्चान्नब्बे", "छयान्नब्बे", "सन्तान्नब्बे", "अन्ठान्नब्बे", "उनान्सय"
    ]

    @staticmethod
    def two_digit_number_to_words(n):
        if 0 <= n < 100:
            return NumberToNepaliWords.NUMBER_WORDS[n]
        elif n == 100:
            return "सय"
        else:
            return ""

    @staticmethod
    def convert_to_words(n):
        if n == 0:
            return "शून्य"

        parts = []

        crore = n // 10000000
        if crore > 0:
            parts.append(NumberToNepaliWords.two_digit_number_to_words(crore) + " करोड")
        n %= 10000000

        lakh = n // 100000
        if lakh > 0:
            parts.append(NumberToNepaliWords.two_digit_number_to_words(lakh) + " लाख")
        n %= 100000

        thousand = n // 1000
        if thousand > 0:
            parts.append(NumberToNepaliWords.two_digit_number_to_words(thousand) + " हजार")
        n %= 1000

        hundred = n // 100
        if hundred > 0:
            parts.append(NumberToNepaliWords.NUMBER_WORDS[hundred] + " सय")
        n %= 100

        if n > 0:
            parts.append(NumberToNepaliWords.two_digit_number_to_words(n))

        return " ".join(parts).strip()


    
    
class NumberToNepaliWordsEnglish:
    UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    TENS = ["", "ten", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    TEENS = ["eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    HIGHER = ["hundred", "thousand", "lakh", "crore"]

    @staticmethod
    def convert_to_words(number):
        if number == 0:
            return "zero"

        def num_to_words(n, suffix):
            if n == 0:
                return ""
            if n < 10:
                return NumberToNepaliWordsEnglish.UNITS[n] + " " + suffix
            elif n < 20:
                return NumberToNepaliWordsEnglish.TEENS[n - 11] + " " + suffix
            elif n < 100:
                return (
                    NumberToNepaliWordsEnglish.TENS[n // 10]
                    + " "
                    + NumberToNepaliWordsEnglish.UNITS[n % 10]
                    + " "
                    + suffix
                )

        words = []
        place_values = [10000000, 100000, 1000, 100, 1]
        suffixes = ["crore", "lakh", "thousand", "hundred", ""]

        for pv, suf in zip(place_values, suffixes):
            part = number // pv
            number %= pv
            if part > 0:
                words.append(num_to_words(part, suf))

        return " ".join(words).strip()

