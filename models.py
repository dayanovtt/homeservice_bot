from aiogram.fsm.state import StatesGroup, State

# Определение состояний
class Form(StatesGroup):
    description = State()
    name = State()
    phone = State()
    inn = State()
    review = State()