import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message


TOKEN = "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎰 Привет!\n\n"
        "Добро пожаловать в Emoji Casino!"
    )


async def main():
    bot = Bot(TOKEN)

    print("Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
