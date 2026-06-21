"""
Модуль системы уведомлений приложения CL Bot.

Этот модуль обеспечивает функциональность отправки различных типов уведомлений
пользователям с настраиваемыми интервалами. Система отслеживает важные события, 
такие как дни рождения сотрудников, необходимость обновления медицинских книжек,
истечение срока действия сертификатов и техническое обслуживание кофемашин.

Уведомления отправляются в строго определенное время (по умолчанию в 9:00),
что предотвращает получение пользователями множества разрозненных сообщений
в течение дня.
"""

import asyncio
import time
from datetime import datetime

from aiogram import Bot

from config import SETTINGS

from app.core.funcs.app import get_app
from app.notifier.check_birthday import check_birthday
from app.notifier.check_lmk import check_lmk, check_exp_lmk
from app.notifier.check_anniversary import check_anniversary
from app.notifier.check_certs import check_certs, check_exp_certs
from app.notifier.check_espresso_machines import check_espresso_machines, format_notification_message
from app.core.funcs.user import get_all_to_notify

# Хранилище для сообщений, которые нужно отправить в указанное время
pending_notifications = {
    'birthday': [],
    'lmk': [],
    'certificates': [],
    'anniversary': [],
    'espresso': []
}

# Отслеживаем день последней отправки уведомлений
last_notification_day = None


async def send_message(chat_id, text):
    """
    Отправляет сообщение пользователю через Telegram API.
    
    Args:
        chat_id (int): Уникальный идентификатор чата, куда отправляется сообщение
        text (str): Текст сообщения для отправки
    """
    bot = Bot(SETTINGS.BOT_TOKEN, parse_mode='html')
    await bot.send_message(
        chat_id=chat_id,
        text=text
    )
    await bot.close()


def is_notification_time():
    """
    Проверяет, является ли текущее время временем для отправки уведомлений.
    
    Сравнивает текущее время с установленным временем отправки уведомлений,
    допуская погрешность в ±2 минуты для надежности.
    
    Returns:
        bool: True если текущее время находится в пределах окна отправки,
              False в противном случае
    """
    app = get_app()
    notify_time = app.time_to_notify
    
    # Разбираем время для сравнения (формат '9:00')
    notify_hour, notify_minute = map(int, notify_time.split(':'))
    
    # Получаем текущее время
    now = datetime.now()
    current_hour, current_minute = now.hour, now.minute
    print(current_hour, current_minute, notify_hour, notify_minute)
    
    # Преобразуем время в минуты с начала дня для обоих значений
    current_time_minutes = current_hour * 60 + current_minute
    notify_time_minutes = notify_hour * 60 + notify_minute
    
    # Проверяем, находится ли текущее время в окне допустимых значений (±2 минуты)
    return abs(current_time_minutes - notify_time_minutes) < 2


def should_send_missed_notifications():
    """
    Проверяет, нужно ли отправить пропущенные уведомления.
    
    Вызывается при запуске бота для проверки, не было ли пропущено
    время отправки уведомлений в текущий день (например, если бот 
    был выключен во время запланированной отправки).
    
    Returns:
        bool: True если уведомления за сегодня еще не отправлялись и 
              текущее время уже прошло запланированное время отправки,
              False в противном случае
    """
    global last_notification_day
    
    # Получаем текущие дату и время
    now = datetime.now()
    current_day = now.day
    
    # Разбираем время отправки
    app = get_app()
    notify_time = app.time_to_notify
    notify_hour, notify_minute = map(int, notify_time.split(':'))
    
    # Если время отправки уже прошло сегодня и не отправляли сегодня уведомления
    current_time_minutes = now.hour * 60 + now.minute
    notify_time_minutes = notify_hour * 60 + notify_minute
    
    # Проверяем: 
    # 1. Если день последней отправки не совпадает с текущим днем (или None)
    # 2. Если текущее время больше времени отправки
    return (last_notification_day != current_day and 
            current_time_minutes > notify_time_minutes)


async def __dr_notifier():
    """
    Асинхронная функция для отслеживания приближающихся дней рождения сотрудников.
    
    Регулярно проверяет список сотрудников и формирует уведомления о предстоящих
    днях рождения, которые затем будут отправлены в запланированное время.
    """
    while True:
        dr = check_birthday()
        if dr:
            message = "🎂 В ближайшие дни Дни Рождения у следующих сотрудников:\n\n"
            for employee in dr:
                days_to_birth = employee.get_days_to_birth()
                message += f"{employee.name}"

                if days_to_birth == 0:
                    message += f" - сегодня День Рождения\n"
                elif days_to_birth == 1:
                    message += f" - завтра День Рождения\n"
                else:   
                    message += f" - через {days_to_birth} дней\n"
            
            # Сохраняем сообщение для отправки в указанное время
            pending_notifications['birthday'] = [(message, get_all_to_notify())]

        await asyncio.sleep(get_app().dr_notify_time_interval)


async def __lmk_notifier():
    """
    Асинхронная функция для мониторинга статуса медицинских книжек сотрудников.
    
    Проверяет как уже просроченные, так и скоро истекающие медицинские книжки,
    формируя соответствующие уведомления для пользователей.
    """
    while True:
        messages = []
        
        lmk = check_lmk()
        if lmk:
            message = "⚠️ Просрочены мед. книжки у следующих сотрудников:\n\n"
            for employee in lmk:
                message += f"{employee.name} - просрочена мед. книжка\n"
            messages.append(message)

        lmk = check_exp_lmk()
        if lmk:
            message = "⚠️ В ближайшие дни истекает срок действия ЛМК у следующих сотрудников:\n\n"
            for employee in lmk:
                message += f"{employee.name} - через {employee.get_days_lmk()} дней\n"
            messages.append(message)
        
        if messages:
            # Сохраняем сообщения для отправки в указанное время
            pending_notifications['lmk'] = [(msg, get_all_to_notify()) for msg in messages]

        await asyncio.sleep(get_app().lmk_notify_time_interval)


async def __certs_notifier():
    """
    Асинхронная функция для отслеживания статуса профессиональных сертификатов.
    
    Проверяет как уже просроченные, так и скоро истекающие сертификаты 
    сотрудников, формируя соответствующие уведомления.
    """
    while True:
        messages = []
        
        employees = check_certs()
        if employees:
            message = "⚠️ Просрочены сертификаты у следующих сотрудников:\n\n"
            for employee, cert_type in employees:
                message += f"{employee.name} - просрочен сертификат {cert_type} от {employee.get_cert_by_type(cert_type)}\n"
            messages.append(message)

        employees = check_exp_certs()
        if employees:
            message = "⚠️ В ближайшие дни истекает срок действия сертификатов у следующих сотрудников:\n\n"
            for employee, cert_type in employees:
                message += f"{employee.name} - {cert_type} – через {employee.get_days_to_cert(cert_type)} дней\n"
            messages.append(message)
        
        if messages:
            # Сохраняем сообщения для отправки в указанное время
            pending_notifications['certificates'] = [(msg, get_all_to_notify()) for msg in messages]

        await asyncio.sleep(get_app().certs_time_interval)


async def __anniversary_notifier():
    """
    Асинхронная функция для отслеживания приближающихся юбилеев работы сотрудников.
    
    Проверяет список сотрудников на предмет юбилеев и формирует 
    уведомления о таких событиях.
    """
    while True:
        anniversary = check_anniversary()
        if anniversary:
            message = "🎉 В ближайшие дни юбилеи у следующих сотрудников:\n\n"
            for employee in anniversary:
                message += f"{employee.name} - через {employee.get_days_to_anniversary()} дней\n"
            
            # Сохраняем сообщение для отправки в указанное время
            pending_notifications['anniversary'] = [(message, get_all_to_notify())]

        await asyncio.sleep(get_app().anniversary_time_interval)


async def __espresso_notifier():
    """
    Асинхронная функция для мониторинга состояния кофемашин.
    
    Проверяет необходимость технического обслуживания и 
    замены уплотнителей в кофемашинах, формируя соответствующие уведомления.
    """
    while True:
        machines = check_espresso_machines()
        if machines:
            message = format_notification_message(machines)
            
            # Сохраняем сообщение для отправки в указанное время
            pending_notifications['espresso'] = [(message, get_all_to_notify())]

        await asyncio.sleep(86400)


async def __notification_sender():
    """
    Асинхронная функция для отправки накопленных уведомлений в указанное время.
    
    Отвечает за проверку текущего времени и отправку всех накопленных
    уведомлений различных типов в установленное время дня.
    При первом запуске также проверяет, не были ли пропущены уведомления
    за текущий день.
    """
    global last_notification_day
    
    # При первом запуске проверяем, не пропустили ли мы время отправки сегодня
    if should_send_missed_notifications():
        print("Обнаружены пропущенные уведомления, отправляем сразу...")
        # Отправляем все накопленные уведомления
        for category, notifications in pending_notifications.items():
            for message, chat_ids in notifications:
                for chat_id in chat_ids:
                    await send_message(chat_id, message)
            
            # Очищаем отправленные уведомления
            pending_notifications[category] = []
        
        # Обновляем день последней отправки уведомлений
        last_notification_day = datetime.now().day
    
    while True:
        # Проверяем, пришло ли время отправки уведомлений
        print(is_notification_time())
        if is_notification_time():
            # Отправляем все накопленные уведомления
            for category, notifications in pending_notifications.items():
                for message, chat_ids in notifications:
                    for chat_id in chat_ids:
                        await send_message(chat_id, message)
                
                # Очищаем отправленные уведомления
                pending_notifications[category] = []
            
            # Обновляем день последней отправки уведомлений
            last_notification_day = datetime.now().day
        
        # Проверяем время каждую минуту
        await asyncio.sleep(60)


async def _start_notifier():
    """
    Запускает все асинхронные задачи системы уведомлений.
    
    Использует asyncio.gather для параллельного запуска всех функций-notifier,
    что позволяет эффективно обрабатывать различные типы уведомлений одновременно.
    """
    await asyncio.gather(
        __dr_notifier(),
        __lmk_notifier(),
        __certs_notifier(),
        __anniversary_notifier(),
        __espresso_notifier(),
        __notification_sender()  # Функция отправки уведомлений
    )


def start_notifier():
    """
    Основная функция для запуска системы уведомлений.
    
    Вызывается из главного модуля приложения для активации
    всей системы мониторинга и отправки уведомлений.
    """
    asyncio.run(_start_notifier())
