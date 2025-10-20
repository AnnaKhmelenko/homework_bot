import os
import sys
import time
import logging
from http import HTTPStatus

import requests
import telebot
from dotenv import load_dotenv


from exceptions import APIResponseError

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


def check_tokens():
    """Проверяет доступность переменных окружения."""
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
        logging.critical(
            f'Отсутствуют обязательные переменные окружения: {
                ", ".join(missing_tokens)}'
        )
        raise ValueError(
            f'Отсутствуют обязательные переменные окружения: {
                ", ".join(missing_tokens)}'
        )


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    logging.debug(f'Начало отправки сообщения: "{message}"')
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug(f'Бот отправил сообщение "{message}"')
    except (
            telebot.apihelper.ApiException, requests.RequestException
    ) as error:
        logging.exception(f'Ошибка при отправке сообщения в Telegram: {error}')
        raise


def get_api_answer(timestamp):
    """Делает запрос к эндпоинту API-сервиса."""
    logging.debug(f'Отправка запроса к {ENDPOINT} с timestamp: {timestamp}')
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except requests.exceptions.RequestException as error:
        raise ConnectionError(f'Ошибка при запросе к API: {error}')

    if response.status_code != HTTPStatus.OK:
        raise APIResponseError(
            f'Эндпоинт {ENDPOINT} недоступен. Код ответа API: {
                response.status_code}'
        )

    try:
        api_response = response.json()
        logging.debug(f'Успешно получен ответ от API: {api_response}')
        return api_response
    except ValueError as error:
        raise ValueError(f'Ошибка преобразования в JSON: {error}')


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
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

    logging.debug('Проверка ответа API завершена успешно')
    return homeworks


def parse_status(homework):
    """Извлекает статус домашней работы."""
    logging.debug('Начало извлечения статуса домашней работы')

    required_keys = ['homework_name', 'status']
    missing_keys = [key for key in required_keys if key not in homework]

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

    logging.debug(f'Статус успешно извлечен: {result_message}')
    return result_message


def main():
    """Основная логика работы бота."""
    try:
        check_tokens()
    except ValueError as error:
        sys.exit(f'Ошибка инициализации: {error}')

    last_sent_message = None
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time())

    logging.info('Бот запущен')

    while True:
        try:
            timestamp, last_sent_message = _process_homeworks(
                bot, timestamp, last_sent_message)
        except Exception as error:
            last_sent_message = _handle_error(bot, error, last_sent_message)
        finally:
            time.sleep(RETRY_PERIOD)


def _process_homeworks(bot, timestamp, last_sent_message):
    """Обрабатывает проверку домашних работ."""
    response = get_api_answer(timestamp)
    homeworks = check_response(response)

    if not homeworks:
        logging.debug('Нет новых статусов')
        return response.get('current_date', timestamp), last_sent_message

    homework = homeworks[0]
    message = parse_status(homework)

    if message != last_sent_message:
        send_message(bot, message)
        last_sent_message = message

    return response.get('current_date', timestamp), last_sent_message


def _handle_error(bot, error, last_sent_message):
    """Обрабатывает ошибки и отправляет сообщения в Telegram."""
    error_message = f'Сбой в работе программы: {error}'
    logging.exception(error_message)

    if error_message != last_sent_message:
        try:
            send_message(bot, error_message)
            return error_message
        except (telebot.apihelper.ApiException, requests.RequestException):
            logging.error(
                'Не удалось отправить сообщение об ошибке в Telegram')

    return last_sent_message


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    main()
