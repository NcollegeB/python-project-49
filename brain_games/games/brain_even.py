import random
from brain_games.engine import MAX_VALUE


NAME = 'Even or Odd'
SLUG = 'even'
RULES = 'Answer "yes" if the number is even, otherwise answer "no".'


def get_question_and_answer():
    rand = random.randint(0, MAX_VALUE)
    question_and_answer = (rand, is_even(rand) and 'yes' or 'no')
    return question_and_answer


def is_even(number):
    return number % 2 == 0
