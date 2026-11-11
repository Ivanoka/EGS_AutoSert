import gc
import re
from pathlib import Path

import cv2
import numpy as np
from paddleocr import PaddleOCR


class OcrService:
    def __init__(self):
        self.ocr_ru = None
        self.ocr_en = None

        self._load_russian_model()

    @staticmethod
    def _settings():
        return {
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "enable_mkldnn": False,
            "cpu_threads": 4,
            "text_det_limit_type": "max",
            "text_det_limit_side_len": 960
        }

    def _load_russian_model(self):
        print("Загрузка русской OCR-модели...")

        self.ocr_ru = PaddleOCR(
            lang="ru",
            text_recognition_model_name="eslav_PP-OCRv5_mobile_rec",
            **self._settings()
        )

    def _load_english_model(self):
        print("Загрузка английской OCR-модели...")

        self.ocr_en = PaddleOCR(
            lang="en",
            text_recognition_model_name="PP-OCRv5_server_rec",
            **self._settings()
        )

    def release_russian_model(self):
        print("Освобождение памяти русской OCR-модели...")

        self.ocr_ru = None
        gc.collect()

        self._load_english_model()

    def recognize_document(self, image_path: Path) -> dict:
        if self.ocr_ru is None:
            raise RuntimeError("Русская OCR-модель не загружена")

        image = cv2.imread(str(image_path))

        if image is None:
            raise ValueError(
                f"Не удалось открыть изображение: {image_path}"
            )

        results = self.ocr_ru.predict(str(image_path))

        recognized_lines = []
        crops = {
            "login": None,
            "password": None
        }

        for result in results:
            data = result.json["res"]

            texts = data.get("rec_texts", [])
            polygons = data.get("rec_polys", [])

            for text, polygon in zip(texts, polygons):
                recognized_lines.append(text)

                normalized = text.casefold()

                if crops["login"] is None and "логин" in normalized:
                    crops["login"] = self._crop_value(
                        image,
                        text,
                        polygon,
                        "логин"
                    )

                elif crops["password"] is None and "пароль" in normalized:
                    crops["password"] = self._crop_value(
                        image,
                        text,
                        polygon,
                        "пароль"
                    )

                if crops["login"] is not None:
                    debug_dir = Path("debug")
                    debug_dir.mkdir(exist_ok=True)

                    cv2.imwrite(
                        str(debug_dir / f"{image_path.stem}_login.png"),
                        crops["login"]
                    )

                if crops["password"] is not None:
                    debug_dir = Path("debug")
                    debug_dir.mkdir(exist_ok=True)

                    cv2.imwrite(
                        str(debug_dir / f"{image_path.stem}_password.png"),
                        crops["password"]
                    )

        return {
            "text": "\n".join(recognized_lines),
            "crops": crops
        }

    @staticmethod
    def _crop_value(
        image: np.ndarray,
        text: str,
        polygon,
        label: str
    ) -> np.ndarray | None:

        if label not in text.casefold():
            return None

        points = np.asarray(polygon, dtype=np.float32)

        if points.shape != (4, 2):
            return None

        # Сортируем вершины по углу относительно центра.
        center = points.mean(axis=0)

        angles = np.arctan2(
            points[:, 1] - center[1],
            points[:, 0] - center[0]
        )

        points = points[np.argsort(angles)]

        # Определяем направление верхней стороны:
        # она должна идти слева направо.
        edges = np.roll(points, -1, axis=0) - points
        lengths = np.linalg.norm(edges, axis=1)

        max_length = lengths.max()

        candidates = [
            i for i in range(4)
            if lengths[i] >= max_length * 0.8
            and edges[i][0] > 0
        ]

        if not candidates:
            return None

        # Выбираем длинную сторону, направленную слева направо.
        index = max(candidates, key=lambda i: lengths[i])

        src = np.array(
            [
                points[index],
                points[(index + 1) % 4],
                points[(index + 2) % 4],
                points[(index + 3) % 4]
            ],
            dtype=np.float32
        )

        width = int(round(max(
            lengths[0],
            lengths[2]
        ))) if index == 0 else int(round(max(
            lengths[index],
            lengths[(index + 2) % 4]
        )))

        height = int(round(max(
            lengths[(index + 1) % 4],
            lengths[(index + 3) % 4]
        )))

        if width <= 0 or height <= 0:
            return None

        dst = np.array(
            [
                [0, 0],
                [width - 1, 0],
                [width - 1, height - 1],
                [0, height - 1]
            ],
            dtype=np.float32
        )

        matrix = cv2.getPerspectiveTransform(src, dst)

        crop = cv2.warpPerspective(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255)
        )

        if crop.size == 0:
            return None

        padding_y = max(4, int(height * 0.08))

        crop = cv2.copyMakeBorder(
            crop,
            padding_y,
            padding_y,
            10,
            10,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255)
        )

        crop = cv2.resize(
            crop,
            None,
            fx=4,
            fy=4,
            interpolation=cv2.INTER_LANCZOS4
        )

        return crop

    def recognize_credential_crop(
        self,
        crop: np.ndarray | None
    ) -> str | None:

        if crop is None:
            return None

        if self.ocr_en is None:
            raise RuntimeError("Английская OCR-модель не загружена")

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        ).apply(gray)

        _, otsu = cv2.threshold(
            clahe,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        adaptive = cv2.adaptiveThreshold(
            clahe,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11
        )

        variants = [
            crop,
            cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR),
            cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)
        ]

        candidates = []

        for index, variant in enumerate(variants):
            results = self.ocr_en.predict(variant)

            recognized = []

            for result in results:
                data = result.json["res"]
                recognized.extend(data.get("rec_texts", []))

            if not recognized:
                continue

            full_text = " ".join(recognized)

            parts = re.split(r"[:：]", full_text, maxsplit=1)

            if len(parts) > 1:
                value = "".join(
                    re.findall(r"[a-zA-Z0-9]+", parts[1])
                )
            else:
                tokens = re.findall(r"[a-zA-Z0-9]+", full_text)
                value = tokens[-1] if tokens else ""

            if value:
                candidates.append((index, value))

        if not candidates:
            return None

        # Результат оригинального изображения.
        original = next(
            (value for index, value in candidates if index == 0),
            None
        )

        if original is None:
            original = None

        from collections import Counter

        counts = Counter(
            value for _, value in candidates
        )

        best_value, occurrences = counts.most_common(1)[0]

        # Если минимум два варианта согласны,
        # используем результат большинства.
        if occurrences >= 2:
            return best_value

        # Если согласия нет, доверяем оригиналу.
        return original or best_value

    def close(self):
        """Освобождает ресурсы обеих OCR-моделей."""

        print("Освобождение ресурсов OCR...")

        self.ocr_ru = None
        self.ocr_en = None

        gc.collect()