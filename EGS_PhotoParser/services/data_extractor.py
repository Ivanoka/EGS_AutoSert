import re


class DataExtractor:
    URL_PATTERN = re.compile(
        r"https?://[^\s<>()]+",
        re.IGNORECASE
    )

    @staticmethod
    def extract(text):
        """
        Извлекает URL из распознанного текста документа.
        """

        if not text:
            return None

        match = DataExtractor.URL_PATTERN.search(text)

        if not match:
            return None

        url = match.group(0).rstrip(".,;:!?")

        return {
            "url": url,
            "login": None,
            "password": None
        }
