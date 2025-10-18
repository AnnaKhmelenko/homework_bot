import os
import sys
import time
import logging
from http import HTTPStatus

import requests
import telebot
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


# Кастомный класс исключения для ошибок API
class APIResponseError(Exception):
    """Исключение для ошибок ответа API."""


def check_tokens():
    """Проверяет доступность переменных окружения."""
    # Собираем информацию о всех отсутствующих переменных
    missing_tokens = []
    tokens = (
        ('PRACTICUM_TOKEN', PRACTICUM_TOKEN),
        ('TELEGRAM_TOKEN', TELEGRAM_TOKEN),
        ('TELEGRAM_CHAT_ID', TELEGRAM_CHAT_ID),
    )
    for token_name, token_value in tokens:
        if not token_value:
            missing_tokens.append(token_name)

    if missing_tokens:
        # Логируем все отсутствующие переменные одним сообщением
        logging.critical(
            f'Отсутствуют обязательные переменные окружения: {
                ", ".join(missing_tokens)}'
        )
        return False
    return True


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    # логирование начала отправки
    logging.debug(f'Начало отправки сообщения: "{message}"')
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug(f'Бот отправил сообщение "{message}"')
    # Указаны конкретные исключения вместо общего Exception
    except (
            telebot.apihelper.ApiException, requests.RequestException
    ) as error:
        # для добавления трейсбека
        logging.exception(f'Ошибка при отправке сообщения в Telegram: {error}')
        raise


def get_api_answer(timestamp):
    """Делает запрос к эндпоинту API-сервиса."""
    # логирование параметров запроса
    logging.debug(f'Отправка запроса к {ENDPOINT} с timestamp: {timestamp}')
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except requests.exceptions.RequestException as error:
        raise ConnectionError(f'Ошибка при запросе к API: {error}')

    # Кастомный класс исключения вместо ConnectionError
    if response.status_code != HTTPStatus.OK:
        raise APIResponseError(
            f'Эндпоинт {ENDPOINT} недоступен. Код ответа API: {
                response.status_code}'
        )

    try:
        api_response = response.json()
        # Логирование успешного получения ответа
        logging.debug(f'Успешно получен ответ от API: {api_response}')
        return api_response
    except ValueError as error:
        raise ValueError(f'Ошибка преобразования в JSON: {error}')


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    # Логирование начала проверки
    logging.debug('Начало проверки ответа API')

    if not isinstance(response, dict):
        raise TypeError(
            f'Ответ API не является словарем. Получен тип: {type(response)}')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ homeworks')

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            f'homeworks не является списком. Получен тип: {type(homeworks)}')

    # Логирование успешного завершения проверки
    logging.debug('Проверка ответа API завершена успешно')
    return homeworks


def parse_status(homework):
    """Извлекает статус домашней работы."""
    # логирование начала выполнения функции
    logging.debug('Начало извлечения статуса домашней работы')

    # сбор информации о всех отсутствующих ключах
    missing_keys = []
    if 'homework_name' not in homework:
        missing_keys.append('homework_name')
    if 'status' not in homework:
        missing_keys.append('status')

    if missing_keys:
        raise KeyError(
            f'В ответе API отсутствуют ключи: {", ".join(missing_keys)}')

    homework_name = homework['homework_name']
    status = homework['status']

    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус домашней работы: {status}')

    verdict = HOMEWORK_VERDICTS[status]
    result_message = f'Изменился статус проверки работы "{
        homework_name}". {verdict}'

    # Логирование завершения функции
    logging.debug(f'Статус успешно извлечен: {result_message}')
    return result_message


def main():
    """Основная логика работы бота."""
    # проверка токенов с принудительной остановкой
    if not check_tokens():
        sys.exit('Отсутствуют обязательные переменные окружения')

    last_sent_message = None

    # Создаем объект бота
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time())

    logging.info('Бот запущен')

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)

            if not homeworks:
                logging.debug('Нет новых статусов')
                # Обновляем timestamp
                timestamp = response.get('current_date', timestamp)
                continue

            homework = homeworks[0]
            message = parse_status(homework)
            # Проверка на дублирование сообщения
            if message != last_sent_message:
                send_message(bot, message)
                last_sent_message = message

            timestamp = response.get('current_date', timestamp)

        except Exception as error:
            error_message = f'Сбой в работе программы: {error}'
            logging.exception(error_message)

            if error_message != last_sent_message:
                try:
                    send_message(bot, error_message)
                    last_sent_message = error_message
                except (
                        telebot.apihelper.ApiException,
                        requests.RequestException):
                    logging.error(
                        'Не удалось отправить сообщение об ошибке в Telegram')

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    main()
