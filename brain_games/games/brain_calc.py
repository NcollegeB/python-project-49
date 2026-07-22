import random


CALC_OPERATIONS_NUMBER = 2  # количество операций в игре калькулятор
CALC_MAX_VALUE = 10  # максимальное значение чисел для игры калькулятор
NAME = 'Calculator'
SLUG = 'calc'
CATEGORY = 'Math'
RULES = 'What is the result of the expression?'


def get_question_and_answer():
    random1 = random.randint(0, CALC_MAX_VALUE)
    random2 = random.randint(0, CALC_MAX_VALUE)
    operation = random.choice(['+', '*', '-'])
    if operation == '+':
        question = f'{random1} + {random2}'
        answer = random1 + random2
    elif operation == '*':
        question = f'{random1} * {random2}'
        answer = random1 * random2
    elif operation == '-':
        question = f'{max(random1, random2)} - {min(random1, random2)}'
        answer = max(random1, random2) - min(random1, random2)
    return question, str(answer)
