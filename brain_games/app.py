from flask import Flask, render_template, jsonify
from flask_cors import CORS
from brain_games.models import db, Game
from brain_games.admin import admin, GameAdminView
from brain_games.games import brain_calc
from brain_games.games import brain_even
from brain_games.games import brain_gcd
from brain_games.games import brain_prime
from brain_games.games import brain_progression
from dotenv import load_dotenv
import os

app = Flask(__name__)
CORS(app)
load_dotenv()

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.getenv(
    'SQLALCHEMY_TRACK_MODIFICATIONS',
)

db.init_app(app)
admin.init_app(app)

admin.add_view(GameAdminView(Game, session=db.session))

games = {
    "Calculator": brain_calc,
    "Even": brain_even,
    "GCD": brain_gcd,
    "Prime": brain_prime,
    "Progression": brain_progression
}


@app.route('/', methods=['GET', 'POST'])
def index():
    games = Game.query.all()
    return render_template('index.html', games=games)


@app.route('/api/<game_name>')
def get_game_data(game_name):
    rules = games[game_name].RULES
    question, answer = games[game_name].get_question_and_answer()
    return jsonify({
        'rules': rules,
        'question': question,
        'answer': answer
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
