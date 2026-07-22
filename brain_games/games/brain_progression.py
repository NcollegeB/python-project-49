import random
from brain_games.engine import MAX_VALUE


MIN_SEQUENCE_LENGTH = 5  # минимальная длина прогрессии
MAX_SEQUENCE_LENGTH = 10  # максимальная длина прогрессии
DIFFERENCE = 10  # максимальный шаг прогрессии
NAME = 'Missing Progression'
SLUG = 'progression'
RULES = 'What number is missing in the progression?'


def get_question_and_answer():
    initial_term = random.randint(0, MAX_VALUE)
    number_of_terms = random.randint(MIN_SEQUENCE_LENGTH, MAX_SEQUENCE_LENGTH)
    difference = random.randint(1, DIFFERENCE)
    array = get_sequence(initial_term, difference, number_of_terms)
    hidden_index = random.randint(0, len(array) - 1)
    question = f"{' '.join(array[:hidden_index])} .. " \
               f"{' '.join(array[hidden_index + 1:])}".strip()
    answer = (array[hidden_index])
    question_and_answer = (question, answer)
    return question_and_answer


def get_sequence(initial_term, difference, number_of_terms):
    last_term = initial_term + difference * number_of_terms
    return [str(x) for x in range(initial_term, last_term, difference)]
