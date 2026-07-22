import random
from brain_games.engine import MAX_VALUE


NAME = 'Even or Odd'
SLUG = 'even'
CATEGORY = 'Math'
ANSWER_ALIASES = {'y': 'yes', 'n': 'no'}
RULES = 'Is the number even? Answer yes/no or y/n.'


def get_question_and_answer():
    rand = random.randint(0, MAX_VALUE)
    question_and_answer = (rand, is_even(rand) and 'yes' or 'no')
    return question_and_answer


def is_even(number):
    return number % 2 == 0
