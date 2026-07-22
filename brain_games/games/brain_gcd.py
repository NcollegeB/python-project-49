import random
from brain_games.engine import MAX_VALUE

NAME = 'Greatest Common Divisor'
SLUG = 'gcd'
RULES = 'Find the greatest common divisor of given numbers.'


def get_question_and_answer():
    rand1 = random.randint(1, MAX_VALUE)
    rand2 = random.randint(1, MAX_VALUE)
    question_and_answer = (f'{rand1} {rand2}', str(get_gcd(rand1, rand2)))
    return question_and_answer


def get_gcd(number1, number2):
    if number1 == 0 or number2 == 0:
        return max(number1, number2)
    else:
        if number1 > number2:
            return get_gcd(number1 % number2, number2)
        else:
            return get_gcd(number1, number2 % number1)
