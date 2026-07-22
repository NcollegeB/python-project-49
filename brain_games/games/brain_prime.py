import random
from brain_games.engine import MAX_VALUE


NAME = 'Prime Number'
SLUG = 'prime'
CATEGORY = 'Math'
ANSWER_ALIASES = {'y': 'yes', 'n': 'no'}
RULES = 'Is the number prime? Answer yes/no or y/n.'


def get_question_and_answer():
    rand = random.randint(0, MAX_VALUE)
    question_and_answer = (rand, is_prime(rand) and 'yes' or 'no')
    return question_and_answer


def is_prime(number):
    if number <= 1:
        return False
    for i in range(2, (number // 2) + 1):
        if number % i == 0:
            return False
    return True
