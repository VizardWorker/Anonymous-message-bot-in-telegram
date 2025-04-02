import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import asyncio
from uuid import uuid4
import logging
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "YOUR_BOT_TOKEN"  # Замените на ваш токен бота
ADMIN_ID = "YOUR_TELEGRAM_ID"  # Замените на ваш Telegram ID
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
bot_username = None

# Определение состояний
class UserState(StatesGroup):
    waiting_for_anon_message = State()
    waiting_for_admin_id = State()
    waiting_for_ban_duration = State()  # Можно удалить, если не нужен текстовый ввод

# База данных
def init_db():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id INTEGER PRIMARY KEY, unique_link TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      link_owner_id INTEGER, 
                      sender_id INTEGER,
                      message TEXT, 
                      is_reported INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins 
                     (admin_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_users 
                     (user_id INTEGER PRIMARY KEY, ban_until TEXT)''')
        c.execute("PRAGMA table_info(blocked_users)")
        columns = [col[1] for col in c.fetchall()]
        if 'ban_until' not in columns:
            c.execute("ALTER TABLE blocked_users ADD COLUMN ban_until TEXT")
            logger.info("Added column 'ban_until' to blocked_users table")
        c.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))

def is_admin(user_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,))
        return c.fetchone() is not None

def add_admin(admin_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (admin_id,))

def remove_admin(admin_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE admin_id=?", (admin_id,))

def get_admins():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT admin_id FROM admins")
        return [row[0] for row in c.fetchall()]

def is_user_blocked(user_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT ban_until FROM blocked_users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        if result and result[0]:
            ban_until = datetime.fromisoformat(result[0])
            if datetime.now() > ban_until:
                unblock_user(user_id)
                return False
            return True
        return False

def block_user(user_id, duration_hours):
    ban_until = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO blocked_users (user_id, ban_until) VALUES (?, ?)", 
                  (user_id, ban_until))

def unblock_user(user_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
    asyncio.create_task(notify_unblock(user_id))

async def notify_unblock(user_id):
    try:
        await bot.send_message(user_id, "<b>✅ Ваш бан истёк</b>, вы снова можете использовать бота!")
    except TelegramBadRequest as e:
        logger.error(f"Failed to notify user {user_id} about unblock: {e}")

def get_blocked_users():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, ban_until FROM blocked_users")
        return c.fetchall()

def get_reported_messages():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT id, link_owner_id, sender_id, message FROM messages WHERE is_reported=1")
        return c.fetchall()

def get_or_create_user_link(user_id):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT unique_link FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        if not result:
            unique_link = str(uuid4()).replace('-', '')
            c.execute("INSERT INTO users (user_id, unique_link) VALUES (?, ?)", (user_id, unique_link))
        else:
            unique_link = result[0]
        return unique_link

def get_link_owner(unique_link):
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE unique_link=?", (unique_link,))
        result = c.fetchone()
        return result[0] if result else None

# Клавиатуры
def get_main_menu(is_admin=False):
    builder = InlineKeyboardBuilder()
    builder.button(text="📎 Получить мою ссылку", callback_data="get_link")
    if is_admin:
        builder.button(text="👨‍💼 Админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_report_button(msg_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 Пожаловаться", callback_data=f"report_{msg_id}")
    return builder.as_markup()

def get_admin_panel():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Список заблокированных", callback_data="list_blocked")
    builder.button(text="📩 Список жалоб", callback_data="list_reports")
    builder.button(text="👥 Управление администраторами", callback_data="manage_admins")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_ban_duration_panel(sender_id, msg_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="1 час", callback_data=f"ban_{sender_id}_{msg_id}_1")
    builder.button(text="24 часа", callback_data=f"ban_{sender_id}_{msg_id}_24")
    builder.button(text="7 дней", callback_data=f"ban_{sender_id}_{msg_id}_168")
    builder.button(text="Навсегда", callback_data=f"ban_{sender_id}_{msg_id}_0")
    builder.button(text="Игнорировать", callback_data=f"ignore_{msg_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_edit_ban_duration_panel(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="1 час", callback_data=f"edit_ban_duration_{user_id}_1")
    builder.button(text="24 часа", callback_data=f"edit_ban_duration_{user_id}_24")
    builder.button(text="7 дней", callback_data=f"edit_ban_duration_{user_id}_168")
    builder.button(text="Навсегда", callback_data=f"edit_ban_duration_{user_id}_0")
    builder.button(text="🔙 Назад", callback_data=f"manage_{user_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_blocked_user_panel(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить срок", callback_data=f"edit_ban_{user_id}")
    builder.button(text="✅ Разблокировать", callback_data=f"unblock_{user_id}")
    builder.button(text="🔙 Назад", callback_data="list_blocked")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_list_keyboard():
    builder = InlineKeyboardBuilder()
    admins = get_admins()
    for admin_id in admins:
        builder.button(text=f"Удалить {admin_id}", callback_data=f"remove_admin_{admin_id}")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

# Обработчики
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    global bot_username
    args = message.text.split()
    user_id = message.from_user.id
    if is_user_blocked(user_id):
        await message.answer("<b>🚫 Вы заблокированы</b> и не можете использовать бота!")
        return
    if len(args) == 1:
        unique_link = get_or_create_user_link(user_id)
        link = f"https://t.me/{bot_username}?start={unique_link}"
        admin_hint = "<b>Вы админ.</b> Используйте /add_admin для добавления администраторов." if is_admin(user_id) else ""
        text = (
            f"<b>👋 Добро пожаловать!</b>\n\n"
            f"Я помогу вам получать анонимные сообщения.\n\n"
            f"Ваша уникальная ссылка: <a href='{link}'>{link}</a>\n\n"
            f"Поделитесь ею с друзьями!\n\n"
            f"• Получите уникальную ссылку\n"
            f"• Делитесь ею с друзьями\n"
            f"• Получайте анонимные сообщения\n"
            f"• Жалуйтесь на нежелательный контент\n\n"
            f"{admin_hint}"
        )
        await message.answer(text, reply_markup=get_main_menu(is_admin(user_id)), disable_web_page_preview=True)
    else:
        unique_link = args[1]
        owner_id = get_link_owner(unique_link)
        if owner_id:
            await message.answer("✍️ Напишите ваше анонимное сообщение:")
            await state.set_state(UserState.waiting_for_anon_message)
            await state.update_data(owner_id=owner_id)
        else:
            await message.answer("❌ Ссылка недействительна", reply_markup=get_main_menu(is_admin(user_id)))

@dp.message(UserState.waiting_for_anon_message)
async def process_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if is_user_blocked(user_id):
        await message.answer("<b>🚫 Вы заблокированы</b> и не можете отправлять сообщения!")
        await state.clear()
        return
    data = await state.get_data()
    owner_id = data.get("owner_id")
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO messages (link_owner_id, sender_id, message) VALUES (?, ?, ?)",
                  (owner_id, user_id, message.text))
        msg_id = c.lastrowid
    await bot.send_message(owner_id, f"<b>✨ Новое анонимное сообщение:</b>\n{message.text}", 
                          reply_markup=get_report_button(msg_id))
    await message.answer("<b>✅ Сообщение отправлено!</b>", reply_markup=get_main_menu(is_admin(user_id)))
    await state.clear()

@dp.callback_query(lambda c: c.data == "get_link")
async def get_link(call: types.CallbackQuery):
    user_id = call.from_user.id
    if is_user_blocked(user_id):
        await call.message.edit_text("<b>🚫 Вы заблокированы</b> и не можете использовать бота!")
        return
    unique_link = get_or_create_user_link(user_id)
    link = f"https://t.me/{bot_username}?start={unique_link}"
    text = f"📎 Ваша ссылка:\n<a href='{link}'>{link}</a>"
    await call.message.edit_text(text, reply_markup=get_main_menu(is_admin(user_id)), disable_web_page_preview=True)
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("report_"))
async def process_report(call: types.CallbackQuery):
    msg_id = int(call.data.split("_")[1])
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT link_owner_id, sender_id, message FROM messages WHERE id=?", (msg_id,))
        result = c.fetchone()
        c.execute("UPDATE messages SET is_reported=1 WHERE id=?", (msg_id,))
    if result:
        owner_id, sender_id, reported_message = result
        notification_text = (
            f"<b>🚨 Новая жалоба!</b>\n"
            f"Владелец ссылки: {owner_id}\n"
            f"Отправитель: {sender_id}\n"
            f"Сообщение: {reported_message}"
        )
        for admin_id in get_admins():
            try:
                await bot.send_message(admin_id, notification_text, reply_markup=get_ban_duration_panel(sender_id, msg_id))
                logger.info(f"Notified admin {admin_id} about report on message {msg_id}")
            except TelegramBadRequest as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    await call.message.edit_text("<b>✅ Жалоба отправлена!</b>", reply_markup=get_main_menu(is_admin(call.from_user.id)))
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("ban_"))
async def handle_ban(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id, msg_id, duration = int(parts[1]), int(parts[2]), int(parts[3])
    duration_hours = duration if duration > 0 else 999999
    ban_until = datetime.now() + timedelta(hours=duration_hours)
    block_user(user_id, duration_hours)
    
    if duration > 0:
        duration_text = f"{duration} час(ов), до {ban_until.strftime('%Y-%m-%d %H:%M')}"
    else:
        duration_text = "навсегда"
    
    text = f"<b>🚫 Пользователь {user_id}</b> заблокирован на {duration_text}"
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE id=?", (msg_id,))
    
    await call.message.edit_text(text)
    await call.answer(f"✅ Пользователь заблокирован на {duration_text}")
    
    try:
        await bot.send_message(user_id, f"<b>🚫 Вы были заблокированы</b> на {duration_text}")
    except TelegramBadRequest as e:
        logger.warning(f"Не удалось уведомить пользователя {user_id} о бане: {e}")

@dp.callback_query(lambda c: c.data.startswith("ignore_"))
async def ignore_report(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    msg_id = int(call.data.split("_")[1])
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE id=?", (msg_id,))
    await call.message.edit_text("<b>✅ Жалоба проигнорирована и удалена</b>")
    await call.answer("✅ Жалоба проигнорирована")

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    text = "<b>👨‍💼 Админ-панель:</b>"
    await call.message.edit_text(text, reply_markup=get_admin_panel())
    await call.answer()

@dp.callback_query(lambda c: c.data == "list_blocked")
async def list_blocked(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    blocked = get_blocked_users()
    if not blocked:
        text = "<b>📋 Список заблокированных пуст</b>"
    else:
        text = "<b>📋 Заблокированные пользователи:</b>\n"
        for user_id, ban_until in blocked:
            ban_until_dt = datetime.fromisoformat(ban_until)
            remaining = ban_until_dt - datetime.now()
            remaining_text = f"до {ban_until_dt.strftime('%Y-%m-%d %H:%M')}" if remaining.total_seconds() > 0 else "навсегда"
            text += f"• {user_id} - {remaining_text}\n"
    builder = InlineKeyboardBuilder()
    for user_id, _ in blocked:
        builder.button(text=f"👤 {user_id}", callback_data=f"manage_{user_id}")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@dp.callback_query(lambda c: c.data == "list_reports")
async def list_reports(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    reports = get_reported_messages()
    if not reports:
        text = "<b>📩 Список жалоб пуст</b>"
    else:
        text = "<b>📩 Жалобы:</b>\n"
        for msg_id, owner_id, sender_id, message in reports:
            truncated_message = message[:50] + "..." if len(message) > 50 else message
            text += f"ID: {msg_id} | Отправитель: {sender_id} | Владелец: {owner_id}\nСообщение: {truncated_message}\n"
    builder = InlineKeyboardBuilder()
    for msg_id, _, sender_id, _ in reports:
        builder.button(text=f"📩 {msg_id}", callback_data=f"manage_report_{sender_id}_{msg_id}")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("manage_report_"))
async def manage_report(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    parts = call.data.split("_")
    sender_id, msg_id = int(parts[2]), int(parts[3])
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT link_owner_id, message FROM messages WHERE id=?", (msg_id,))
        result = c.fetchone()
    if result:
        owner_id, message = result
        text = (
            f"<b>📩 Жалоба ID: {msg_id}</b>\n"
            f"Владелец ссылки: {owner_id}\n"
            f"Отправитель: {sender_id}\n"
            f"Сообщение: {message}"
        )
    else:
        text = f"<b>📩 Жалоба ID: {msg_id} не найдена</b>"
    await call.message.edit_text(text, reply_markup=get_ban_duration_panel(sender_id, msg_id))
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("manage_") and c.data.split("_")[1].isdigit())
async def manage_blocked(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    user_id = int(call.data.split("_")[1])
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute("SELECT ban_until FROM blocked_users WHERE user_id=?", (user_id,))
        result = c.fetchone()
    if result:
        ban_until = datetime.fromisoformat(result[0])
        remaining = ban_until - datetime.now()
        remaining_text = f"до {ban_until.strftime('%Y-%m-%d %H:%M')}" if remaining.total_seconds() > 0 else "навсегда"
        text = f"<b>👤 Пользователь {user_id}</b>\nСрок бана: {remaining_text}"
    else:
        text = f"<b>👤 Пользователь {user_id}</b> не найден в списке заблокированных"
    await call.message.edit_text(text, reply_markup=get_blocked_user_panel(user_id))
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_ban_") and len(c.data.split("_")) == 3)
async def edit_ban(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    user_id = int(call.data.split("_")[2])
    text = f"Выберите новый срок бана для <b>{user_id}</b>:"
    await call.message.edit_text(text, reply_markup=get_edit_ban_duration_panel(user_id))
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_ban_duration_") and len(c.data.split("_")) == 5)
async def handle_edit_ban_duration(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id, duration = int(parts[3]), int(parts[4])
    duration_hours = duration if duration > 0 else 999999
    ban_until = datetime.now() + timedelta(hours=duration_hours)
    
    if duration > 0:
        duration_text = f"{duration} час(ов), до {ban_until.strftime('%Y-%m-%d %H:%M')}"
    else:
        duration_text = "навсегда"
    
    block_user(user_id, duration_hours)
    text = f"<b>🚫 Срок бана для {user_id}</b> изменён на {duration_text}"
    await call.message.edit_text(text, reply_markup=get_blocked_user_panel(user_id))
    await call.answer(f"✅ Срок бана изменён на {duration_text}")
    
    try:
        await bot.send_message(user_id, f"<b>🚫 Ваш срок бана изменён</b> на {duration_text}")
    except TelegramBadRequest as e:
        logger.warning(f"Не удалось уведомить пользователя {user_id} о новом сроке бана: {e}")

@dp.message(UserState.waiting_for_ban_duration)  # Можно удалить, если не нужен текстовый ввод
async def process_ban_duration(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("<b>❌ У вас нет прав!</b>")
        await state.clear()
        return
    try:
        duration = int(message.text)
        if duration < 0:
            raise ValueError("Срок не может быть отрицательным")
        data = await state.get_data()
        user_id = data.get("user_id")
        duration_hours = duration if duration > 0 else 999999
        block_user(user_id, duration_hours)
        duration_text = f"{duration} час(ов)" if duration > 0 else "навсегда"
        text = f"<b>🚫 Срок бана для {user_id}</b> изменён на {duration_text}"
        await message.answer(text, reply_markup=get_main_menu(True))
        await state.clear()
    except ValueError:
        await message.answer("Ошибка: введите корректное число часов (0 или больше)!")

@dp.callback_query(lambda c: c.data.startswith("unblock_"))
async def unblock(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    user_id = int(call.data.split("_")[1])
    unblock_user(user_id)
    text = f"<b>✅ Пользователь {user_id} разблокирован</b>"
    await call.message.edit_text(text)
    await call.answer(f"✅ Пользователь {user_id} разблокирован")

@dp.callback_query(lambda c: c.data == "manage_admins")
async def manage_admins(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    admins = get_admins()
    if len(admins) <= 1:
        text = "<b>👥 Нельзя удалить последнего администратора!</b>"
    else:
        text = "<b>👥 Список администраторов:</b>\n" + "\n".join(f"• {admin_id}" for admin_id in admins)
    await call.message.edit_text(text, reply_markup=get_admin_list_keyboard())
    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("remove_admin_"))
async def remove_admin_handler(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ У вас нет прав!", show_alert=True)
        return
    admin_id = int(call.data.split("_")[2])
    admins = get_admins()
    if len(admins) <= 1:
        await call.answer("Нельзя удалить последнего администратора!", show_alert=True)
        return
    if admin_id == call.from_user.id:
        await call.answer("Вы не можете удалить себя!", show_alert=True)
        return
    if admin_id not in admins:
        await call.answer(f"Пользователь {admin_id} не является администратором!", show_alert=True)
        return
    remove_admin(admin_id)
    text = f"<b>👥 Администратор {admin_id} удалён</b>"
    await call.message.edit_text(text, reply_markup=get_admin_list_keyboard())
    await call.answer(f"Администратор {admin_id} удалён")

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    if is_user_blocked(user_id):
        await call.message.edit_text("<b>🚫 Вы заблокированы</b> и не можете использовать бота!")
        return
    unique_link = get_or_create_user_link(user_id)
    link = f"https://t.me/{bot_username}?start={unique_link}"
    text = f"📎 Ваша ссылка:\n<a href='{link}'>{link}</a>"
    await call.message.edit_text(text, reply_markup=get_main_menu(is_admin(user_id)), disable_web_page_preview=True)
    await call.answer()

@dp.message(Command("add_admin"))
async def add_admin_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("Команда не найдена.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Введите Telegram ID нового администратора (число):")
        await state.set_state(UserState.waiting_for_admin_id)
    else:
        try:
            new_admin_id = int(args[1])
            await process_add_admin_direct(message, new_admin_id)
        except ValueError:
            await message.answer("<b>Ошибка:</b> ID должен быть числом!")

@dp.message(UserState.waiting_for_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Команда не найдена.")
        await state.clear()
        return
    try:
        new_admin_id = int(message.text)
        await process_add_admin_direct(message, new_admin_id)
        await state.clear()
    except ValueError:
        await message.answer("<b>Ошибка:</b> Введите корректный Telegram ID (число)!")

async def process_add_admin_direct(message: types.Message, new_admin_id: int):
    if is_admin(new_admin_id):
        await message.answer("<b>⚠️ Этот пользователь уже администратор!</b>", reply_markup=get_main_menu(True))
    else:
        add_admin(new_admin_id)
        await message.answer(f"<b>✅ Пользователь {new_admin_id}</b> добавлен как администратор!", reply_markup=get_main_menu(True))
        try:
            await bot.send_message(new_admin_id, "<b>👨‍💼 Вы назначены администратором бота!</b>")
        except TelegramBadRequest as e:
            logger.warning(f"Не удалось уведомить нового админа {new_admin_id}: {e}")

# Основная функция
async def main():
    global bot_username
    init_db()
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    logger.info(f"Бот {bot_username} запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())