import asyncio
import json
import logging
import random

from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

ACCOUNTS_FILE = Path("accounts.json")
DOWNLOAD_DIR = Path("downloads")

ALLOWED_EXTENSIONS = {".cer", ".p7b"}

HEADLESS = False

PAGE_TIMEOUT = 30_000
DOWNLOAD_TIMEOUT = 30_000

# Случайные задержки в секундах
LOGIN_DELAY = (1.0, 3.0)
DOWNLOAD_DELAY = (1.0, 3.0)
ACCOUNT_DELAY = (5.0, 15.0)


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def random_delay(delay_range: tuple[float, float]) -> None:
    """Ожидание случайного количества секунд."""

    delay = random.uniform(*delay_range)

    logger.debug("Ожидание %.2f сек.", delay)

    await asyncio.sleep(delay)


def load_accounts() -> list[dict]:
    """Загрузка и проверка учётных записей из JSON."""

    if not ACCOUNTS_FILE.exists():
        raise FileNotFoundError(
            f"Файл конфигурации не найден: {ACCOUNTS_FILE}"
        )

    with ACCOUNTS_FILE.open("r", encoding="utf-8") as file:
        accounts = json.load(file)

    if not isinstance(accounts, list):
        raise ValueError(
            "Файл accounts.json должен содержать JSON-массив"
        )

    if not accounts:
        raise ValueError(
            "Не настроено ни одной учётной записи"
        )

    for index, account in enumerate(accounts, start=1):

        if not isinstance(account, dict):
            raise ValueError(
                f"Учётная запись №{index} должна быть объектом"
            )

        for field in ("url", "login", "password"):
            if not account.get(field):
                raise ValueError(
                    f"Учётная запись №{index}: отсутствует поле '{field}'"
                )

        account["url"] = account["url"].strip().rstrip("/")

        parsed_url = urlparse(account["url"])

        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError(
                f"Учётная запись №{index}: некорректный URL: "
                f"{account['url']}"
            )

    return accounts


# ============================================================
# АВТОРИЗАЦИЯ
# ============================================================

async def login(page, account: dict) -> bool:
    """Авторизация в ownCloud."""

    base_url = account["url"]
    username = account["login"]
    password = account["password"]

    logger.info("[%s] Открытие %s", username, base_url)

    try:
        await page.goto(
            base_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        await random_delay(LOGIN_DELAY)

        # Поля авторизации ownCloud
        username_input = page.locator(
            "input#user, input[name='user'], "
            "input[autocomplete='username']"
        ).first

        password_input = page.locator(
            "input#password, input[name='password'], "
            "input[autocomplete='current-password']"
        ).first

        await username_input.wait_for(
            state="visible",
            timeout=PAGE_TIMEOUT,
        )

        await username_input.fill(username)
        await password_input.fill(password)

        submit_button = page.locator(
            "button[type='submit'], "
            "input[type='submit'], "
            "#submit"
        ).first

        await submit_button.click()

        # Ожидание появления списка файлов
        await page.locator(
            "#app-content-files #fileList"
        ).wait_for(
            state="visible",
            timeout=PAGE_TIMEOUT,
        )

        logger.info("[%s] Авторизация успешна", username)

        return True

    except PlaywrightTimeoutError:
        logger.error(
            "[%s] Превышено время ожидания авторизации. "
            "Проверьте учётные данные и селекторы страницы входа.",
            username,
        )

        return False

    except Exception:
        logger.exception("[%s] Ошибка авторизации", username)
        return False


# ============================================================
# МЕТОДЫ СКАЧИВАНИЯ
# ============================================================

async def download_via_request(
    context,
    download_url: str,
    output_path: Path,
    base_url: str,
) -> bool:
    """Скачивание файла через HTTP-запрос с авторизацией."""

    try:
        response = await context.request.get(
            download_url,
            headers={
                "Referer": base_url,
            },
            timeout=DOWNLOAD_TIMEOUT,
        )

        if not response.ok:
            logger.warning(
                "Ошибка HTTP-скачивания: статус %s",
                response.status,
            )

            return False

        content = await response.body()

        if not content:
            logger.warning("Скачанный файл пуст")

            return False

        output_path.write_bytes(content)

        return True

    except Exception as error:
        logger.warning(
            "Ошибка HTTP-скачивания: %s",
            error,
        )

        return False


async def download_via_browser(
    page,
    download_url: str,
    output_path: Path,
) -> bool:
    """Резервное скачивание файла через браузер."""

    try:
        async with page.expect_download(
            timeout=DOWNLOAD_TIMEOUT
        ) as download_info:

            await page.evaluate(
                """
                (url) => {
                    const link = document.createElement("a");
                    link.href = url;
                    link.style.display = "none";

                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                }
                """,
                download_url,
            )

        download = await download_info.value

        await download.save_as(str(output_path))

        return (
            output_path.exists()
            and output_path.stat().st_size > 0
        )

    except Exception as error:
        logger.error(
            "Ошибка скачивания через браузер: %s",
            error,
        )

        return False


# ============================================================
# ОБРАБОТКА УЧЁТНОЙ ЗАПИСИ
# ============================================================

async def process_account(browser, account: dict) -> dict:
    """Обработка всех подходящих файлов одной учётной записи."""

    username = account["login"]
    base_url = account["url"]

    output_dir = DOWNLOAD_DIR / username
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
    }

    logger.info("=" * 60)
    logger.info("Обработка учётной записи: %s", username)
    logger.info("URL: %s", base_url)
    logger.info("=" * 60)

    context = await browser.new_context(
        accept_downloads=True,
    )

    page = await context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT)

    try:
        if not await login(page, account):
            stats["failed"] += 1
            return stats

        # Поиск файлов в корневой папке
        file_list = page.locator(
            "#app-content-files #fileList"
        )

        rows = file_list.locator(
            "tr[data-type='file']"
        )

        row_count = await rows.count()

        logger.info(
            "[%s] Файлов найдено в корневой папке: %d",
            username,
            row_count,
        )

        for index in range(row_count):
            row = rows.nth(index)

            try:
                # Получение настоящего имени файла из атрибута строки
                filename = await row.get_attribute("data-file")

                if not filename:
                    logger.warning(
                        "[%s] Строка №%d не содержит имени файла",
                        username,
                        index + 1,
                    )

                    stats["skipped"] += 1
                    continue

                extension = Path(filename).suffix.lower()

                if extension not in ALLOWED_EXTENSIONS:
                    logger.debug(
                        "[%s] Пропуск файла неподдерживаемого формата: %s",
                        username,
                        filename,
                    )

                    stats["skipped"] += 1
                    continue

                link = row.locator("a.name").first
                href = await link.get_attribute("href")

                if not href:
                    logger.warning(
                        "[%s] Не найдена ссылка для скачивания: %s",
                        username,
                        filename,
                    )

                    stats["failed"] += 1
                    continue

                download_url = urljoin(
                    base_url + "/",
                    href,
                )

                output_path = output_dir / filename

                logger.info(
                    "[%s] Скачивание: %s",
                    username,
                    filename,
                )

                # Первая попытка: HTTP-запрос
                success = await download_via_request(
                    context,
                    download_url,
                    output_path,
                    base_url,
                )

                # Вторая попытка: скачивание через браузер
                if not success:
                    logger.info(
                        "[%s] Повторная попытка скачивания через браузер: %s",
                        username,
                        filename,
                    )

                    success = await download_via_browser(
                        page,
                        download_url,
                        output_path,
                    )

                if success:
                    file_size = output_path.stat().st_size

                    logger.info(
                        "[%s] Скачано: %s (%.2f КБ)",
                        username,
                        filename,
                        file_size / 1024,
                    )

                    stats["downloaded"] += 1

                else:
                    logger.error(
                        "[%s] Не удалось скачать: %s",
                        username,
                        filename,
                    )

                    stats["failed"] += 1

            except Exception:
                logger.exception(
                    "[%s] Ошибка обработки строки №%d",
                    username,
                    index + 1,
                )

                stats["failed"] += 1

            finally:
                # Задержка после каждой строки, включая пропущенные и ошибочные
                await random_delay(DOWNLOAD_DELAY)

    except Exception:
        logger.exception(
            "[%s] Непредвиденная ошибка обработки учётной записи",
            username,
        )

        stats["failed"] += 1

    finally:
        await context.close()

    logger.info(
        "[%s] Обработка завершена: скачано=%d, пропущено=%d, ошибок=%d",
        username,
        stats["downloaded"],
        stats["skipped"],
        stats["failed"],
    )

    return stats


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

async def main():
    accounts = load_accounts()

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    total_stats = {
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
    }

    logger.info(
        "Загружено учётных записей: %d",
        len(accounts),
    )

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=HEADLESS,
        )

        try:
            for index, account in enumerate(accounts):

                stats = await process_account(
                    browser,
                    account,
                )

                for key in total_stats:
                    total_stats[key] += stats[key]

                # Задержка между учётными записями,
                # кроме последней
                if index < len(accounts) - 1:
                    await random_delay(ACCOUNT_DELAY)

        finally:
            await browser.close()

    # Итоговая статистика
    logger.info("=" * 60)
    logger.info("ОБРАБОТКА ВСЕХ УЧЁТНЫХ ЗАПИСЕЙ ЗАВЕРШЕНА")
    logger.info("Скачано:    %d", total_stats["downloaded"])
    logger.info("Пропущено:  %d", total_stats["skipped"])
    logger.info("Ошибок:     %d", total_stats["failed"])
    logger.info("=" * 60)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.warning("Выполнение прервано пользователем")

    except Exception:
        logger.exception("Критическая ошибка")
