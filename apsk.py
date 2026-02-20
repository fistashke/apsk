import asyncio
import logging
import sqlite3
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional

# --- НАСТРОЙКИ ---
TOKEN = "8438685814:AAEvrbY14BSa0Hg6b3iq6GR1Q1nsxIopydo"  # ВСТАВЬ СЮДА ТОКЕН!
ADMIN_IDS = [7985423843, 7330788297]  # ВСТАВЬТЕ ID АДМИНОВ ЧЕРЕЗ ЗАПЯТУЮ
CHANNEL_LINK = "https://t.me/apsk_clan"  # ССЫЛКА НА КАНАЛ С ПРАВИЛАМИ
CLAN_NAME = "APSK"
# -----------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- БАЗА ДАННЫХ ---
async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        # Таблица заявок
        await db.execute('''
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                nickname TEXT,
                hours TEXT,
                mode TEXT,
                files TEXT,
                comment TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP
            )
        ''')
        
        # Таблица принятых участников
        await db.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                nickname TEXT,
                mode TEXT,
                hours TEXT,
                joined_date TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        ''')
        await db.commit()

# --- КЛАСС СОСТОЯНИЙ ---
class ApplicationStates(StatesGroup):
    choosing_mode = State()
    entering_nickname = State()
    entering_hours = State()
    adding_files_comment = State()

# --- КЛАВИАТУРЫ ---

def main_keyboard():
    """Главная клавиатура для пользователя"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📝 ПОДАТЬ ЗАЯВКУ", callback_data="start_application"))
    return builder.as_markup()

def modes_keyboard():
    """Клавиатура выбора режима"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="БЛОК", callback_data="mode_block"),
        InlineKeyboardButton(text="КОГ", callback_data="mode_cog")
    )
    builder.row(
        InlineKeyboardButton(text="ФНГ", callback_data="mode_fng"),
        InlineKeyboardButton(text="РЕЙС", callback_data="mode_race")
    )
    builder.row(InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="cancel_application"))
    return builder.as_markup()

def application_control_keyboard():
    """Клавиатура управления заявкой"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📎 Прикрепить файлы/комментарий", callback_data="add_attachment"))
    builder.row(InlineKeyboardButton(text="✅ ЗАКОНЧИТЬ ЗАЯВКУ", callback_data="finish_application"))
    builder.row(InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_application"))
    return builder.as_markup()

def admin_main_keyboard():
    """Главная админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📨 Входящие заявки", callback_data="admin_applications"))
    builder.row(InlineKeyboardButton(text="👥 Принятые участники", callback_data="admin_members"))
    return builder.as_markup()

def admin_application_actions_keyboard(app_id: int):
    """Кнопки действий над заявкой"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{app_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")
    )
    builder.row(InlineKeyboardButton(text="🤝 Нужна встреча в игре", callback_data=f"meet_{app_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_applications"))
    return builder.as_markup()

def admin_members_actions_keyboard(member_id: int):
    """Кнопки действий над участником"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🚫 Исключить", callback_data=f"kick_{member_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_members"))
    return builder.as_markup()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS

async def save_application_to_db(data: dict):
    """Сохранение заявки в БД"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        await db.execute('''
            INSERT INTO applications (user_id, username, nickname, hours, mode, files, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['user_id'],
            data['username'],
            data['nickname'],
            data['hours'],
            data['mode'],
            data.get('files', ''),
            data.get('comment', ''),
            datetime.now()
        ))
        await db.commit()
        cursor = await db.execute('SELECT last_insert_rowid()')
        row = await cursor.fetchone()
        return row[0]

async def get_pending_applications():
    """Получить все ожидающие заявки"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM applications WHERE status = 'pending' ORDER BY created_at DESC
        ''')
        return await cursor.fetchall()

async def get_all_members():
    """Получить всех принятых участников"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM members WHERE status = 'active' ORDER BY joined_date DESC
        ''')
        return await cursor.fetchall()

async def update_application_status(app_id: int, status: str):
    """Обновить статус заявки"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        await db.execute('UPDATE applications SET status = ? WHERE id = ?', (status, app_id))
        await db.commit()

async def add_to_members(application):
    """Добавить пользователя в участники"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        await db.execute('''
            INSERT OR REPLACE INTO members (user_id, nickname, mode, hours, joined_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            application['user_id'],
            application['nickname'],
            application['mode'],
            application['hours'],
            datetime.now(),
            'active'
        ))
        await db.commit()

async def remove_member(user_id: int):
    """Исключить участника"""
    async with aiosqlite.connect('clan_apsk.db') as db:
        await db.execute('UPDATE members SET status = "kicked" WHERE user_id = ?', (user_id,))
        await db.commit()

# --- ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Приветственное сообщение"""
    text = f"""
🔰 APSK CLAN APPLICATION SYSTEM 🔰

Добро пожаловать в систему подачи заявок клана {CLAN_NAME}!

Чтобы подать заявку на вступление, нажми кнопку ниже.
"""
    if await is_admin(message.from_user.id):
        text += "\n👑 У вас есть права администратора!"
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="📝 Подать заявку", callback_data="start_application"))
        builder.row(InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel"))
        await message.answer(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=main_keyboard())

@dp.callback_query(F.data == "start_application")
async def start_application(callback: CallbackQuery, state: FSMContext):
    """Начало подачи заявки"""
    await callback.message.edit_text(
        "🔹Выберите режим, на который хотите податься:\n\n"
        "•БЛОК\n"
        "•КОГ\n"
        "•ФНГ\n"
        "•РЕЙС",
        reply_markup=modes_keyboard()
    )
    await state.set_state(ApplicationStates.choosing_mode)
    await callback.answer()

@dp.callback_query(F.data.startswith("mode_"))
async def process_mode(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора режима"""
    mode_map = {
        "mode_block": "БЛОК",
        "mode_cog": "КОГ", 
        "mode_fng": "ФНГ",
        "mode_race": "РЕЙС"
    }
    selected_mode = mode_map[callback.data]
    
    await state.update_data(mode=selected_mode)
    
    await callback.message.edit_text(
        f"✅ Выбран режим: {selected_mode}\n\n"
        "📝 Введите ваш игровой никнейм:"
    )
    await state.set_state(ApplicationStates.entering_nickname)
    await callback.answer()

@dp.message(ApplicationStates.entering_nickname)
async def process_nickname(message: types.Message, state: FSMContext):
    """Обработка ника"""
    await state.update_data(nickname=message.text)
    
    await message.answer(
        "⏱Введите ваше количество часов:\n"
    )
    await state.set_state(ApplicationStates.entering_hours)

@dp.message(ApplicationStates.entering_hours)
async def process_hours(message: types.Message, state: FSMContext):
    """Обработка количества часов"""
    await state.update_data(hours=message.text)
    data = await state.get_data()
    
    rules_text = f"""
📋 ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ЗАЯВКИ

Режим: {data['mode']}
Ник: {data['nickname']}
Часов в день: {data['hours']}

⚠️ ВАЖНО!
Перед отправкой заявки убедитесь, что вы прочитали правила вступления в нашем канале:
{CHANNEL_LINK}

Вы можете прикрепить скриншоты, демо или добавить комментарий к заявке.
    """
    
    await message.answer(rules_text, reply_markup=application_control_keyboard())
    await state.set_state(ApplicationStates.adding_files_comment)

@dp.callback_query(F.data == "add_attachment", StateFilter(ApplicationStates.adding_files_comment))
async def add_attachment(callback: CallbackQuery, state: FSMContext):
    """Добавление вложений"""
    await callback.message.edit_text(
        "📎 Отправьте файлы или текст комментария\n"
        "(можно отправить несколько сообщений)\n\n"
        "Когда закончите, нажмите кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Закончить добавление", callback_data="finish_attachment")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "finish_attachment")
async def finish_attachment(callback: CallbackQuery, state: FSMContext):
    """Завершение добавления вложений"""
    await callback.message.edit_text(
        "📋 Продолжаем оформление заявки",
        reply_markup=application_control_keyboard()
    )
    await callback.answer()

@dp.message(StateFilter(ApplicationStates.adding_files_comment))
async def process_attachment(message: types.Message, state: FSMContext):
    """Сохранение вложений/комментариев"""
    data = await state.get_data()
    
    # Сохраняем файлы и комментарии
    attachments = data.get('attachments', [])
    
    if message.text:
        attachments.append(f"💬 Комментарий: {message.text}")
        await message.answer("✅ Комментарий добавлен!")
    elif message.photo:
        file_id = message.photo[-1].file_id
        attachments.append(f"📸 Фото: {file_id}")
        await message.answer("✅ Фото добавлено!")
    elif message.document:
        attachments.append(f"📄 Документ: {message.document.file_name}")
        await message.answer("✅ Документ добавлен!")
    
    await state.update_data(attachments=attachments)

@dp.callback_query(F.data == "finish_application")
async def finish_application(callback: CallbackQuery, state: FSMContext):
    """Завершение и отправка заявки"""
    data = await state.get_data()
    
    # Формируем данные для сохранения
    application_data = {
        'user_id': callback.from_user.id,
        'username': callback.from_user.username or "Нет username",
        'nickname': data['nickname'],
        'hours': data['hours'],
        'mode': data['mode'],
        'files': '\n'.join(data.get('attachments', [])),
        'comment': ''
    }
    
    # Сохраняем в БД
    app_id = await save_application_to_db(application_data)
    
    await callback.message.edit_text(
        f"✅ЗАЯВКА №{app_id} ОТПРАВЛЕНА!\n\n"
        "Ожидайте решения администрации. Мы свяжемся с вами в ближайшее время."
    )
    
    # Отправляем уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 НОВАЯ ЗАЯВКА #{app_id}\n\n"
                f"👤 От: @{callback.from_user.username or 'Нет username'}\n"
                f"🎮 Ник: {data['nickname']}\n"
                f"⚡️ Режим: {data['mode']}\n"
                f"⏱ Часов: {data['hours']}\n"
                f"📎 Вложения:\n{chr(10).join(data.get('attachments', ['Нет']))}\n\n"
                "Перейдите в админ-панель для рассмотрения."
            )
        except:
            pass
    
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "cancel_application")
async def cancel_application(callback: CallbackQuery, state: FSMContext):
    """Отмена заявки"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Подача заявки отменена.\n"
        "Если передумаете - нажмите /start",
        reply_markup=main_keyboard()
    )
    await callback.answer()

# --- АДМИН-ПАНЕЛЬ ---

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    """Главная админ-панель"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👑 АДМИН-ПАНЕЛЬ APSK\n\n"
        "Выберите раздел:",
        reply_markup=admin_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_applications")
async def admin_applications(callback: CallbackQuery):
    """Просмотр входящих заявок"""
    if not await is_admin(callback.from_user.id):
        return
    
    applications = await get_pending_applications()
    
    if not applications:
        await callback.message.edit_text(
            "📭 Нет новых заявок",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ])
        )
        return
    
    # Показываем первую заявку
    app = applications[0]
    
    text = f"""
📨 ЗАЯВКА #{app['id']}

👤 Ник: {app['nickname']}
🎮 Режим: {app['mode']}
⏱ Часов: {app['hours']}
📎 Вложения/Комментарии:
{app['files'] or 'Нет'}

Всего заявок: {len(applications)}
    """
    
    await callback.message.edit_text(text, reply_markup=admin_application_actions_keyboard(app['id']))
    await callback.answer()

@dp.callback_query(F.data.startswith("accept_"))
async def accept_application(callback: CallbackQuery):
    """Принять заявку"""
    app_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM applications WHERE id = ?', (app_id,))
        application = await cursor.fetchone()
    
    if application:
        # Обновляем статус
        await update_application_status(app_id, 'accepted')
        
        # Добавляем в участники
        await add_to_members(application)
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                application['user_id'],
                f"✅ ПОЗДРАВЛЯЕМ!\n\n"
                f"Ваша заявка в клан {CLAN_NAME} принята!\n"
                f"Добро пожаловать в семью APSK! 🎉"
            )
        except:
            pass
        
        await callback.answer("Заявка принята!", show_alert=True)
    
    # Показываем следующую заявку
    await admin_applications(callback)

@dp.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    """Отклонить заявку"""
    app_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM applications WHERE id = ?', (app_id,))
        application = await cursor.fetchone()
    
    if application:
        await update_application_status(app_id, 'rejected')
        
        try:
            await bot.send_message(
                application['user_id'],
                f"❌ ЗАЯВКА ОТКЛОНЕНА\n\n"
                f"К сожалению, ваша заявка в клан {CLAN_NAME} была отклонена.\n"
                f"Попробуйте подать заявку снова через некоторое время."
            )
        except:
            pass
        
        await callback.answer("Заявка отклонена!", show_alert=True)
    
    await admin_applications(callback)

@dp.callback_query(F.data.startswith("meet_"))
async def need_meeting(callback: CallbackQuery):
    """Нужна встреча в игре"""
    app_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM applications WHERE id = ?', (app_id,))
        application = await cursor.fetchone()
    
    if application:
        await update_application_status(app_id, 'meeting_needed')
        
        try:
            await bot.send_message(
                application['user_id'],
                f"🤝ВСТРЕЧА В ИГРЕ\n\n"
                f"Администрации клана {CLAN_NAME} нужно встретиться с вами в игре.\n"
                f"Ожидайте, с вами свяжутся в ближайшее время!"
            )
        except:
            pass
        
        await callback.answer("Запрос на встречу отправлен!", show_alert=True)
    
    await admin_applications(callback)

@dp.callback_query(F.data == "admin_members")
async def admin_members(callback: CallbackQuery):
    """Просмотр принятых участников"""
    if not await is_admin(callback.from_user.id):
        return
    
    members = await get_all_members()
    
    if not members:
        await callback.message.edit_text(
            "👥 Нет принятых участников",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ])
        )
        return
    
    text = "👥 ПРИНЯТЫЕ УЧАСТНИКИ\n\n"
    
    for member in members:
        text += f"• {member['nickname']} | {member['mode']} | {member['hours']}ч\n"
    
    # Клавиатура для выбора участника для исключения
    builder = InlineKeyboardBuilder()
    for member in members[:5]:  # Показываем первых 5 для выбора
        builder.row(InlineKeyboardButton(
            text=f"🚫 {member['nickname'][:15]}", 
            callback_data=f"select_kick_{member['user_id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("select_kick_"))
async def select_kick(callback: CallbackQuery):
    """Выбор участника для исключения"""
    user_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect('clan_apsk.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM members WHERE user_id = ?', (user_id,))
        member = await cursor.fetchone()
    
    if member:
        await callback.message.edit_text(
            f"🚫 Исключить участника?\n\n"
            f"Ник: {member['nickname']}\n"
            f"Режим: {member['mode']}\n"
            f"Дата вступления: {member['joined_date']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, исключить", callback_data=f"kick_{user_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_members")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("kick_"))
async def kick_member(callback: CallbackQuery):
    """Исключение участника"""
    user_id = int(callback.data.split("_")[1])
    
    await remove_member(user_id)
    
    try:
        await bot.send_message(
            user_id,
            f"⚠️ ВЫ ИСКЛЮЧЕНЫ ИЗ КЛАНА\n\n"
            f"Вы были исключены из клана {CLAN_NAME}.\n"
            f"По вопросам обращайтесь к администрации."
        )
    except:
        pass
    
    await callback.answer("Участник исключен!", show_alert=True)
    await admin_members(callback)

# --- ЗАПУСК ---
async def main():
    await init_db()
    print(f"Бот {CLAN_NAME} запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

