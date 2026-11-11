
import os
import re
import shutil

from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier
from cryptography.hazmat.primitives.serialization import pkcs7


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

SOURCE_DIR = BASE_DIR / "input"
DESTINATION_DIR = BASE_DIR / "output"

SUPPORTED_EXTENSIONS = {".cer", ".p7b"}

# SN — Surname (2.5.4.4)
SURNAME_OID = NameOID.SURNAME

# 2.5.4.41 — Name
NAME_OID = ObjectIdentifier("2.5.4.41")


# ============================================================
# CERTIFICATE READING
# ============================================================

def load_certificates(file_path: Path) -> list[x509.Certificate]:
    """
    Loads X.509 certificates from CER or PKCS#7 files.
    Supports DER and PEM formats.
    """

    data = file_path.read_bytes()

    if file_path.suffix.lower() == ".p7b":
        try:
            return pkcs7.load_der_pkcs7_certificates(data)
        except ValueError:
            try:
                return pkcs7.load_pem_pkcs7_certificates(data)
            except ValueError:
                return []

    elif file_path.suffix.lower() == ".cer":
        try:
            return [x509.load_der_x509_certificate(data)]
        except ValueError:
            try:
                return [x509.load_pem_x509_certificate(data)]
            except ValueError:
                return []

    return []


# ============================================================
# SUBJECT EXTRACTION
# ============================================================

def get_subject_name(
    certificate: x509.Certificate
) -> tuple[str, str] | None:
    """
    Extracts:
        SN       (2.5.4.4)  - Surname
        2.5.4.41            - Name
    """

    subject = certificate.subject

    surnames = subject.get_attributes_for_oid(SURNAME_OID)
    names = subject.get_attributes_for_oid(NAME_OID)

    if not surnames or not names:
        return None

    surname = surnames[0].value.strip()
    name = names[0].value.strip()

    if not surname or not name:
        return None

    return surname, name


# ============================================================
# FILE NAMING
# ============================================================

def sanitize_filename(name: str) -> str:
    """
    Removes characters forbidden in Windows filenames.
    """

    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)

    return name.strip(" .")


def get_unique_path(path: Path) -> Path:
    """
    Generates a unique filename if the destination already exists.
    """

    if not path.exists():
        return path

    counter = 1

    while True:
        new_path = path.with_name(
            f"{path.stem} ({counter}){path.suffix}"
        )

        if not new_path.exists():
            return new_path

        counter += 1


# ============================================================
# FILE PROCESSING
# ============================================================

def process_file(file_path: Path) -> bool:

    try:
        certificates = load_certificates(file_path)

        if not certificates:
            print(f"[SKIP] Сертификаты не найдены: {file_path}")
            return False

        subject_data = None

        # Find the first certificate with required attributes.
        for certificate in certificates:
            subject_data = get_subject_name(certificate)

            if subject_data:
                break

        if not subject_data:
            print(f"[SKIP] Не найдены необходимые атрибуты: {file_path}")
            return False

        surname, name = subject_data

        filename = sanitize_filename(
            f"{surname} {name}"
        )

        if not filename:
            print(f"[SKIP] Некорректное имя файла: {file_path}")
            return False

        destination = DESTINATION_DIR / (
            filename + file_path.suffix.lower()
        )

        destination = get_unique_path(destination)

        shutil.move(
            str(file_path),
            str(destination)
        )

        print(f"[OK] {file_path.name} -> {destination.name}")

        return True

    except Exception as error:
        print(f"[ERROR] {file_path}: {error}")
        return False


# ============================================================
# EMPTY DIRECTORY CLEANUP
# ============================================================

def remove_empty_directories() -> int:
    """
    Removes empty subdirectories from input.
    The input directory itself is preserved.
    """

    removed = 0

    for current_dir, dirs, files in os.walk(
        SOURCE_DIR,
        topdown=False
    ):

        directory = Path(current_dir)

        if directory == SOURCE_DIR:
            continue

        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                removed += 1

                print(f"[CLEANUP] Удалена пустая папка: {directory}")

        except OSError:
            # Directory is not empty or cannot be removed.
            pass

    return removed


# ============================================================
# DIRECTORY SCANNING
# ============================================================

def scan_directory():

    if not SOURCE_DIR.exists():
        print(f"[ERROR] Исходная папка не найдена: {SOURCE_DIR}")
        return

    if not SOURCE_DIR.is_dir():
        print(f"[ERROR] Путь input не является папкой: {SOURCE_DIR}")
        return

    # Prevent output from being inside input.
    source = SOURCE_DIR.resolve()
    destination = DESTINATION_DIR.resolve()

    if destination == source or source in destination.parents:
        print("[ERROR] Папка output не должна находиться внутри input.")
        return

    DESTINATION_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    total = 0
    successful = 0
    failed = 0

    print("=" * 60)
    print("CERTIFICATE SORTER")
    print("=" * 60)

    print(f"Источник: {source}")
    print(f"Результат: {destination}")
    print()

    # Recursive directory scanning.
    for current_dir, dirs, files in os.walk(source):

        for filename in files:

            file_path = Path(current_dir) / filename

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            total += 1

            if process_file(file_path):
                successful += 1
            else:
                failed += 1

    # Remove empty directories after processing.
    print("\nОчистка пустых папок...")

    removed_directories = remove_empty_directories()

    # Summary.
    print()
    print("=" * 60)
    print("ОБРАБОТКА ЗАВЕРШЕНА")
    print("=" * 60)

    print(f"Всего найдено сертификатов: {total}")
    print(f"Успешно перемещено:          {successful}")
    print(f"Ошибок:                      {failed}")
    print(f"Удалено пустых папок:        {removed_directories}")

    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        scan_directory()

    except KeyboardInterrupt:
        print("\n[INFO] Обработка прервана пользователем.")

    except Exception as error:
        print(f"\n[FATAL ERROR] {error}")