import logging
import re
import asyncio
import asyncpg

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from settings import TOKEN, ADMIN_CHAT_ID, DATABASE_URL
from models import Form

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Клавиатуры
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Услуги")],
        [KeyboardButton(text="О нас")],
        [KeyboardButton(text="Отправить отзыв")]
    ],
    resize_keyboard=True
)

services_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Физическое лицо")],
        [KeyboardButton(text="Компаниям")],
        [KeyboardButton(text="Назад")]
    ],
    resize_keyboard=True
)


# Функция валидации номера телефона
def validate_phone(phone):
    return re.fullmatch(r"8(?!1234567890|9990000000)\d{10}", phone)


# Функция валидации ИНН
def validate_inn(inn):
    return re.fullmatch(r"\d{10}|\d{12}", inn)


# Подключение к базе данных
async def init_db():
    return await asyncpg.create_pool(DATABASE_URL, ssl=False)


db_pool = None


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=main_menu)


@dp.message(lambda message: message.text == "Услуги")
async def services_cmd(message: types.Message):
    await message.answer("Выберите тип услуги:", reply_markup=services_menu)


@dp.message(lambda message: message.text == "Физическое лицо")
async def individual_service(message: types.Message, state: FSMContext):
    await message.answer("Мы предоставляем гибкий список услуг... Опишите в сообщении, какая помощь вам требуется.")
    await state.set_state(Form.description)


@dp.message(lambda message: message.text == "Компаниям")
async def company_service(message: types.Message, state: FSMContext):
    await message.answer("Мы предоставляем услуги для компаний... Опишите в сообщении, какая помощь вам требуется.")
    await state.set_state(Form.description)
    # Устанавливаем, что это компания, чтобы запросить ИНН позже
    await state.update_data(is_company=True)


@dp.message(Form.description)
async def get_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)

    user_data = await state.get_data()

    # Если это компания, запрашиваем ИНН
    if user_data.get('is_company'):
        await message.answer("Укажите ИНН вашей компании:")
        await state.set_state(Form.inn)
    else:
        await message.answer("Как Вас зовут?")
        await state.set_state(Form.name)


@dp.message(Form.inn)
async def get_company_inn(message: types.Message, state: FSMContext):
    if not validate_inn(message.text):
        await message.answer("Некорректный ИНН! Попробуйте снова.")
        return

    user_data = await state.get_data()
    user_data["inn"] = message.text
    await state.update_data(inn=user_data["inn"])  # Сохраняем ИНН в состоянии

    await message.answer("Как Вас зовут?")
    await state.set_state(Form.name)


@dp.message(Form.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Укажите Ваш номер телефона в формате '89991370000'")
    await state.set_state(Form.phone)


@dp.message(Form.phone)
async def get_phone(message: types.Message, state: FSMContext):
    if not validate_phone(message.text):
        await message.answer("Некорректный номер телефона! Попробуйте снова.")
        return

    user_data = await state.get_data()
    user_data["phone"] = message.text

    async with db_pool.acquire() as conn:
        # Проверяем, существует ли номер телефона
        existing_record = await conn.fetchrow("SELECT user_id, inn FROM dbtable WHERE phone = $1", user_data["phone"])

        if existing_record:
            user_id = existing_record["user_id"]  # Используем существующий user_id
            user_data["inn"] = existing_record["inn"]  # Получаем существующий ИНН
        else:
            # Создаем новую запись и получаем новый user_id
            user_id = await conn.fetchval(
                """
                INSERT INTO dbtable (description, name, phone, inn) 
                VALUES ($1, $2, $3, $4) RETURNING user_id
                """,
                user_data["description"], user_data["name"], user_data["phone"], user_data.get("inn")
            )

            # Создаем новую запись с полученным user_id
            await conn.execute("""
                INSERT INTO dbtable (description, name, phone, inn) 
                VALUES ($1, $2, $3, $4)
            """, user_data["description"], user_data["name"], user_data["phone"], user_data.get("inn"))

    msg = (f"Новая заявка:\nОписание: {user_data['description']}\nИмя: {user_data['name']}\n"
           f"Телефон: {user_data['phone']}\nИНН: {user_data.get('inn')}")
    await bot.send_message(ADMIN_CHAT_ID, msg)

    await message.answer("Ваша заявка отправлена, с вами свяжутся в ближайшее время", reply_markup=main_menu)
    await state.clear()


@dp.message(lambda message: message.text == "О нас")
async def about_cmd(message: types.Message):
    await message.answer("Home Service - это ключ к качеству и гибкости на рынке услуг ремонтных работ для физических "
                         "и юридических лиц. Телефон для справок: 8-991-053-11-85")


@dp.message(lambda message: message.text == "Отправить отзыв")
async def review_cmd(message: types.Message, state: FSMContext):
    await message.answer("Напишите отзыв.")
    await state.set_state(Form.review)


@dp.message(Form.review)
async def get_review(message: types.Message, state: FSMContext):
    await bot.send_message(ADMIN_CHAT_ID, f"Новый отзыв:\n{message.text}")
    await message.answer("Отзыв направлен на проверку, спасибо!", reply_markup=main_menu)
    await state.clear()


async def main():
    global db_pool
    db_pool = await init_db()
    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
