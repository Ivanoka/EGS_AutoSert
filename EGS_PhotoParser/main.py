from pathlib import Path

from services.ocr_service import OcrService
from services.data_extractor import DataExtractor
from services.json_store import JsonStore


BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "photos"
OUTPUT_FILE = BASE_DIR / "output" / "accounts.json"

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp"
}


def main():
    INPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    store = JsonStore(OUTPUT_FILE)

    records = store.load()

    print(f"Уже сохранено записей: {len(records)}")

    images = sorted(
        path
        for path in INPUT_DIR.iterdir()
        if (
            path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    )

    print(f"Найдено фотографий: {len(images)}")

    if not images:
        print("Нет фотографий для обработки.")
        return

    ocr = OcrService()

    prepared = []

    added = 0
    duplicates = 0
    failed = 0

    try:
        # ==================================================
        # ЭТАП 1. РУССКОЕ РАСПОЗНАВАНИЕ
        # ==================================================

        print("\n=== ЭТАП 1: РУССКОЕ РАСПОЗНАВАНИЕ ===")

        for index, image_path in enumerate(images, start=1):
            print(
                f"\n[{index}/{len(images)}] "
                f"Обработка: {image_path.name}"
            )

            try:
                document = ocr.recognize_document(image_path)

                record = DataExtractor.extract(
                    document["text"]
                )

                if record is None:
                    print("Не удалось найти URL.")
                    failed += 1
                    continue

                crops = document["crops"]

                if (
                    crops["login"] is None
                    or crops["password"] is None
                ):
                    print(
                        "Не удалось найти строку логина "
                        "или пароля."
                    )
                    failed += 1
                    continue

                prepared.append({
                    "image": image_path.name,
                    "record": record,
                    "crops": crops
                })

                print("Документ подготовлен.")

            except Exception as error:
                print(f"Ошибка обработки документа: {error}")
                failed += 1

        # ==================================================
        # ЭТАП 2. АНГЛИЙСКОЕ РАСПОЗНАВАНИЕ
        # ==================================================

        if prepared:
            print(
                "\n=== ЭТАП 2: АНГЛИЙСКОЕ РАСПОЗНАВАНИЕ ==="
            )

            # Освобождаем русскую модель и загружаем английскую.
            ocr.release_russian_model()

            for index, item in enumerate(prepared, start=1):
                print(
                    f"\n[{index}/{len(prepared)}] "
                    f"Обработка: {item['image']}"
                )

                try:
                    crops = item["crops"]

                    login = ocr.recognize_credential_crop(
                        crops["login"]
                    )

                    password = ocr.recognize_credential_crop(
                        crops["password"]
                    )

                    if not login or not password:
                        print(
                            "Не удалось распознать логин "
                            "или пароль."
                        )
                        failed += 1
                        continue

                    record = item["record"]

                    record["login"] = login
                    record["password"] = password
                    record["source_image"] = item["image"]

                    if store.add(record):
                        added += 1
                        print("Запись сохранена.")
                    else:
                        duplicates += 1
                        print("Дубликат логина. Запись пропущена.")

                except Exception as error:
                    print(f"Ошибка распознавания данных: {error}")
                    failed += 1

    finally:
        # Освобождаем обе модели независимо от результата обработки.
        ocr.close()

    # ==================================================
    # ИТОГИ
    # ==================================================

    print("\n========== РЕЗУЛЬТАТ ==========")

    print(f"Всего фотографий: {len(images)}")
    print(f"Подготовлено документов: {len(prepared)}")
    print(f"Добавлено записей: {added}")
    print(f"Дубликатов: {duplicates}")
    print(f"Ошибок: {failed}")
    print(f"Всего записей в базе: {len(store.records)}")

    print(f"\nРезультат сохранён: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()