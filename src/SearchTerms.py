import re
import unicodedata
from importlib.metadata import version

# Termos de busca por condição, no formato {grupo: [termos]} usado pelo main.py.
#
# Critérios: nome da condição, variantes comuns em português e equivalente em inglês
# (a loja brasileira tem muitos apps com título em inglês). Termos neutros, sem
# palavras como "jogos" ou "aprender", para não enviesar a amostra para apps de
# aprendizagem.

terms = {
    "TDAH": [
        "tdah",
        "déficit de atenção",
        "transtorno do déficit de atenção com hiperatividade",
        "adhd",
        "attention deficit",
    ],
    "TDL": [
        "transtorno do desenvolvimento da linguagem",
        "atraso de linguagem",
        "atraso na fala",
        "developmental language disorder",
        # "tdl",  # sigla curta e ambígua: provável ruído
    ],
    "DISLEXIA": [
        "dislexia",
        "transtorno de leitura",
        "dyslexia",
    ],
    "TDC": [
        "dispraxia",
        "transtorno do desenvolvimento da coordenação",
        "dyspraxia",
        "developmental coordination disorder",
        # "tdc",  # sigla ambígua
    ],
    "DISCALCULIA": [
        "discalculia",
        "dificuldade em matemática",
        "dyscalculia",
    ],
    "AHSD": [
        "altas habilidades",
        "superdotação",
        "altas habilidades superdotação",
        "gifted",
        # "ah/sd",  # sigla ambígua
    ],
    "DISGRAFIA": [
        "disgrafia",
        "dificuldade de escrita",
        "dysgraphia",
    ],
    "TEA": [
        "autismo",
        "transtorno do espectro autista",
        "autism",
        "espectro autista",
        # "tea",  # em inglês é "chá": traz apps de chá
    ],
    "DI": [
        "deficiência intelectual",
        "intellectual disability",
        # "di",  # sigla ambígua
    ],
    "TOURETTE": [
        "síndrome de tourette",
        "tourette",
        "tiques",
        "tourette syndrome",
    ],
    "GERAL": [
        "neurodivergente",
        "neurodiversidade",
        "necessidades especiais",
        "educação especial",
    ],
}

def slugify(text: str) -> str:
    """'Déficit de atenção' -> 'deficit_de_atencao' (seguro para nome de arquivo)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")