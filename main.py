import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from tinydb import Query
import database as db
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=os.getenv("BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def is_admin(user_id: int) -> bool:
    admin_ids = list(map(int, os.getenv("ADMIN_IDS").split(',')))
    return user_id in admin_ids


# Обработчик команды /start
@dp.message(Command('start'))
async def send_hello(message: types.Message):
    await message.answer("Привет, что бы зарегистрироваться напиши команду /reg а если у тебя есть временный пропуск то напиши команду /scan_pass номер кода")

#Обработчик команды /reg
class RegistrationState(StatesGroup):
    full_name = State()
    vehicle = State()

@dp.message(Command('reg'))
async def start_registration(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        return await message.answer("👑 Вы авторизованы как администратор")
    
    user = db.User.table.get(Query().user_id == message.from_user.id)
    if user:
        return await message.answer("✅ Вы уже зарегистрированы")
    
    await state.set_state(RegistrationState.full_name)
    await message.answer("""🔐 Регистрация:
Введите ваше ФИО в формате: Иванов Иван Иванович""")

@dp.message(RegistrationState.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    if len(message.text.split()) < 3:
        return await message.answer("❌ Введите полное ФИО")
    
    await state.update_data(full_name=message.text)
    await state.set_state(RegistrationState.vehicle)
    await message.answer("🚗 Введите номер транспортного средства (или 'нет'):")

@dp.message(RegistrationState.vehicle)
async def process_vehicle(message: types.Message, state: FSMContext):
    vehicle = message.text if message.text.lower() != 'нет' else None
    data = await state.get_data()
    
    if db.User.create(message.from_user.id, data['full_name'], vehicle):
        await message.answer("✅ Регистрация завершена!")
    else:
        await message.answer("⚠️ Вы уже зарегистрированы")
    
    await state.clear()

# Команда для пользователей
@dp.message(Command('my_qrcode'))
async def show_my_qrcode(message: types.Message):
    user = db.User.table.get(Query().user_id == message.from_user.id)
    if not user:
        return await message.answer("❌ Сначала пройдите регистрацию через /start")
    
    if not user.get('qr_code_path'):
        return await message.answer("🔄 QR-код ещё не сгенерирован администратором")
    
    text = f"""
🔑 Ваш пропуск:
ФИО: {user['full_name']}
Номер ТС: {user['vehicle'] or 'Нет'}
ID: {user['qr_id']}
    """
    await message.answer_photo(
        types.FSInputFile(user['qr_code_path']),
        caption=text
    )

# Админская команда для генерации QR
@dp.message(Command('generate_user_qr'))
async def generate_user_qr(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    try:
        full_name = message.text.split(maxsplit=1)[1]
    except IndexError:
        return await message.answer("❌ Формат: /generate_user_qr <ФИО>")
    
    user = db.User.table.get(Query().full_name == full_name)
    if not user:
        return await message.answer("❌ Пользователь не найден")
    
    qr_path = db.User.generate_qr(user['user_id'])
    if qr_path:
        await message.answer_document(
            types.FSInputFile(qr_path),
            caption=f"✅ QR-код для {full_name} сгенерирован"
        )
    else:
        await message.answer("❌ Ошибка генерации")
        
@dp.message(Command('scan_pass'))
async def handle_scan(message: types.Message):
    try:
        scanned_qr_id = int(message.text.split(maxsplit=1)[1])
    except (IndexError, ValueError):
        return await message.answer("❌ Неверный формат. Используйте: /scan_pass <QR-код>")

    # Проверка гостевого пропуска (для НЕзарегистрированных)
    guest = db.Guest.table.get(Query().qr_id == scanned_qr_id)
    if guest:
        # Проверка активности и срока действия
        if not guest['is_active']:
            return await message.answer("🔒 Гостевой пропуск заблокирован")
        if datetime.fromisoformat(guest['expires_at']) < datetime.now():
            return await message.answer("⌛️ Срок действия гостевого пропуска истек")

        # Создание запроса для гостя
        db.PendingRequest.create(
            requester_id=message.from_user.id,
            pass_id=scanned_qr_id,
            user_type='guest'
        )

        # Уведомление администратора
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"access_allow_{scanned_qr_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"access_deny_{scanned_qr_id}")
            ]
        ])
        admin_text = (
            f"🔔 Запрос гостя:\n"
            f"QR-ID: {scanned_qr_id}\n"
            f"Действителен до: {guest['expires_at'][:10]}"
        )
        await bot.send_message(
            chat_id=os.getenv("ADMIN_CHAT_ID"),
            text=admin_text,
            reply_markup=keyboard
        )
        return await message.answer("⏳ Запрос отправлен администратору")

    # Проверка для зарегистрированных пользователей
    user = db.User.table.get(Query().user_id == message.from_user.id)
    if user:
        # Проверка принадлежности QR-кода
        if user['qr_id'] != scanned_qr_id:
            return await message.answer("🚫 Это не ваш QR-код!")
        if not user.get('is_active', True):
            return await message.answer("🔒 Ваш аккаунт заблокирован")

        # Создание запроса для пользователя
        db.PendingRequest.create(
            requester_id=message.from_user.id,
            pass_id=scanned_qr_id,
            user_type='user'
        )

        # Уведомление администратора
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"access_allow_{scanned_qr_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"access_deny_{scanned_qr_id}")
            ]
        ])
        admin_text = (
            f"🔔 Запрос от пользователя:\n"
            f"👤 {user['full_name']}\n"
            f"🆔 QR-ID: {scanned_qr_id}"
        )
        await bot.send_message(
            chat_id=os.getenv("ADMIN_CHAT_ID"),
            text=admin_text,
            reply_markup=keyboard
        )
        return await message.answer("⏳ Запрос отправлен администратору")

    # Если QR-код не гостевой и пользователь не зарегистрирован
    return await message.answer("❌ Недействительный QR-код. Обратитесь к администратору")

@dp.callback_query(F.data.startswith("access_"))
async def handle_access_decision(callback: types.CallbackQuery):
    action, pass_id = callback.data.split('_')[1:]
    pass_id = int(pass_id)
    
    request = db.PendingRequest.get_by_pass_id(pass_id)
    if not request:
        await callback.answer("⚠️ Запрос устарел")
        return
    
    user_type = request['user_type']
    requester_id = request['requester_id']
    status = "разрешён" if action == "allow" else "отклонён"
    status_upper = status.upper()

    # Сообщения для пользователя
    user_message_allow = "✅ Доступ подтвержден! Можете проходить."
    user_message_deny = "❌ Пропуск отклонен. Обратитесь к администратору."

    # Обработка гостей
    if user_type == 'guest':
        guest = db.Guest.table.get(Query().qr_id == pass_id)
        if guest:
            if action == "deny":
                db.Guest.update(guest.doc_id, {'is_active': False})  # Блокируем ТОЛЬКО гостей
            
            # Уведомление гостя
            if requester_id:
                try:
                    await bot.send_message(
                        chat_id=requester_id,
                        text=user_message_allow if action == "allow" else user_message_deny
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки гостю: {e}")

            # Логирование
            db.AccessLog.log_entry(
                user_type='guest',
                user_id=pass_id,
                status=status
            )

    # Обработка зарегистрированных пользователей
    elif user_type == 'user':
        user = db.User.table.get(Query().user_id == requester_id)
        if user:
            # Уведомление пользователя (без блокировки)
            try:
                await bot.send_message(
                    chat_id=requester_id,
                    text=user_message_allow if action == "allow" else user_message_deny
                )
            except Exception as e:
                logging.error(f"Ошибка отправки пользователю: {e}")
            
            # Логирование
            db.AccessLog.log_entry(
                user_type='user',
                user_id=requester_id,
                status=status
            )

    # Удаление запроса и ответ администратору
    db.PendingRequest.table.remove(doc_ids=[request.doc_id])
    await callback.message.edit_text(f"Результат: {status_upper} ✅")
    await callback.answer()

@dp.message(Command('create_temp_pass'))
async def create_temp_pass(message: types.Message):
    """Создание временного пропуска (для гостей)"""
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    try:
        days = int(message.text.split()[1])
    except:
        return await message.answer("❌ Формат: /create_temp_pass <дней>")
    
    doc_id, qr_id = db.Guest.create_temp_pass(days)
    await message.answer_document(
        types.FSInputFile(f'qrcodes/guest_{doc_id}.png'),
        caption=f"🔑 Временный пропуск создан!\nID: {qr_id}\nСрок: {days} дн."
    )

@dp.message(Command('block_pass'))
async def block_pass(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    try:
        doc_id = int(message.text.split()[1])
        user_type = message.text.split()[2].lower()
    except:
        return await message.answer("❌ Формат: /block_pass <ID> <employee/guest>")
    
    if user_type == 'employee':
        db.Employee.toggle_status(doc_id)
    elif user_type == 'guest':
        db.Guest.toggle_status(doc_id)
    else:
        return await message.answer("❌ Неверный тип пользователя")
    
    await message.answer(f"✅ Статус пропуска {doc_id} изменён")

@dp.message(Command('logs'))
async def show_logs(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    logs = db.AccessLog.get_all()
    if not logs:
        return await message.answer("📂 Журнал пуст")
    
    text = "📜 Журнал доступа:\n\n"
    for log in logs[-10:]:
        text += (
            f"Дата: {log['timestamp'][:10]}\n"
            f"Тип: {log['user_type']}\n"
            f"ID: {log['user_id']}\n"
            f"Статус: {log['status']}\n\n"
        )
    await message.answer(text)
    
# --- Новостной раздел ---
class NewsState(StatesGroup):
    title = State()
    content = State()
    media = State()

# Обработчики команд должны быть объявлены ПЕРВЫМИ
@dp.message(Command('add_news'))
async def add_news_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    await state.set_state(NewsState.title)
    await message.answer("📝 Введите заголовок новости:")

@dp.message(NewsState.title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(NewsState.content)
    await message.answer("📄 Введите текст новости:")

@dp.message(NewsState.content)
async def process_content(message: types.Message, state: FSMContext):
    await state.update_data(content=message.text)
    await state.set_state(NewsState.media)
    await message.answer("🖼️ Прикрепите фото/видео/PDF или отправьте 'пропустить':")

@dp.message(NewsState.media)
async def process_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    media_type = None
    media_id = None
    
    if message.text and message.text.lower() == 'пропустить':
        pass
    else:
        if message.photo:
            media_type = 'photo'
            media_id = message.photo[-1].file_id
        elif message.video:
            media_type = 'video'
            media_id = message.video.file_id
        elif message.document:
            media_type = 'document'
            media_id = message.document.file_id
        else:
            await message.answer("❌ Недопустимый тип файла. Отправьте фото, видео или PDF")
            return

    db.News.create(
        title=data['title'],
        content=data['content'],
        media_type=media_type,
        media_id=media_id
    )

    # Рассылка уведомлений
    users = db.User.get_all()
    for user in users:
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text="🎉 Вышла новая новость! Напишите /news чтобы посмотреть"
            )
        except Exception as e:
            logging.error(f"Ошибка отправки пользователю {user['user_id']}: {e}")

    await state.clear()
    await message.answer("✅ Новость успешно опубликована!")

@dp.message(Command('news'))
async def show_last_news(message: types.Message):
    news = db.News.get_all()
    if not news:
        return await message.answer("📰 Новостей пока нет")
    
    last_news = news[-1]
    text = f"<b>Последняя новость:</b>\n\n{last_news['title']}\n\n{last_news['content']}"
    
    try:
        if last_news.get('media_type') == 'photo':
            await message.answer_photo(last_news['media_id'], caption=text)
        elif last_news.get('media_type') == 'video':
            await message.answer_video(last_news['media_id'], caption=text)
        elif last_news.get('media_type') == 'document':
            await message.answer_document(last_news['media_id'], caption=text)
        else:
            await message.answer(text)
    except Exception as e:
        await message.answer("⚠️ Не удалось загрузить медиафайл последней новости")
        logging.error(f"Ошибка загрузки медиа: {e}")

@dp.message(Command('all_news'))
async def show_all_news(message: types.Message):
    news = db.News.get_all()
    if not news:
        return await message.answer("📰 Новостей пока нет")

    await message.answer("🗞 Все новости:")
    
    for item in reversed(news):
        text = f"<b>{item['title']}</b>\n\n{item['content']}"
        media_type = item.get('media_type')
        media_id = item.get('media_id')
        
        try:
            if media_type == 'photo':
                await message.answer_photo(media_id, caption=text)
            elif media_type == 'video':
                await message.answer_video(media_id, caption=text)
            elif media_type == 'document':
                await message.answer_document(media_id, caption=text)
            else:
                await message.answer(text)
        except Exception as e:
            await message.answer(f"⚠️ Не удалось загрузить новость от {item['created_at'][:10]}")
            logging.error(f"Ошибка загрузки медиа: {e}")

@dp.message(Command('delete_all_news'))
async def delete_all_news(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен")
    
    db.News.table.truncate()
    await message.answer("✅ Все новости успешно удалены!")

# Обработчик команды /help
@dp.message(Command('help'))
async def show_help(message: types.Message):
    if is_admin(message.from_user.id):
        help_text = """
<b>👑 Администраторские команды:</b>
/start - Начать работу с ботом
/reg - Зарегистрировать пользователя (команда для пользователей)
/generate_user_qr [ФИО] - Сгенерировать QR-код для сотрудника
/create_temp_pass [дни] - Создать временный гостевой пропуск
/block_pass [ID] [тип] - Блокировать пропуск (employee/guest)
/logs - Показать журнал доступа
/add_news - Добавить новость
/delete_all_news - Удалить все новости
/all_news - Показать все новости

<b>👤 Общие команды:</b>
/my_qrcode - Мой QR-пропуск
/scan_pass [код] - Сканировать пропуск
/news - Последняя новость
"""
    else:
        help_text = """
<b>📜 Доступные команды:</b>
/start - Начать работу
/reg - Пройти регистрацию
/my_qrcode - Показать мой QR-пропуск
/scan_pass [код] - Отсканировать пропуск
/news - Посмотреть последнюю новость

<code>По вопросам обращайтесь к администратору</code>
"""
    
    await message.answer(help_text)

@dp.message(F.text.startswith('/'))
async def handle_unknown_command(message: types.Message):
    await message.answer("⚠️ Такой команды не существует или она неверно написана.")

# Общий обработчик ВСЕГДА В КОНЦЕ
@dp.message()
async def register_user(message: types.Message):
    try:
        db.User.create(message.from_user.id)
        logging.info(f"Зарегистрирован пользователь: {message.from_user.id}")
    except Exception as e:
        logging.error(f"Ошибка регистрации: {e}")

if __name__ == '__main__':
    dp.run_polling(bot)