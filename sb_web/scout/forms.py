"""Formulários das observações, validados no servidor (Flask-WTF)."""
from flask_wtf import FlaskForm
from wtforms import HiddenField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, ValidationError

from sb_web.scout.models import NOTA_MAXIMA, NOTA_MINIMA, TAMANHO_AUTOR, TAMANHO_TEXTO

TAMANHO_MINIMO_TEXTO = 10


def _sem_espacos(valor):
    return valor.strip() if isinstance(valor, str) else valor


class ObservacaoForm(FlaskForm):
    """`jogadores` é o conjunto de ids da base: o id vem de um campo oculto e não pode ser confiado."""

    player_id = HiddenField(validators=[DataRequired("Escolha um jogador.")])
    # validate_choice desligado: validate_temporada confere a opção e responde em português.
    temporada = SelectField("Temporada", validate_choice=False, validators=[DataRequired("Escolha a temporada.")])
    autor = StringField(
        "Seu nome",
        filters=[_sem_espacos],
        validators=[
            DataRequired("Informe seu nome."),
            Length(min=2, max=TAMANHO_AUTOR, message=f"Use de 2 a {TAMANHO_AUTOR} caracteres."),
        ],
    )
    nota = IntegerField(
        f"Nota ({NOTA_MINIMA} a {NOTA_MAXIMA})",
        validators=[
            InputRequired("Dê uma nota."),
            NumberRange(min=NOTA_MINIMA, max=NOTA_MAXIMA, message=f"A nota vai de {NOTA_MINIMA} a {NOTA_MAXIMA}."),
        ],
    )
    texto = TextAreaField(
        "Observação",
        filters=[_sem_espacos],
        validators=[
            DataRequired("Escreva a observação."),
            Length(
                min=TAMANHO_MINIMO_TEXTO, max=TAMANHO_TEXTO,
                message=f"Escreva de {TAMANHO_MINIMO_TEXTO} a {TAMANHO_TEXTO} caracteres.",
            ),
        ],
    )

    def __init__(self, *args, jogadores=frozenset(), temporadas=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._jogadores = jogadores
        self.temporada.choices = [(t, t) for t in reversed(list(temporadas))]

    def validate_temporada(self, campo):
        if campo.data not in {valor for valor, _ in self.temporada.choices}:
            raise ValidationError("Temporada inválida.")

    def validate_player_id(self, campo):
        try:
            player_id = int(campo.data)
        except (TypeError, ValueError):
            raise ValidationError("Jogador inválido.") from None
        if player_id not in self._jogadores:
            raise ValidationError("Jogador não encontrado na base.")
        campo.data = player_id
