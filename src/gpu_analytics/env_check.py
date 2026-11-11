"""Проверка окружения и «паспорт эксперимента».

Зачем: результаты замеров зависят от железа и версий библиотек. Поэтому перед
каждым прогоном бенчмарка мы записываем, на чём он выполнялся: CPU, RAM, GPU,
драйвер, версии Python и библиотек. Этот же модуль удобно запустить первым
делом на новой машине: он сразу покажет, видна ли GPU и установлены ли библиотеки.

Запуск:  python -m gpu_analytics.env_check
"""

from __future__ import annotations  # Разрешает писать подсказки типов вида `dict[str, str]` в любой версии Python 3.

import json  # Модуль для вывода словаря в читаемом формате JSON.
import os  # Модуль для работы с операционной системой (число ядер CPU).
import platform  # Модуль с информацией об ОС и процессоре.
import shutil  # Нужен функцией shutil.which: проверить, есть ли программа nvidia-smi.
import subprocess  # Запуск внешних программ (nvidia-smi) из Python.
import sys  # Информация о самом интерпретаторе Python (версия).
from importlib import metadata  # Узнать версию установленного пакета, не импортируя его.

import psutil  # Сторонняя библиотека: объём оперативной памяти и физические ядра CPU.

# Библиотеки, версии которых важны для воспроизводимости результатов.
LIBRARIES = ["duckdb", "polars", "pyarrow", "pyspark"]
# Пакеты RAPIDS (cudf, cudf-polars, pylibcudf, …) ищем по началу имени: у них в имени есть вариант CUDA
# (cudf-polars-cu13, cudf-cu12), и заранее неизвестно, какой стоит на машине (на сервере — cu13, в Colab — как предустановлено).
RAPIDS_PREFIXES = ("cudf", "pylibcudf", "rmm", "rapidsmpf")


def library_versions() -> dict[str, str]:
    """Вернуть словарь «имя библиотеки → версия» (или пометку, что не установлена)."""
    versions = {}  # Сюда будем складывать результат.
    for name in LIBRARIES:  # Перебираем основные библиотеки.
        try:  # Пытаемся узнать версию...
            versions[name] = metadata.version(name)  # ...по метаданным установленного пакета.
        except metadata.PackageNotFoundError:  # Если пакет не установлен — будет эта ошибка.
            versions[name] = "не установлена"  # Записываем понятную пометку вместо версии.
    for dist in metadata.distributions():  # Перебираем ВСЕ установленные пакеты (dist — «дистрибутив», установленный пакет)...
        name = (dist.metadata["Name"] or "").lower()  # ...имя пакета в нижнем регистре (у битых пакетов имени может не быть).
        if name.startswith(RAPIDS_PREFIXES):  # ...и берём только пакеты RAPIDS (startswith принимает кортеж вариантов).
            versions[name] = dist.version  # Например: "cudf-polars-cu13": "26.6.1".
    return dict(sorted(versions.items()))  # Сортируем по имени, чтобы паспорта разных машин было удобно сравнивать.


def gpu_info() -> list[dict[str, str]]:
    """Вернуть список GPU (имя, память, драйвер) через утилиту nvidia-smi.

    Если nvidia-smi нет (нет драйвера NVIDIA или нет GPU) — вернуть пустой список.
    """
    if shutil.which("nvidia-smi") is None:  # Ищем программу nvidia-smi в системе.
        return []  # Не нашли — значит, NVIDIA GPU недоступна.
    query = "name,memory.total,driver_version,pcie.link.gen.max"  # Какие поля спросить у nvidia-smi.
    result = subprocess.run(  # Запускаем nvidia-smi как внешнюю программу.
        ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader"],  # Аргументы: нужные поля, вывод в CSV без заголовка.
        capture_output=True,  # Перехватить вывод программы, а не печатать его в консоль.
        text=True,  # Получить вывод как строку, а не как байты.
        check=False,  # Не бросать исключение при ошибке — обработаем сами.
    )
    if result.returncode != 0:  # Ненулевой код возврата — программа завершилась с ошибкой.
        return []  # В этом случае считаем, что GPU недоступна.
    gpus = []  # Сюда соберём описание каждой GPU.
    for line in result.stdout.strip().splitlines():  # Каждая строка вывода — одна GPU.
        name, memory, driver, pcie_gen = [part.strip() for part in line.split(",")]  # Делим строку по запятым и убираем пробелы.
        gpus.append({"name": name, "memory": memory, "driver": driver, "pcie_gen_max": pcie_gen})  # Сохраняем как словарь.
    return gpus  # Возвращаем список GPU.


def environment_passport() -> dict:
    """Собрать полный «паспорт» окружения в один словарь."""
    memory = psutil.virtual_memory()  # Информация об оперативной памяти.
    return {  # Возвращаем словарь со всеми полями паспорта.
        "python": sys.version.split()[0],  # Версия Python, например "3.12.7".
        "os": platform.platform(),  # Операционная система и её версия.
        "cpu": platform.processor() or platform.machine(),  # Модель процессора (на Linux иногда пусто — тогда архитектура).
        "cpu_logical_cores": os.cpu_count(),  # Число логических ядер (с учётом hyper-threading).
        "cpu_physical_cores": psutil.cpu_count(logical=False),  # Число физических ядер.
        "ram_gb": round(memory.total / 1024**3, 1),  # Объём RAM в гигабайтах, округлённый до 0.1.
        "gpus": gpu_info(),  # Список GPU (пустой, если GPU нет).
        "libraries": library_versions(),  # Версии ключевых библиотек.
    }


def main() -> None:
    """Точка входа для командной строки: напечатать паспорт окружения."""
    sys.stdout.reconfigure(encoding="utf-8")  # Консоль Windows по умолчанию в cp1251 — переключаем вывод на UTF-8, чтобы кириллица печаталась без ошибок.
    passport = environment_passport()  # Собираем паспорт.
    print(json.dumps(passport, ensure_ascii=False, indent=2))  # Печатаем красиво: с отступами и кириллицей без экранирования.
    if not passport["gpus"]:  # Если список GPU пуст...
        print("\nВнимание: NVIDIA GPU не найдена. Доступны только CPU-движки.")  # ...предупреждаем пользователя.


if __name__ == "__main__":  # Этот блок выполняется только при запуске файла напрямую (а не при импорте).
    main()  # Вызываем главную функцию.
