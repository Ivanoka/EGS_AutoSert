import json
import os
from pathlib import Path


class JsonStore:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self.records = []

    def load(self):
        """
        Загружает существующие записи.
        """

        if not self.file_path.exists():
            self.records = []
            return self.records

        try:
            with self.file_path.open(
                "r",
                encoding="utf-8"
            ) as file:
                data = json.load(file)

            if not isinstance(data, list):
                raise ValueError(
                    "Корневой элемент JSON должен быть массивом."
                )

            self.records = data

        except (json.JSONDecodeError, OSError, ValueError) as error:
            raise RuntimeError(
                f"Не удалось загрузить JSON: {error}"
            ) from error

        return self.records

    @staticmethod
    def _normalize_login(login):
        if not isinstance(login, str):
            return ""

        return login.strip().casefold()

    def add(self, record):
        """
        Добавляет запись, если логин ещё не существует.
        """

        login = self._normalize_login(
            record.get("login")
        )

        if not login:
            return False

        for existing in self.records:
            existing_login = self._normalize_login(
                existing.get("login")
            )

            if existing_login == login:
                return False

        self.records.append(record)

        self.save()

        return True

    def save(self):
        """
        Атомарно сохраняет JSON через временный файл.
        """

        self.file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_path = self.file_path.with_suffix(
            self.file_path.suffix + ".tmp"
        )

        try:
            with temp_path.open(
                "w",
                encoding="utf-8"
            ) as file:
                json.dump(
                    self.records,
                    file,
                    ensure_ascii=False,
                    indent=4
                )

            os.replace(
                temp_path,
                self.file_path
            )

        finally:
            if temp_path.exists():
                temp_path.unlink()
