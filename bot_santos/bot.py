import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaAnimation, ReactionTypeEmoji, BotCommand, BotCommandScopeAllPrivateChats
import google.genai as genai
from google.genai import types as genai_types
import random
import datetime
import time
import threading
import json
import io
import string
import math
import unicodedata
import html
import re
import shlex
import requests
from collections import deque
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

# === 1. TOKENS E CHAVES (nunca deixe valores reais direto no código) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GIPHY_API_KEY = os.environ.get("GIPHY_API_KEY")
STICKER_IDS = [item.strip() for item in os.environ.get("STICKER_IDS", "").split(",") if item.strip()]
ARQUIVO_STICKERS = os.path.join(os.path.dirname(__file__), "stickers_santos.json")
ARQUIVO_STICKERS_BICHO = os.path.join(os.path.dirname(__file__), "stickers_bicho.json")
ARQUIVO_CONFIG_GRUPOS = os.path.join(os.path.dirname(__file__), "config_grupos.json")


def carregar_lista_json(caminho):
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_lista_json(dados, caminho):
    escrever_json_atomico(caminho, dados)


def carregar_stickers():
    return carregar_lista_json(ARQUIVO_STICKERS)


def salvar_stickers(stickers):
    salvar_lista_json(stickers, ARQUIVO_STICKERS)


STICKER_IDS.extend(item for item in carregar_stickers() if item not in STICKER_IDS)
STICKER_BICHOS = carregar_lista_json(ARQUIVO_STICKERS_BICHO)
MODO_STICKER_BICHO = set()

if not TELEGRAM_TOKEN or not GEMINI_KEY:
    raise RuntimeError(
        "Defina TELEGRAM_TOKEN e GEMINI_KEY como variáveis de ambiente (veja .env.example) antes de rodar o bot."
    )

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Sobrescreve qualquer lista de comandos antiga configurada no BotFather, que causava confusão no menu do PV.
try:
    bot.set_my_commands(
        [
            BotCommand("start", "Abrir a central privada da Santos"),
            BotCommand("ajuda", "Abrir a central privada da Santos"),
            BotCommand("painel", "Ligar/desligar interações nos seus grupos"),
            BotCommand("addlink", "Cadastrar um link de plataforma"),
            BotCommand("links", "Ver links de plataforma cadastrados"),
            BotCommand("removerlink", "Remover um link de plataforma"),
            BotCommand("addbicho", "Ligar/desligar cadastro de stickers de bicho"),
            BotCommand("bichos", "Ver quantos stickers de bicho estão salvos"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
except Exception as erro:
    print(f"Não consegui atualizar o menu de comandos: {type(erro).__name__}: {erro}")

GEMINI_MODELO = "gemini-3.6-flash"
genai_client = genai.Client(api_key=GEMINI_KEY)


def gerar_texto_ia(prompt, retorno_padrao):
    try:
        resp = genai_client.models.generate_content(
            model=GEMINI_MODELO,
            contents=prompt,
            config=genai_types.GenerateContentConfig(temperature=0.7, max_output_tokens=300),
        )
        return (resp.text or "").strip() or retorno_padrao
    except Exception as erro:
        print(f"Erro ao chamar o Gemini: {type(erro).__name__}: {erro}")
        return retorno_padrao


def buscar_gif(termo):
    """Busca um GIF real no Giphy (API oficial); retorna None se não houver chave ou a busca falhar."""
    if not GIPHY_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.giphy.com/v1/gifs/search",
            params={
                "api_key": GIPHY_API_KEY,
                "q": termo,
                "limit": 20,
                "rating": "pg-13",
                "lang": "pt",
            },
            timeout=5,
        )
        resultados = resp.json().get("data", [])
        if not resultados:
            return None
        escolhido = random.choice(resultados)
        return escolhido["images"]["original"]["url"]
    except Exception:
        return None

# Memória e Estruturas
ULTIMA_FOTO_PV = {}


def config_grupo_padrao():
    return {"nome": "", "auto_reacoes": True, "auto_ia": True, "auto_jogos": True}


def carregar_config_grupos():
    try:
        with open(ARQUIVO_CONFIG_GRUPOS, "r", encoding="utf-8") as arquivo:
            bruto = json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        bruto = {}
    convertido = {}
    for chat_id_str, config in bruto.items():
        padrao = config_grupo_padrao()
        padrao.update(config)
        convertido[int(chat_id_str)] = padrao
    return convertido


def salvar_config_grupos(config_grupos):
    bruto = {str(chat_id): config for chat_id, config in config_grupos.items()}
    escrever_json_atomico(ARQUIVO_CONFIG_GRUPOS, bruto)


CONFIG_GRUPOS = carregar_config_grupos()
ARQUIVO_RANKING = os.path.join(os.path.dirname(__file__), "ranking_semanal.json")



def escrever_json_atomico(caminho, dados):
    caminho_temp = f"{caminho}.tmp"
    with open(caminho_temp, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(caminho_temp, caminho)


def carregar_ranking():
    try:
        with open(ARQUIVO_RANKING, "r", encoding="utf-8") as arquivo:
            bruto = json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    # As chaves viram string no JSON; sem essa conversão, o ranking salvo nunca é reencontrado após reiniciar.
    convertido = {}
    for chat_id_str, jogadores in bruto.items():
        convertido[int(chat_id_str)] = {int(user_id_str): dados for user_id_str, dados in jogadores.items()}
    return convertido


def salvar_ranking():
    escrever_json_atomico(ARQUIVO_RANKING, {str(chat_id): {str(uid): dados for uid, dados in jogadores.items()} for chat_id, jogadores in PONTOS_SEMANAL.items()})


PONTOS_SEMANAL = carregar_ranking()


def sincronizar_grupos_conhecidos():
    # O Telegram não deixa o bot listar seus grupos; usamos o ranking (que já tem os chat_ids) para não "esquecer" grupos após reiniciar.
    houve_mudanca = False
    for chat_id in PONTOS_SEMANAL:
        if chat_id in CONFIG_GRUPOS:
            continue
        try:
            chat = bot.get_chat(chat_id)
        except Exception:
            continue
        CONFIG_GRUPOS[chat_id] = config_grupo_padrao()
        CONFIG_GRUPOS[chat_id]["nome"] = chat.title or str(chat_id)
        houve_mudanca = True
    if houve_mudanca:
        salvar_config_grupos(CONFIG_GRUPOS)


sincronizar_grupos_conhecidos()


HISTORICO_ESCOLHAS = {}


def escolher_sem_repetir(chave, opcoes):
    opcoes = list(opcoes)
    historico = HISTORICO_ESCOLHAS.setdefault(chave, deque(maxlen=max(1, len(opcoes) - 1)))
    disponiveis = [opcao for opcao in opcoes if opcao not in historico] or opcoes
    escolhida = random.choice(disponiveis)
    historico.append(escolhida)
    return escolhida


def enviar_sticker_interacao(chat_id):
    if STICKER_IDS and random.random() < 0.55:
        try:
            bot.send_sticker(chat_id, escolher_sem_repetir("sticker_" + str(chat_id), STICKER_IDS))
        except Exception:
            pass

JOGOS_CACA = {}
JOGOS_VELHA = {}
JOGOS_MEMORIA = {}
JOGOS_CRUZADA = {}
JOGOS_PPT = {}
JOGOS_PENALTI = {}
JOGOS_FORCA = {}
JOGOS_QUIZ = {}
JOGOS_PARIMPAR = {}
JOGOS_MOEDA = {}
JOGOS_EMOJI = {}
JOGOS_QUEM = {}
JOGOS_MISTERIO = {}
JOGOS_RAPIDO = {}
JOGOS_VF = {}
JOGOS_OCULTO = {}
JOGOS_CHARADA = {}
JOGOS_STOP = {}
JOGOS_BATATA = {}
JOGOS_DETETIVE = {}
DETETIVE_ACOES = {}
JOGOS_NAVAL = {}
TAMANHO_NAVAL = 5
QTD_NAVIOS_NAVAL = 3

LOCAIS_DETETIVE = ["festa", "praia", "escola", "nave espacial", "hotel", "parque"]

BANCO_QUIZ = [
    {"pergunta": "Qual é o maior planeta do Sistema Solar?", "opcoes": ["Terra", "Júpiter", "Saturno", "Marte"], "certa": 1},
    {"pergunta": "Quantos lados tem um hexágono?", "opcoes": ["5", "6", "7", "8"], "certa": 1},
    {"pergunta": "Qual é a capital da França?", "opcoes": ["Roma", "Madri", "Paris", "Berlim"], "certa": 2},
    {"pergunta": "Quem pintou a Mona Lisa?", "opcoes": ["Van Gogh", "Picasso", "Da Vinci", "Monet"], "certa": 2},
    {"pergunta": "Qual o maior oceano do mundo?", "opcoes": ["Atlântico", "Índico", "Pacífico", "Ártico"], "certa": 2},
    {"pergunta": "Em que ano o homem pisou na Lua pela primeira vez?", "opcoes": ["1965", "1969", "1972", "1959"], "certa": 1},
    {"pergunta": "Qual é o animal terrestre mais rápido do mundo?", "opcoes": ["Leão", "Guepardo", "Cavalo", "Avestruz"], "certa": 1},
    {"pergunta": "Quantas cordas tem um violão comum?", "opcoes": ["4", "5", "6", "7"], "certa": 2},
    {"pergunta": "Qual é o menor país do mundo?", "opcoes": ["Mônaco", "Vaticano", "San Marino", "Liechtenstein"], "certa": 1},
    {"pergunta": "Em que continente fica o Egito?", "opcoes": ["Ásia", "Europa", "África", "Oceania"], "certa": 2},
    {"pergunta": "Qual é o metal que derruba a ponta de um ímã quando entra em contato com ele?", "opcoes": ["Mercúrio", "Ferro", "Ouro", "Alumínio"], "certa": 1},
    {"pergunta": "Qual é a língua mais falada no mundo?", "opcoes": ["Inglês", "Mandarim", "Espanhol", "Hindi"], "certa": 1},
    {"pergunta": "Qual é o país com mais habitantes do mundo?", "opcoes": ["Índia", "China", "Estados Unidos", "Brasil"], "certa": 1},
    {"pergunta": "Qual organela é conhecida como a usina de energia da célula?", "opcoes": ["Ribossomo", "Lisossomo", "Mitocôndria", "Núcleo"], "certa": 2},
    {"pergunta": "Qual destes elementos é um gás nobre?", "opcoes": ["Sódio", "Oxigênio", "Neônio", "Cobre"], "certa": 2},
    {"pergunta": "Qual é o nome do processo que a planta usa para transformar luz em energia?", "opcoes": ["Respiração", "Fotossíntese", "Digestão", "Transpiração"], "certa": 1},
    {"pergunta": "Qual é a maior montanha do mundo?", "opcoes": ["K2", "Monte Fuji", "Monte Everest", "Aconcágua"], "certa": 2},
    {"pergunta": "Em que ano a independência do Brasil foi proclamada?", "opcoes": ["1822", "1808", "1889", "1831"], "certa": 0},
    {"pergunta": "Qual é a pessoa que escreve a música de uma canção?", "opcoes": ["Diretor", "Compositor", "Produtor", "Editor"], "certa": 1},
    {"pergunta": "Qual destes animais vive mais tempo?", "opcoes": ["Tubarão", "Tartaruga", "Golfinho", "Gato"], "certa": 1},
    {"pergunta": "Qual é o instrumento que tem 88 teclas?", "opcoes": ["Violino", "Piano", "Flauta", "Bateria"], "certa": 1},
    {"pergunta": "Qual é o rio mais extenso do mundo?", "opcoes": ["Nilo", "Amazonas", "Mississippi", "Danúbio"], "certa": 1},
    {"pergunta": "Quantos ossos tem o corpo humano adulto, aproximadamente?", "opcoes": ["106", "156", "206", "256"], "certa": 2},
    {"pergunta": "Qual é a moeda oficial do Japão?", "opcoes": ["Won", "Iene", "Yuan", "Rúpia"], "certa": 1},
    {"pergunta": "Quem escreveu Dom Casmurro?", "opcoes": ["José de Alencar", "Machado de Assis", "Monteiro Lobato", "Graciliano Ramos"], "certa": 1},
    {"pergunta": "Qual é o gás mais abundante na atmosfera terrestre?", "opcoes": ["Oxigênio", "Gás carbônico", "Nitrogênio", "Hidrogênio"], "certa": 2},
    {"pergunta": "Qual é o esporte olímpico praticado na água com raquete?", "opcoes": ["Não existe", "Polo aquático", "Vôlei de praia", "Windsurfe"], "certa": 0},
    {"pergunta": "Qual planeta é conhecido como o planeta vermelho?", "opcoes": ["Vênus", "Marte", "Júpiter", "Mercúrio"], "certa": 1},
    {"pergunta": "Quantos minutos tem uma partida oficial de futebol (sem prorrogação)?", "opcoes": ["80", "90", "100", "120"], "certa": 1},
    {"pergunta": "Qual é a capital da Austrália?", "opcoes": ["Sydney", "Melbourne", "Camberra", "Perth"], "certa": 2},
    {"pergunta": "Qual desses é um mamífero marinho?", "opcoes": ["Tubarão", "Baleia", "Polvo", "Água-viva"], "certa": 1},
    {"pergunta": "Quantas cores tem o arco-íris?", "opcoes": ["5", "6", "7", "8"], "certa": 2},
    {"pergunta": "Qual é o metal líquido à temperatura ambiente?", "opcoes": ["Ferro", "Mercúrio", "Chumbo", "Zinco"], "certa": 1},
    {"pergunta": "Qual é o maior deserto do mundo (em área)?", "opcoes": ["Saara", "Antártida", "Gobi", "Atacama"], "certa": 1},
    {"pergunta": "Qual é o órgão responsável por bombear sangue no corpo?", "opcoes": ["Pulmão", "Coração", "Fígado", "Rim"], "certa": 1},
    {"pergunta": "Qual é a capital da Itália?", "opcoes": ["Milão", "Veneza", "Roma", "Nápoles"], "certa": 2},
    {"pergunta": "Quantos jogadores tem um time de vôlei em quadra?", "opcoes": ["5", "6", "7", "8"], "certa": 1},
    {"pergunta": "Qual é o maior mamífero do mundo?", "opcoes": ["Elefante", "Baleia-azul", "Girafa", "Rinoceronte"], "certa": 1},
    {"pergunta": "Em que país fica a Torre Eiffel?", "opcoes": ["Itália", "Espanha", "França", "Alemanha"], "certa": 2},
    {"pergunta": "Qual é o principal ingrediente do guacamole?", "opcoes": ["Tomate", "Abacate", "Pepino", "Cebola"], "certa": 1},
    {"pergunta": "Quantos continentes existem?", "opcoes": ["5", "6", "7", "8"], "certa": 1},
    {"pergunta": "Qual é a única cobra que constrói ninho?", "opcoes": ["Jibóia", "Cobra-rei (naja real)", "Cascavel", "Coral"], "certa": 1},
    {"pergunta": "Qual é a estrutura responsável pela memória genética das células?", "opcoes": ["DNA", "Proteína", "Enzima", "Vitamina"], "certa": 0},
    {"pergunta": "Qual é o país de origem do sushi?", "opcoes": ["China", "Coréia", "Japão", "Tailândia"], "certa": 2},
    {"pergunta": "Quantos jogadores tem um time de basquete em quadra?", "opcoes": ["4", "5", "6", "7"], "certa": 1},
    {"pergunta": "Qual é o metal mais usado em fios elétricos?", "opcoes": ["Ferro", "Cobre", "Chumbo", "Zinco"], "certa": 1},
    {"pergunta": "Qual é a maior ilha do mundo?", "opcoes": ["Madagascar", "Groenlândia", "Bornéu", "Sumatra"], "certa": 1},
    {"pergunta": "Quem foi o primeiro presidente do Brasil?", "opcoes": ["Getúlio Vargas", "Deodoro da Fonseca", "Floriano Peixoto", "Prudente de Morais"], "certa": 1},
]

ULTIMOS_SORTEIOS = {}


def sortear_sem_repetir(chat_id, nome, opcoes):
    opcoes = list(opcoes)
    historico = ULTIMOS_SORTEIOS.setdefault((chat_id, nome), deque(maxlen=max(1, len(opcoes) - 1)))
    disponiveis = [opcao for opcao in opcoes if opcao not in historico] or opcoes
    escolhido = random.choice(disponiveis)
    historico.append(escolhido)
    return escolhido


def sortear_palavras_caca(chat_id):
    pool = POOL_PALAVRAS_CACA
    anterior = ULTIMOS_SORTEIOS.get((chat_id, "caca_ultimo"))
    escolhido = tuple(sorted(random.sample(pool, QTD_PALAVRAS_CACA)))
    tentativas = 0
    while escolhido == anterior and tentativas < 10:
        escolhido = tuple(sorted(random.sample(pool, QTD_PALAVRAS_CACA)))
        tentativas += 1
    ULTIMOS_SORTEIOS[(chat_id, "caca_ultimo")] = escolhido
    return list(escolhido)


def sortear_cruzada(chat_id):
    escolhido = tuple(sorted(random.sample(POOL_PALAVRAS_CRUZADA, 10)))
    anterior = ULTIMOS_SORTEIOS.get((chat_id, "cruzada_ultimo"))
    tentativas = 0
    while escolhido == anterior and tentativas < 10:
        escolhido = tuple(sorted(random.sample(POOL_PALAVRAS_CRUZADA, 10)))
        tentativas += 1
    ULTIMOS_SORTEIOS[(chat_id, "cruzada_ultimo")] = escolhido
    return list(escolhido)

CONSELHOS_DIA = [
    "Respira, organiza uma coisa de cada vez e não deixa a pressa escolher por você.",
    "Uma conversa sincera hoje pode deixar o caminho bem mais leve.",
    "Cuida da sua energia: nem todo convite merece um sim.",
    "Dá uma chance para uma ideia antiga, mas começa pequeno.",
    "Seu descanso também faz parte do plano. Se acolhe um pouquinho hoje.",
]

BANCOS_QUEM_SOU = [
    ("🦁", "Sou um animal conhecido como o rei da selva."),
    ("🍕", "Sou redonda, tenho queijo e faço sucesso nas noites de filme."),
    ("🚀", "Viajo para o espaço e posso levar pessoas para fora da Terra."),
    ("🌈", "Apareço no céu depois da chuva e tenho várias cores."),
    ("🎸", "Tenho cordas e faço música quando alguém toca em mim."),
    ("🐧", "Sou uma ave que não voa, mas adoro nadar em águas geladas."),
    ("🏰", "Sou uma construção antiga com torres e histórias de reis."),
    ("☀️", "Sou a estrela que ilumina o dia e parece o centro da vida por aqui."),
    ("🌙", "Sou a luz que aparece à noite e inspira sonhos."),
    ("🧣", "Sou útil no frio e algumas pessoas me amarram no pescoço."),
    ("📱", "Sou a tela que sempre está na mão das pessoas."),
    ("🧊", "Sou congelado e derreto quando a temperatura sobe."),
    ("🧁", "Sou doce, redondo e muito amado em festas."),
    ("🐠", "Sou peixe e adoro viver em água salgada ou doce."),
    ("🧸", "Tenho cara de fofinho e muitas pessoas me levam para a cama."),
    ("🍉", "Sou uma fruta suculenta e adoro cair no verão."),
    ("🧭", "Ajudo pessoas a não se perderem e sigo apontando o caminho."),
    ("⌚", "Sou usado no pulso e marca o tempo."),
    ("🌽", "Sou um alimento que pode ser quente, assado ou na forma de pipoca."),
    ("🛁", "Sou onde a água cai e a gente vai relaxar."),
    ("🍦", "Sou gelado, doce e derreto rápido no calor."),
    ("🎈", "Sou leve, colorido e voo se me soltarem."),
    ("🕯️", "Dou luz no escuro e derreto enquanto queimo."),
    ("🐢", "Sou lento, tenho casco e vivo muitos anos."),
    ("🐝", "Faço mel e posso picar se me incomodarem."),
    ("🍿", "Estouro no calor e sou clássica no cinema."),
    ("🚂", "Ando sobre trilhos e puxo vagões."),
    ("🎹", "Tenho teclas pretas e brancas e faço música."),
    ("🧦", "Uso no pé, dentro do sapato, e às vezes suma um par."),
    ("🧹", "Tenho cerdas e limpo a bagunça do chão."),
    ("🎧", "Você me coloca no ouvido pra escutar música sem incomodar ninguém."),
    ("🍐", "Sou uma fruta verde ou amarela, com formato diferente e polpa docinha."),
    ("💇", "Sou usado pra pentear o cabelo."),
    ("🌟", "Brilho no céu à noite, sou pequena perto da lua."),
    ("🐭", "Sou pequeno, tenho rabo comprido e adoro queijo."),
    ("🍂", "Sou marrom, caio das árvores no outono."),
    ("👑", "Uso na cabeça e mostro quem é o rei."),
    ("🧪", "Testo coisas em laboratório e às vezes exploto se misturarem errado."),
]

RESPOSTAS_QUEM_SOU = {
    "🦁": {"leao", "leões", "rei da selva"},
    "🍕": {"pizza"},
    "🚀": {"foguete", "nave espacial", "foguetao"},
    "🌈": {"arco iris", "arco-iris", "arcoiris"},
    "🎸": {"violao", "guitarra"},
    "🐧": {"pinguim"},
    "🏰": {"castelo"},
    "☀️": {"sol"},
    "🌙": {"lua"},
    "🧣": {"cachecol", "lenço", "cachecol"},
    "📱": {"celular", "telefone", "smartphone"},
    "🧊": {"gelo", "ice"},
    "🧁": {"bolo", "cupcake", "cup cake"},
    "🐠": {"peixe"},
    "🧸": {"urso", "ursinho"},
    "🍉": {"melancia"},
    "🧭": {"bússola", "bussola"},
    "⌚": {"relógio", "relogio"},
    "🌽": {"milho", "pipoca"},
    "🛁": {"banheiro", "banho", "chuveiro"},
    "🍦": {"sorvete"},
    "🎈": {"balão", "balao"},
    "🕯️": {"vela"},
    "🐢": {"tartaruga"},
    "🐝": {"abelha"},
    "🍿": {"pipoca"},
    "🚂": {"trem", "locomotiva"},
    "🎹": {"piano", "teclado"},
    "🧦": {"meia", "meias"},
    "🧹": {"vassoura"},
    "🎧": {"fone de ouvido", "fone", "fones"},
    "🍐": {"pera", "peras"},
    "💇": {"pente"},
    "🌟": {"estrela"},
    "🐭": {"rato", "camundongo"},
    "🍂": {"folha"},
    "👑": {"coroa"},
    "🧪": {"cientista"},
}

BANCO_MISTERIO = [
    ("Sou redondo, sou doce e as pessoas me levam para festas.", {"bolo", "cupcake", "docinho"}),
    ("Tenho teclas, me ligam e me ouvem quando a pessoa fala comigo.", {"celular", "telefone", "smartphone"}),
    ("Sou um animal de praia, gosto de nadar e tenho barbatanas.", {"golfinho", "delfim"}),
    ("Apareço depois da chuva e mostra vários tons no céu.", {"arco iris", "arco-iris", "arcoiris"}),
    ("Sou pequeno, feminino e faz as pessoas suspirarem com seus afetos.", {"coração", "coracao"}),
    ("Tenho rodas e me aproximo do destino sem perder a direção.", {"carro", "automóvel", "automovel"}),
    ("São meus sonhos, minhas ideias e meu momento de criar mundos imaginários.", {"imaginação", "imaginacao"}),
    ("Sou muito bom em vencer a fome e me transformo em pipoca quando aquecido.", {"milho", "pipoca"}),
    ("Pessoas usam meu som para se organizar, e eu também gosto de música.", {"alarme", "musica"}),
    ("Sou uma luz do dia e a maioria das pessoas me usa para se orientar.", {"sol"}),
    ("Sou verde, moro em árvores e mudo de cor conforme o ambiente.", {"camaleão", "camaleao"}),
    ("Sou usado para escrever e apagar erros com facilidade.", {"lápis", "lapis"}),
    ("Sou um doce gelado que derrete rápido no calor.", {"sorvete"}),
    ("Tenho quatro rodas, motor e levo gente de um lugar a outro.", {"carro", "automóvel", "automovel"}),
    ("Sou uma fruta amarela e curvada que os macacos adoram.", {"banana"}),
    ("Ilumino ambientes escuros e fico pendurada no teto.", {"lâmpada", "lampada"}),
    ("Sou o instrumento de cordas mais tocado em shows de rock.", {"guitarra"}),
    ("Guardo roupas e fico geralmente dentro do quarto.", {"guarda-roupa", "guarda roupa", "armario", "armário"}),
    ("Sou um animal doméstico que mia e adora dormir o dia todo.", {"gato"}),
    ("Sou frio, uso capuz e cachecol pra combater esse tempo.", {"inverno", "frio"}),
    ("Sou um doce brasileiro feito de leite condensado e chocolate granulado.", {"brigadeiro"}),
    ("Tenho quatro patas, late e é o melhor amigo do homem.", {"cachorro", "cão", "cao"}),
    ("Sou um símbolo usado pra representar amor no dia dos namorados.", {"coração", "coracao"}),
    ("Sou uma peça de roupa usada nos pés dentro do sapato.", {"meia", "meias"}),
    ("Sou uma fruta que os macacos adoram e tenho casca amarela.", {"banana"}),
    ("Fico pendurado na parede da sala mostrando fotos da família.", {"quadro", "retrato"}),
]

BANCO_RAPIDO = [
    ("Qual palavra combina com: sol, lua e estrelas?", {"céu", "ceu"}),
    ("Qual palavra combina com: pão, café e leite?", {"café", "cafe", "cafezinho"}),
    ("Qual palavra combina com: futebol, basquete e vôlei?", {"esporte", "esportes"}),
    ("Qual palavra combina com: livro, caderno e lápis?", {"estudo", "escola"}),
    ("Qual palavra combina com: pizza, hambúrguer e sushi?", {"comida", "alimento"}),
    ("Qual palavra combina com: rio, montanha e floresta?", {"natureza"}),
    ("Qual palavra combina com: sonho, sorriso e abraço?", {"amor", "afeto"}),
    ("Qual palavra combina com: teclado, mouse e monitor?", {"computador", "pc"}),
    ("Qual palavra combina com: alegria, música e dança?", {"festa"}),
    ("Qual palavra combina com: chuva, vento e relâmpago?", {"tempestade", "chuva"}),
    ("Qual palavra combina com: praia, sol e biquíni?", {"verão", "verao"}),
    ("Qual palavra combina com: neve, casaco e frio?", {"inverno"}),
    ("Qual palavra combina com: microfone, palco e plateia?", {"show", "apresentação", "apresentacao"}),
    ("Qual palavra combina com: agulha, linha e tecido?", {"costura"}),
    ("Qual palavra combina com: caneta, folha e redação?", {"escrita", "texto"}),
    ("Qual palavra combina com: bola, rede e apito?", {"futebol", "jogo"}),
    ("Qual palavra combina com: forno, massa e fermento?", {"pão", "pao", "bolo"}),
    ("Qual palavra combina com: tela, controle e joystick?", {"videogame", "jogo"}),
    ("Qual palavra combina com: vela, bolo e parabéns?", {"aniversário", "aniversario"}),
    ("Qual palavra combina com: escova, pasta e espelho?", {"banheiro", "higiene"}),
    ("Qual palavra combina com: bola, cesta e quadra?", {"basquete"}),
    ("Qual palavra combina com: linha, agulha e botão?", {"costura"}),
    ("Qual palavra combina com: sabão, água e esponja?", {"limpeza", "banho"}),
    ("Qual palavra combina com: nota, prova e caderno?", {"escola", "estudo"}),
    ("Qual palavra combina com: fogueira, milho e São João?", {"festa junina", "junina"}),
    ("Qual palavra combina com: máscara, fantasia e confete?", {"carnaval"}),
    ("Qual palavra combina com: presente, árvore e papai noel?", {"natal"}),
    ("Qual palavra combina com: caneta, assinatura e papel?", {"documento", "contrato"}),
]

BANCO_VERDADEIRO_FALSO = [
    ("O Brasil fica na América do Sul.", True),
    ("A lua é um planeta.", False),
    ("A água ferve a 100°C ao nível do mar.", True),
    ("O elefante é o maior animal do mundo.", False),
    ("A capital do Japão é Tóquio.", True),
    ("A moeda oficial do Reino Unido é o euro.", False),
    ("O fogo é uma reação química.", True),
    ("A velocidade da luz é maior que a da luz do sol.", False),
    ("O coração bombeia sangue pelo corpo.", True),
    ("O oceano Pacífico é menor que o Atlântico.", False),
    ("A estrela mais próxima da Terra é o Sol.", True),
    ("O diamante é feito de carbono.", True),
    ("O cavalo consegue voar.", False),
    ("A caneta é feita de algodão.", False),
    ("O universo é infinito.", False),
    ("O código morse foi usado em rádio e telégrafo.", True),
    ("O Brasil já foi sede de duas Copas do Mundo de futebol.", True),
    ("O corpo humano tem apenas um pulmão.", False),
    ("A Grande Muralha da China é visível a olho nu do espaço.", False),
    ("O mel nunca estraga se guardado corretamente.", True),
    ("O polvo tem três corações.", True),
    ("A Torre Eiffel fica em Londres.", False),
    ("O som viaja mais rápido na água do que no ar.", True),
    ("As formigas conseguem carregar objetos muito mais pesados que elas.", True),
    ("O Sol é uma estrela.", True),
    ("O camaleão muda de cor apenas para se camuflar.", False),
    ("A girafa dorme em pé na maior parte do tempo.", True),
    ("O Monte Everest fica na América do Sul.", False),
    ("O corpo humano é composto majoritariamente de água.", True),
    ("Os pinguins vivem apenas no polo norte.", False),
    ("A Amazônia é a maior floresta tropical do mundo.", True),
    ("O relâmpago é mais quente que a superfície do Sol.", True),
    ("Todos os planetas do Sistema Solar têm anéis.", False),
    ("O chocolate amargo tem mais cacau que o chocolate ao leite.", True),
]

BANCO_OCULTO = [
    ("Sou redondo, gero energia quando o sol me bate e ainda deixo o mundo mais bonito.", "sol"),
    ("Pessoas usam meu som para se organizar e eu também gosto de música.", "alarme"),
    ("Sou doce, redondo e muito pedido em festas.", "bolo"),
    ("Tenho tela, bateria e consigo me tornar o melhor amigo da pessoa.", "celular"),
    ("Sou uma fruta com muita água e me encontro fresquinha no verão.", "melancia"),
    ("Pessoas usam o meu brilho para iluminar a casa à noite.", "lampada"),
    ("Fico no pulso da pessoa e marca o tempo.", "relogio"),
    ("Sou a maior estrela da manhã, também conhecida como o astro rei.", "sol"),
    ("Tenho asas e sou um dos símbolos mais famosos da paz.", "pomba"),
    ("Sou usada para mandar mensagens e brincar no celular.", "mensagem"),
    ("Sou o líquido essencial pra vida e cubro a maior parte do planeta.", "agua"),
    ("Sou felino, ronrono e adoro cochilar no sofá.", "gato"),
    ("Sou usado pra cortar papel e tenho duas lâminas.", "tesoura"),
    ("Guardo dinheiro e fico dentro da bolsa ou bolso.", "carteira"),
    ("Sou um doce que derrete na boca e vem em barra ou bombom.", "chocolate"),
    ("Fico pendurado na parede e mostro as horas com ponteiros.", "relogio"),
    ("Sou uma fruta cítrica e azeda, boa pra suco.", "limao"),
    ("Sou um objeto que ilumina o caminho à noite quando alguém anda na rua.", "lanterna"),
    ("Fico no céu à noite e às vezes tenho fases: cheia, nova, minguante.", "lua"),
    ("Sou um instrumento usado por dentistas e também em oficinas pra apertar parafuso.", "chave"),
    ("Sou uma fruta pequena, vermelha e ácida usada em geleias e tortas.", "morango"),
    ("Fico no banheiro e ajudo a lavar as mãos.", "sabonete"),
    ("Sou usado pra proteger do sol e da chuva quando aberto.", "guarda-chuva"),
    ("Sou um objeto usado pra ver as horas quando está no pulso.", "relogio"),
]


def normalizar_resposta(texto):
    texto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(letra for letra in texto if unicodedata.category(letra) != "Mn").strip()


def montar_horoscopo(signo, previsao):
    fechamentos = [
        "Vai com calma, confia no seu caminho e aproveita o dia! 💗",
        "A Santos avisou: fica de olho nas oportunidades e não perde a leveza! ✨",
        "Salva essa mensagem e marcha, porque o universo está conversando com você! 🌙",
        "Agora é com você: atitude, coração tranquilo e uma pitada de ousadia! 💅",
    ]
    return (
        "🔮 <b>HORÓSCOPO DO DIA</b> 🔮\n"
        "━━━━━━━━━━━━━━\n"
        f"✨ <b>Signo:</b> {signo.title()}\n\n"
        "🌟 <b>Previsão de hoje</b>\n"
        f"{previsao}\n\n"
        f"💌 <b>Mensagem da Santos</b>\n{escolher_sem_repetir('horoscopo_fechamento', fechamentos)}\n"
        "━━━━━━━━━━━━━━"
    )

BANCOS_EMOJI = [
    ("👑 + 🦁", "rei leao"),
    ("🌧️ + 🌈", "arco iris"),
    ("🍎 + 🥧", "torta de maca"),
    ("🎤 + 🎶", "cantor"),
    ("🍫 + 😋", "chocolate"),
    ("🏠 + 👻", "casa assombrada"),
    ("🔥 + 🐉", "dragao de fogo"),
    ("🌞 + 🕶️", "dia de sol"),
    ("🐝 + 🍯", "abelha e mel"),
    ("📚 + 🎓", "estudante"),
    ("🐦 + 🎤", "passaro cantor"),
    ("🌊 + 🏄", "surf"),
    ("🍕 + 🌙", "pizza a noite"),
    ("💤 + 🛏️", "dormir"),
    ("🎂 + 🕯️", "aniversario"),
    ("🚗 + 💨", "carro rapido"),
    ("🐱 + 🐟", "gato e peixe"),
    ("🌙 + ⭐", "noite estrelada"),
    ("🎮 + 🏆", "campeao de jogo"),
    ("🍲 + 🔥", "comida quente"),
    ("🐶 + 🦴", "esqueleto de cachorro"),
    ("🍂 + 🍂", "outono"),
    ("👰 + 💒", "casamento"),
    ("🏖️ + 🌞", "praia de dia"),
    ("🦷 + 😬", "dor de dente"),
    ("📦 + 🚚", "entrega"),
]

BANCO_CHARADAS = [
    ("O que é, o que é: quanto mais se tira, maior fica?", {"buraco"}),
    ("O que é, o que é: tem cidade, tem casa, mas não tem gente?", {"mapa"}),
    ("O que é, o que é: fica mais molhado quanto mais seca?", {"toalha"}),
    ("O que é, o que é: tem dentes mas não morde?", {"pente", "garfo", "serra", "zíper", "ziper"}),
    ("O que é, o que é: voa sem asas e chora sem olhos?", {"nuvem"}),
    ("O que é, o que é: tem coroa mas não é rei, tem espinhos mas não é rosa?", {"abacaxi"}),
    ("O que é, o que é: corre mas nunca anda, tem boca mas nunca fala, tem cama mas nunca dorme?", {"rio"}),
    ("O que é, o que é: entra e sai da água mas nunca se molha?", {"sombra"}),
    ("O que é, o que é: tem olhos e não vê?", {"batata"}),
    ("O que é, o que é: tem pescoço mas não tem cabeça, tem mangas mas não tem braço?", {"camisa"}),
    ("O que é, o que é: nasce grande e morre pequena?", {"vela"}),
    ("O que é, o que é: tem uma perna só e fica de pé o dia todo?", {"guarda-chuva", "guarda chuva", "cogumelo", "mesa"}),
    ("O que é, o que é: cai em pé e corre deitado?", {"chuva"}),
    ("O que é, o que é: quanto mais se enche, mais leve fica?", {"balão", "balao"}),
    ("O que é, o que é: fala todas as línguas do mundo?", {"eco"}),
    ("O que é, o que é: tem cabeça, tem dente, mas não é gente?", {"alho"}),
    ("O que é, o que é: quanto mais quente fica, mais gente pede?", {"pão", "pao", "café", "cafe"}),
    ("O que é, o que é: anda o dia todo e no fim volta pro mesmo lugar?", {"relógio", "relogio", "ponteiro"}),
    ("O que é, o que é: quanto mais você usa, mais afiado fica?", {"lápis", "lapis"}),
    ("O que é, o que é: sobe mas nunca desce?", {"idade"}),
    ("O que é, o que é: todo mundo tem e ninguém pode emprestar?", {"nome"}),
    ("O que é, o que é: quanto mais alto, menos pesa?", {"idade"}),
    ("O que é, o que é: enche a casa mas não ocupa espaço?", {"luz"}),
    ("O que é, o que é: tem coração mas não sente nada?", {"alcachofra", "árvore", "arvore", "repolho"}),
    ("O que é, o que é: fica na ponta da língua mas não é palavra?", {"gosto", "sabor"}),
    ("O que é, o que é: nasce na água, mas se ficar na água morre?", {"chuva", "onda"}),
    ("O que é, o que é: quanto mais cresce, menos se vê?", {"escuridão", "escuridao", "noite"}),
    ("O que é, o que é: tem cara mas não tem rosto, tem números mas não conta sozinho?", {"relógio", "relogio"}),
    ("O que é, o que é: sobe quando a chuva cai e desce quando faz sol?", {"guarda-chuva", "guarda chuva"}),
    ("O que é, o que é: quebra sem cair e cai sem quebrar?", {"dia", "noite", "recorde"}),
]

CATEGORIAS_FORCA = {
    "animais": ["CACHORRO", "GATO", "ELEFANTE", "GIRAFA", "TARTARUGA", "CANGURU", "BORBOLETA"],
    "comidas": ["CHOCOLATE", "PIPOCA", "LARANJA", "MELANCIA", "BISCOITO", "ABACATE", "SORVETE"],
    "filmes": ["AVENTURA", "FANTASIA", "COMEDIA", "DRAGAO", "UNIVERSO", "TESOURO", "CASTELO"],
    "musica": ["GUITARRA", "CANTORA", "MELODIA", "RITMO", "FESTIVAL", "MICROFONE", "HARMONIA"],
    "natureza": ["FLORESTA", "MONTANHA", "OCEANO", "GIRASSOL", "PLANETA", "ESTRELA", "PRIMAVERA"],
}

# Trava de jogo por grupo: garante que só 1 jogo rode por vez em cada chat,
# evitando que um jogo "engula" as respostas de outro.
JOGO_ATIVO = {}


def jogo_ocupado(chat_id, novo_jogo):
    atual = JOGO_ATIVO.get(chat_id)
    return atual is not None and atual != novo_jogo


def travar_jogo(chat_id, jogo):
    JOGO_ATIVO[chat_id] = jogo


def liberar_jogo(chat_id, jogo):
    if JOGO_ATIVO.get(chat_id) == jogo:
        JOGO_ATIVO.pop(chat_id, None)


def aviso_jogo_ocupado(mensagem, chat_id):
    atual = JOGO_ATIVO.get(chat_id, "desconhecido")
    texto = f"⚠️ Já tem um jogo de <b>{atual.upper()}</b> rolando aqui! Espere terminar ou use <code>.load{atual}</code> pra resetar."
    try:
        bot.reply_to(mensagem, texto, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, texto, parse_mode="HTML")


def iniciar_quiz(chat_id):
    travar_jogo(chat_id, "quiz")
    pergunta = sortear_sem_repetir(chat_id, "quiz", BANCO_QUIZ)
    JOGOS_QUIZ[chat_id] = {"pergunta": pergunta}
    emojis_num = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    markup = InlineKeyboardMarkup(row_width=1)
    for i, opc in enumerate(pergunta["opcoes"]):
        markup.add(InlineKeyboardButton(f"{emojis_num[i]} {opc}", callback_data=f"quiz_{i}"))
    msg = bot.send_message(chat_id, f"🧠 <b>QUIZ DA SANTOS</b> 🧠\n\n❓ {pergunta['pergunta']}\n\n<i>Quem acertar primeiro leva os pontos!</i>", reply_markup=markup, parse_mode="HTML")
    JOGOS_QUIZ[chat_id]["msg_id"] = msg.message_id


def iniciar_misterio(chat_id):
    pista, respostas = escolher_sem_repetir("misterio", BANCO_MISTERIO)
    JOGOS_MISTERIO[chat_id] = {"respostas": {normalizar_resposta(r) for r in respostas}, "pista": pista}
    travar_jogo(chat_id, "misterio")
    bot.send_message(chat_id, f"🎯 <b>MISTÉRIO DA SANTOS</b> 🎯\n\n💡 {pista}\n\nDigite sua resposta! (+20 pts)", parse_mode="HTML")


def iniciar_rapido(chat_id):
    pergunta, respostas = escolher_sem_repetir("rapido", BANCO_RAPIDO)
    JOGOS_RAPIDO[chat_id] = {"pergunta": pergunta, "respostas": {normalizar_resposta(r) for r in respostas}}
    travar_jogo(chat_id, "rapido")
    bot.send_message(chat_id, f"⚡ <b>RÁPIDO DA SANTOS</b> ⚡\n\n{pergunta}\n\nQuem acertar primeiro leva +15 pts!", parse_mode="HTML")


def iniciar_vf(chat_id):
    frase, resposta = escolher_sem_repetir("vf", BANCO_VERDADEIRO_FALSO)
    JOGOS_VF[chat_id] = {"frase": frase, "resposta": resposta}
    travar_jogo(chat_id, "vf")
    bot.send_message(chat_id, f"✅ <b>VERDADEIRO OU FALSO</b> ✅\n\n{frase}\n\nResponda com: <b>verdadeiro</b> ou <b>falso</b> (+15 pts)", parse_mode="HTML")


def iniciar_oculto(chat_id):
    pista, resposta = escolher_sem_repetir("oculto", BANCO_OCULTO)
    JOGOS_OCULTO[chat_id] = {"pista": pista, "resposta": normalizar_resposta(resposta)}
    travar_jogo(chat_id, "oculto")
    bot.send_message(chat_id, f"🕵️ <b>PALAVRA OCULTA</b> 🕵️\n\n🔍 {pista}\n\nDigite a resposta! (+20 pts)", parse_mode="HTML")


def iniciar_charada(chat_id):
    charada, respostas = escolher_sem_repetir("charada", BANCO_CHARADAS)
    JOGOS_CHARADA[chat_id] = {"charada": charada, "respostas": {normalizar_resposta(r) for r in respostas}}
    travar_jogo(chat_id, "charada")
    bot.send_message(chat_id, f"🧩 <b>CHARADA DA SANTOS</b> 🧩\n\n{charada}\n\nDigite sua resposta! (+20 pts)", parse_mode="HTML")


def iniciar_emoji(chat_id):
    desafio, resposta = escolher_sem_repetir("desafio_emoji", BANCOS_EMOJI)
    JOGOS_EMOJI[chat_id] = {"resposta": resposta, "desafio": desafio}
    travar_jogo(chat_id, "emoji")
    bot.send_message(chat_id, f"🧩 <b>ADIVINHE O EMOJI</b> 🧩\n\nQue palavra ou expressão estes emojis representam?\n\n<b>{desafio}</b>\n\n<i>Dica: responda de forma simples, como “arco iris” ou “dragao de fogo”.</i>\n\nDigite sua resposta! (+15 pts)", parse_mode="HTML")


def iniciar_quem(chat_id):
    personagem, dica = escolher_sem_repetir("desafio_quem", BANCOS_QUEM_SOU)
    JOGOS_QUEM[chat_id] = {"resposta": personagem, "dica": dica, "tentativas": 0}
    travar_jogo(chat_id, "quem")
    bot.send_message(chat_id, f"🎭 <b>QUEM SOU EU?</b> 🎭\n\n💡 Dica: {dica}\n\nDigite seu palpite! (+15 pts)", parse_mode="HTML")


def iniciar_stop(chat_id):
    letra = random.choice("ABCDEFGHIJKLMNOPRSTUV")
    travar_jogo(chat_id, "stop")
    JOGOS_STOP[chat_id] = {"letra": letra, "status": "ativo"}
    bot.send_message(chat_id, f"🛑 <b>STOP!</b> 🛑\n\nA letra é: <b>{letra}</b>\n\nResponda em uma linha:\n<b>nome, animal, comida, objeto</b>\n\nA primeira ficha completa leva +25 pts!", parse_mode="HTML")


# Jogos leves o suficiente (sem lobby/participantes) para a Santos soltar sozinha.
JOGOS_AUTOMATICOS = [
    ("quiz", iniciar_quiz),
    ("misterio", iniciar_misterio),
    ("rapido", iniciar_rapido),
    ("vf", iniciar_vf),
    ("oculto", iniciar_oculto),
    ("charada", iniciar_charada),
    ("emoji", iniciar_emoji),
    ("quem", iniciar_quem),
    ("stop", iniciar_stop),
]

CHAMADAS_JOGO_AUTOMATICO = [
    "🎉 A Santos apareceu com um desafio de surpresa! Bora ganhar ponto fácil:",
    "👀 Ninguém pediu, mas a Santos quis soltar um joguinho aqui:",
    "✨ Intervalo pra resenha! A Santos trouxe um desafio rapidinho:",
    "🎲 A Santos tava entediada e resolveu criar uma atividade:",
]


def rotina_jogos_automaticos():
    while True:
        time.sleep(random.randint(1200, 2700))
        grupos_livres = [
            chat_id for chat_id in list(CONFIG_GRUPOS.keys())
            if not JOGO_ATIVO.get(chat_id) and CONFIG_GRUPOS.get(chat_id, {}).get("auto_jogos", True)
        ]
        if not grupos_livres:
            continue
        chat_id = random.choice(grupos_livres)
        nome_jogo, iniciar = random.choice(JOGOS_AUTOMATICOS)
        try:
            bot.send_message(chat_id, random.choice(CHAMADAS_JOGO_AUTOMATICO))
            iniciar(chat_id)
        except Exception as erro:
            print(f"Erro ao iniciar jogo automático ({nome_jogo}): {type(erro).__name__}: {erro}")
            liberar_jogo(chat_id, nome_jogo)


ARQUIVO_GATILHOS = os.path.join(os.path.dirname(__file__), "gatilhos_plataformas.json")


def carregar_gatilhos():
    try:
        with open(ARQUIVO_GATILHOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_gatilhos(dados):
    escrever_json_atomico(ARQUIVO_GATILHOS, dados)


GATILHOS_PLATAFORMAS = carregar_gatilhos()

FRASES_PLATAFORMA = [
    "Visão, tropa! Cola na {g}, minhas lindas 💅✨:",
    "Anotou a visão? Só vai na {g} que é ➔",
    "O fluxo tá pago, broca a {g} aí, família! 🚀",
    "Papo reto, quer faturar? Encosta na {g}:",
    "Menos neurose e mais resultado na {g}:",
    "Aposta certa, visão braba na {g}:",
    "Marcha que o sistema é brabo na {g}! 🔥",
    "Gente, eu vim aqui só pra avisar mesmo 💗 a {g} tá braba hoje:",
    "Psiu, chega mais 👀 a {g} tá liberada:",
    "Confia na tia Santos 💋 e cola na {g}:",
    "Sextou o coração na {g}? Bora! 🎀",
    "Não fala que eu não avisei, hein! A {g} tá voando 🕊️:",
]

RESPOSTAS_SAUDACAO = {
    "BOM DIA": [
        "Bom diaaa, tropa! ☀️ A Santos já acordou no pique, visão? Que hoje renda coisa boa 💗",
        "Bom dia, minhas lindas! 🌸 Café na mão, sorriso no rosto e marcha no dia!",
        "Bom dia, família! ✨ Quem chegou cedo hoje tá com a visão desbloqueada 😌",
        "Acorda, tropa! ☀️ Bom dia pra quem é de bom coração e gosta de uma resenha!",
        "Bom diaaa! 💅 Hoje eu tô sentindo que vem notícia boa, só não vale ficar parado!",
        "Bom dia, povo bonito! ☀️ Quem dormiu perdeu a fofoca, mas ainda dá tempo de recuperar!",
        "A Santos chegou cedinho, viu? 🌸 Bom dia pra quem tá on e pra quem ainda tá carregando!",
        "Bom diaaa! ☕ Já tomou café ou ainda está funcionando no modo economia de bateria?",
        "Salve, tropa! ☀️ Que o dia venha manso, mas com umas surpresas boas no caminho!",
    ],
    "BOA TARDE": [
        "Boa tarde, meu povo! 🌺 A resenha tá só começando, bora manter o astral lá em cima!",
        "Boa tarde, tropa! 😎 Já deu aquela respirada? Então marcha que o dia ainda tem chão!",
        "Boa tarde, minhas divas! 💗 Passando pra espalhar energia boa e uma pitada de ousadia!",
        "Boa tarde, família! ✨ Quem tá na atividade manda um coração pra Santos!",
        "Boa tarde, meu povo! 😎 O dia já andou, mas a resenha ainda tem muita estrada!",
        "Boa tarde! 🌺 Vim conferir se essa tropa está trabalhando ou só fingindo bonito no grupo!",
    ],
    "BOA NOITE": [
        "Boa noite, gente linda! 🌙 Descansem porque amanhã tem mais resenha e mais visão!",
        "Boa noite, tropa! 💕 Que o sono seja leve e os sonhos venham daquele jeitinho!",
        "Boa noite, minhas lindas! ✨ Fechem o dia com o coração tranquilo, vocês merecem!",
        "A Santos deseja uma noite braba de paz! 🌙 Amanhã a gente volta no pique!",
        "Boa noite, tropa! 🌙 Recarreguem a bateria social porque amanhã tem mais conversa!",
        "Boa noite, meus amores! 💗 Quem for dormir, dorme. Quem ficar, segura a resenha baixinho!",
    ],
    "OI SANTOS": [
        "Oii, meu bem! 💗 Cheguei na área, conta a fofoca e não economiza na resenha!",
        "Opa, tropa! 😎 A Santos tá on e pronta pra causar uma interaçãozinha!",
        "Oii! 🌸 Chamou, eu vim. Qual vai ser a missão de hoje?",
        "Opa, chamou a dona da resenha? 😌 Tô aqui, fala comigo!",
        "Oii, criatura! 💗 Cheguei mais rápido que notícia boa no grupo!",
    ],
}

LISTA_SIGNOS_VALIDOS = [
    "ARIES", "TOURO", "GEMEOS", "CANCER", "LEAO", "VIRGEM",
    "LIBRA", "ESCORPIAO", "SAGITARIO", "CAPRICORNIO", "AQUARIO", "PEIXES",
]

BANCO_CRUZADAS = [
    ["LIMITE", "INTEGRIDADE", "VIOLETA", "RITUAIS", "INTERCAMBIAR", "AUMENTAR", "JUDICIAL", "CONVERSAR", "AMARFANHAR", "REPARAR"],
    ["SANTOS", "RESENHA", "MANDRAKE", "CASSINO", "TIGRINHO", "FUTEBOL", "AMOR", "SORTE", "PIX", "VICTORY"],
]

BANCO_TEMAS_CACA = [
    ["PIX", "LUCRO", "SORTE", "BANCA"],
    ["CASSINO", "GIRO", "VIP", "PREMIO"],
    ["FUTEBOL", "GOL", "APOSTA", "CHAMPION"],
    ["TIGRINHO", "FORTUNA", "OURO", "MOEDA"],
    ["MENTE", "FOCO", "VITORIA", "CHEF"],
    ["DRAGAO", "BONUS", "FESTA", "SALDO"],
]

PALAVRAS_EXTRAS = [
    "ABACATE", "ABAJUR", "ABRIGO", "ACEROLA", "ACORDO", "ADEGA", "AEROPORTO", "AGENDA",
    "ALEGRIA", "ALGODAO", "ALMOCO", "AMIZADE", "AMORA", "ANIMAL", "ANEL", "ANJO",
    "APITO", "ARCO", "AREIA", "ARROZ", "ARTISTA", "ATITUDE", "AVENTURA", "AZEITONA",
    "BALEIA", "BANDEIRA", "BARCO", "BEBIDA", "BEIJO", "BICICLETA", "BISCOITO", "BOLICHE",
    "BRILHO", "BRINCADEIRA", "CAMINHO", "CANETA", "CANGURU", "CARTA", "CASTELO", "CEREJA",
    "CHOCOLATE", "CHUVA", "CINEMA", "CIRCO", "CIDADE", "COELHO", "COLEGA", "COMETA",
    "CORAGEM", "COSTELA", "CRIATIVO", "DANCA", "DESAFIO", "DESENHO", "DESTINO", "DIAMANTE",
    "DINOSSAURO", "DOMINGO", "ELEFANTE", "ENERGIA", "ESCOLA", "ESPACO", "ESTRELA", "FAMILIA",
    "FANTASIA", "FLORESTA", "FOGUETE", "FORMIGA", "FOTOGRAFIA", "FRUTA", "GIRASSOL", "GUITARRA",
    "HARMONIA", "HISTORIA", "IMAGINACAO", "JANELA", "JARDIM", "JORNAL", "LAGOA", "LARANJA",
    "LEITURA", "LIBERDADE", "LIVRO", "LUAR", "MAGIA", "MARMELADA", "MELANCIA", "MEMORIA",
    "MONTANHA", "MUSICA", "NATUREZA", "NUVEM", "OCEANO", "ONDA", "ORIGAMI", "PANDA",
    "PASSARO", "PIPOCA", "PLANETA", "PRESENTE", "PRIMAVERA", "RAIO", "RECEITA", "RISADA",
    "ROSA", "SABEDORIA", "SORVETE", "TARTARUGA", "TESOURO", "TRILHA", "UNIVERSO", "VIAGEM",
    "VIOLETA", "VITORIA", "XADREZ", "ZEBRA",
]

# Igual ao Bil: só entram palavras com 4+ letras no caça-palavras
POOL_PALAVRAS_CACA = sorted({p for tema in BANCO_TEMAS_CACA for p in tema if len(p) >= 4} | set(PALAVRAS_EXTRAS))
POOL_PALAVRAS_CRUZADA = sorted(set(PALAVRAS_EXTRAS + [p for tema in BANCO_CRUZADAS for p in tema if len(p) >= 4]))
QTD_PALAVRAS_CACA = 5


def adicionar_pontos(chat_id, user_id, nome, quantidade=10):
    if eh_admin_por_id(chat_id, user_id):
        return
    if chat_id not in PONTOS_SEMANAL:
        PONTOS_SEMANAL[chat_id] = {}
    if user_id not in PONTOS_SEMANAL[chat_id]:
        PONTOS_SEMANAL[chat_id][user_id] = {"nome": nome, "pontos": 0, "interacoes": 0}
    PONTOS_SEMANAL[chat_id][user_id].setdefault("interacoes", 0)
    PONTOS_SEMANAL[chat_id][user_id]["pontos"] += quantidade
    PONTOS_SEMANAL[chat_id][user_id]["nome"] = nome
    salvar_ranking()


def registrar_interacao(chat_id, user_id, nome):
    if eh_admin_por_id(chat_id, user_id):
        return
    if chat_id not in PONTOS_SEMANAL:
        PONTOS_SEMANAL[chat_id] = {}
    if user_id not in PONTOS_SEMANAL[chat_id]:
        PONTOS_SEMANAL[chat_id][user_id] = {"nome": nome, "pontos": 0, "interacoes": 0}
    jogador = PONTOS_SEMANAL[chat_id][user_id]
    jogador["nome"] = nome
    jogador["interacoes"] = jogador.get("interacoes", 0) + 1
    jogador["pontos"] += 5
    salvar_ranking()


ADMIN_CACHE = {}
ADMIN_CACHE_TTL = 300


def eh_admin_por_id(chat_id, user_id):
    chave = (chat_id, user_id)
    agora = time.time()
    em_cache = ADMIN_CACHE.get(chave)
    if em_cache and agora - em_cache[1] < ADMIN_CACHE_TTL:
        return em_cache[0]
    try:
        membro = bot.get_chat_member(chat_id, user_id)
        resultado = membro.status in ("administrator", "creator")
    except Exception:
        resultado = False
    ADMIN_CACHE[chave] = (resultado, agora)
    return resultado


def administrador_do_grupo(mensagem):
    return eh_admin_por_id(mensagem.chat.id, mensagem.from_user.id)


def criar_mencoes_grupo(chat_id):
    participantes = list(PONTOS_SEMANAL.get(chat_id, {}).items())[:50]
    return " ".join(
        f'<a href="tg://user?id={user_id}">{html.escape(dados["nome"])}</a>'
        for user_id, dados in participantes
    )


def gerar_texto_top(chat_id):
    if chat_id not in PONTOS_SEMANAL or not PONTOS_SEMANAL[chat_id]:
        return "🏆 <b>RANKING SEMANAL DA SANTOS</b> 🏆\n\nNinguém pontuou essa semana ainda!"
    ranking = sorted(PONTOS_SEMANAL[chat_id].values(), key=lambda x: x["pontos"], reverse=True)
    medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    texto = "🏆 <b>RANKING SEMANAL DE PONTUAÇÃO</b> 🏆\n\n"
    for idx, jogador in enumerate(ranking[:10]):
        icone = medalhas[idx] if idx < len(medalhas) else "🎖️"
        bonus = jogador.get("interacoes", 0) * 5
        texto += f"{icone} <b>{jogador['nome']}</b> — <code>{jogador['pontos']} pts</code> <i>(+{bonus} interação)</i>\n"
    texto += "\n💬 Cada mensagem vale 5 pts de bônus de interação.\n✨ <i>Zera automaticamente todo domingo às 17h!</i>"
    return texto


def rotina_ranking_automatico():
    while True:
        agora = datetime.datetime.now()
        if agora.weekday() == 6 and agora.hour == 17 and agora.minute == 0:
            for chat_id in list(CONFIG_GRUPOS.keys()):
                try:
                    texto_ranking = gerar_texto_top(chat_id)
                    aviso = "⏰ <b>FECHAMENTO DA SEMANA!</b> O ranking final de domingo chegou:\n\n" + texto_ranking
                    bot.send_message(chat_id, aviso, parse_mode="HTML")
                    PONTOS_SEMANAL[chat_id] = {}
                    salvar_ranking()
                except Exception as e:
                    print(f"Erro ranking automático: {e}")
            time.sleep(61)
        else:
            time.sleep(30)


threading.Thread(target=rotina_ranking_automatico, daemon=True).start()


def gerar_imagem_forca(erros):
    img = Image.new('RGB', (400, 400), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    draw.line([50, 350, 200, 350], fill=(255, 179, 217), width=6)
    draw.line([100, 50, 100, 350], fill=(255, 179, 217), width=6)
    draw.line([100, 50, 250, 50], fill=(255, 179, 217), width=6)
    draw.line([250, 50, 250, 100], fill=(255, 179, 217), width=4)

    if erros >= 1: draw.ellipse([225, 100, 275, 150], outline=(255, 224, 240), width=4)
    if erros >= 2: draw.line([250, 150, 250, 250], fill=(255, 224, 240), width=4)
    if erros >= 3: draw.line([250, 180, 210, 220], fill=(255, 224, 240), width=4)
    if erros >= 4: draw.line([250, 180, 290, 220], fill=(255, 224, 240), width=4)
    if erros >= 5: draw.line([250, 250, 210, 310], fill=(255, 224, 240), width=4)
    if erros >= 6: draw.line([250, 250, 290, 310], fill=(255, 224, 240), width=4)

    bio = io.BytesIO()
    bio.name = 'forca.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_imagem_velha_lobby():
    img = Image.new('RGB', (500, 300), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 28)
        font_sub = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    draw.rectangle([180, 80, 320, 220], outline=(255, 122, 190), width=4)
    draw.line([226, 80, 226, 220], fill=(255, 122, 190), width=3)
    draw.line([273, 80, 273, 220], fill=(255, 122, 190), width=3)
    draw.line([180, 126, 320, 126], fill=(255, 122, 190), width=3)
    draw.line([180, 173, 320, 173], fill=(255, 122, 190), width=3)
    draw.text((150, 30), "JOGO DA VELHA", fill=(255, 244, 250), font=font_titulo)
    draw.text((155, 250), "Valendo 25 pontos!", fill=(255, 205, 90), font=font_sub)

    bio = io.BytesIO()
    bio.name = 'velha.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def _rosto(draw, cx, cy, r, expressao, cor_pele=(255, 219, 200), cor_traco=(60, 30, 50)):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=cor_pele, outline=cor_traco, width=2)
    olho_y = cy - r * 0.15
    if expressao == "triste":
        draw.line([cx - r * 0.35, olho_y, cx - r * 0.15, olho_y + 6], fill=cor_traco, width=3)
        draw.line([cx + r * 0.15, olho_y + 6, cx + r * 0.35, olho_y], fill=cor_traco, width=3)
        draw.arc([cx - r * 0.3, cy + r * 0.15, cx + r * 0.3, cy + r * 0.5], start=200, end=340, fill=cor_traco, width=3)
        draw.ellipse([cx + r * 0.25, cy + r * 0.05, cx + r * 0.35, cy + r * 0.3], fill=(120, 190, 255))
    elif expressao == "rindo":
        draw.ellipse([cx - r * 0.3, olho_y - 4, cx - r * 0.15, olho_y + 4], fill=cor_traco)
        draw.ellipse([cx + r * 0.15, olho_y - 4, cx + r * 0.3, olho_y + 4], fill=cor_traco)
        draw.arc([cx - r * 0.35, cy, cx + r * 0.35, cy + r * 0.5], start=0, end=180, fill=cor_traco, width=4)
    else:  # feliz
        draw.ellipse([cx - r * 0.3, olho_y - 4, cx - r * 0.15, olho_y + 4], fill=cor_traco)
        draw.ellipse([cx + r * 0.15, olho_y - 4, cx + r * 0.3, olho_y + 4], fill=cor_traco)
        draw.arc([cx - r * 0.25, cy + r * 0.05, cx + r * 0.25, cy + r * 0.3], start=0, end=180, fill=cor_traco, width=3)


def _vovo(draw, cx, cy, expressao, cor_vestido, apontando=False, abracando=False):
    # bolinho de cabelo + rosto + vestido triangular (silhueta de "vovó" para o jogo da velha)
    draw.ellipse([cx - 14, cy - 78, cx + 14, cy - 58], fill=(230, 230, 230), outline=(90, 60, 90), width=2)
    _rosto(draw, cx, cy - 45, 26, expressao)
    draw.polygon([(cx - 40, cy + 60), (cx + 40, cy + 60), (cx + 20, cy - 15), (cx - 20, cy - 15)], fill=cor_vestido, outline=(60, 30, 50))
    if abracando:
        draw.arc([cx - 55, cy - 30, cx + 55, cy + 40], start=200, end=340, fill=cor_vestido, width=10)
    elif apontando:
        draw.line([cx + 20, cy - 5, cx + 65, cy - 35], fill=cor_vestido, width=10)
    else:
        draw.line([cx - 20, cy - 5, cx - 45, cy + 15], fill=cor_vestido, width=10)
        draw.line([cx + 20, cy - 5, cx + 45, cy + 15], fill=cor_vestido, width=10)


def gerar_imagem_velha_vitoria(vencedor, perdedor):
    img = Image.new('RGB', (500, 320), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 24)
        font_nome = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_nome = ImageFont.load_default()

    draw.text((110, 20), "🏆 VITÓRIA NA VELHA! 🏆", fill=(255, 205, 90), font=font_titulo)
    _vovo(draw, 150, 190, "rindo", (255, 105, 180), apontando=True)
    _vovo(draw, 350, 190, "triste", (150, 110, 200))
    draw.text((70, 270), vencedor[:16], fill=(255, 244, 250), font=font_nome)
    draw.text((270, 270), perdedor[:16], fill=(200, 170, 210), font=font_nome)
    draw.text((300, 130), "kkkkk 😹", fill=(255, 244, 250), font=font_nome)

    bio = io.BytesIO()
    bio.name = 'velha_vitoria.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_imagem_velha_empate(nome1, nome2):
    img = Image.new('RGB', (500, 320), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 24)
        font_nome = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_nome = ImageFont.load_default()

    draw.text((115, 20), "🤝 DEU VELHA! 🤝", fill=(255, 205, 90), font=font_titulo)
    _vovo(draw, 215, 190, "feliz", (255, 105, 180), abracando=True)
    _vovo(draw, 285, 190, "feliz", (150, 110, 200), abracando=True)
    draw.ellipse([230, 90, 250, 108], fill=(255, 105, 180))
    draw.ellipse([250, 90, 270, 108], fill=(255, 105, 180))
    draw.text((70, 270), nome1[:16], fill=(255, 244, 250), font=font_nome)
    draw.text((270, 270), nome2[:16], fill=(255, 244, 250), font=font_nome)

    bio = io.BytesIO()
    bio.name = 'velha_empate.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_imagem_penalti_gol(batedor):
    img = Image.new('RGB', (500, 320), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 26)
        font_nome = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_nome = ImageFont.load_default()

    draw.text((120, 20), "🚀 GOLAÇO! 🚀", fill=(255, 205, 90), font=font_titulo)
    cx, cy = 250, 210
    draw.ellipse([cx - 16, cy - 70, cx + 16, cy - 38], fill=(255, 219, 200), outline=(60, 30, 50), width=2)
    _rosto(draw, cx, cy - 54, 16, "rindo")
    draw.polygon([(cx - 26, cy - 36), (cx + 26, cy - 36), (cx + 20, cy + 40), (cx - 20, cy + 40)], fill=(255, 105, 180), outline=(60, 30, 50))
    draw.line([cx - 20, cy - 30, cx - 55, cy - 65], fill=(255, 219, 200), width=8)
    draw.line([cx + 20, cy - 30, cx + 55, cy - 65], fill=(255, 219, 200), width=8)
    for ang in range(0, 360, 30):
        px = cx + 90 * math.cos(math.radians(ang))
        py = cy - 40 + 60 * math.sin(math.radians(ang))
        draw.ellipse([px - 5, py - 5, px + 5, py + 5], fill=random.choice([(255, 205, 90), (255, 105, 180), (200, 160, 255)]))
    draw.ellipse([cx - 90, cy + 60, cx - 60, cy + 90], fill=(255, 255, 255), outline=(60, 30, 50))
    draw.text((60, 270), f"{batedor[:20]} mandou pra rede!", fill=(255, 244, 250), font=font_nome)

    bio = io.BytesIO()
    bio.name = 'penalti_gol.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_imagem_penalti_defesa(goleiro, batedor):
    img = Image.new('RGB', (500, 320), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 26)
        font_nome = ImageFont.truetype("arial.ttf", 16)
        font_bubble = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_nome = ImageFont.load_default()
        font_bubble = ImageFont.load_default()

    draw.text((110, 20), "🧤 DEFESAÇA! 🧤", fill=(255, 205, 90), font=font_titulo)
    cx, cy = 170, 210
    draw.ellipse([cx - 16, cy - 70, cx + 16, cy - 38], fill=(255, 219, 200), outline=(60, 30, 50), width=2)
    _rosto(draw, cx, cy - 54, 16, "rindo")
    draw.polygon([(cx - 26, cy - 36), (cx + 26, cy - 36), (cx + 20, cy + 40), (cx - 20, cy + 40)], fill=(120, 190, 255), outline=(60, 30, 50))
    draw.line([cx - 20, cy - 30, cx - 60, cy - 40], fill=(255, 219, 200), width=8)
    draw.line([cx + 20, cy - 30, cx + 60, cy - 40], fill=(255, 219, 200), width=8)

    draw.rounded_rectangle([300, 60, 460, 120], radius=18, fill=(255, 244, 250), outline=(60, 30, 50), width=2)
    draw.polygon([(310, 118), (330, 118), (300, 140)], fill=(255, 244, 250), outline=(60, 30, 50))
    draw.text((320, 78), "kkk pegou\ntudo!", fill=(60, 30, 50), font=font_bubble)

    bx, by = 380, 220
    draw.ellipse([bx - 14, by - 70, bx + 14, by - 42], fill=(255, 219, 200), outline=(60, 30, 50), width=2)
    _rosto(draw, bx, by - 56, 14, "triste")
    draw.polygon([(bx - 22, by - 38), (bx + 22, by - 38), (bx + 16, by + 30), (bx - 16, by + 30)], fill=(150, 110, 200), outline=(60, 30, 50))

    draw.text((50, 270), f"{goleiro[:16]} zoou {batedor[:16]}!", fill=(255, 244, 250), font=font_nome)

    bio = io.BytesIO()
    bio.name = 'penalti_defesa.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def criar_grid_caca(palavras):
    rows, cols = 15, 15
    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    palavras_info = {}

    for p in palavras:
        p_alvo = p.upper().strip()
        invertida = random.choice([True, False])
        p_txt = p_alvo[::-1] if invertida else p_alvo
        l = len(p_txt)
        colocado = False
        tentativas = 0
        while not colocado and tentativas < 100:
            tentativas += 1
            orientacao = random.choice(["H", "V"])
            r = random.randint(0, rows - (l if orientacao == "V" else 1))
            c = random.randint(0, cols - (l if orientacao == "H" else 1))

            pode_colocar = True
            coords = []
            for i in range(l):
                curr_r, curr_c = (r + i, c) if orientacao == "V" else (r, c + i)
                if grid[curr_r][curr_c] != " " and grid[curr_r][curr_c] != p_txt[i]:
                    pode_colocar = False
                    break
                coords.append((curr_r, curr_c))

            if pode_colocar:
                for i, (cr, cc) in enumerate(coords):
                    grid[cr][cc] = p_txt[i]
                palavras_info[p_alvo] = {"coords": coords, "encontrada": False}
                colocado = True

    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == " ":
                grid[r][c] = random.choice(string.ascii_uppercase)

    return grid, palavras_info


def gerar_imagem_caca(chat_id):
    jogo = JOGOS_CACA[chat_id]
    grid, info = jogo["grid"], jogo["palavras_info"]
    cols, rows = len(grid[0]), len(grid)
    cell, margin = 30, 28
    img = Image.new('RGB', (cols * cell + margin * 2, rows * cell + margin * 2), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    for r in range(rows):
        for c in range(cols):
            x, y = margin + c * cell, margin + r * cell
            draw.rectangle([x, y, x + cell, y + cell], fill=(245, 245, 248), outline=(150, 150, 165), width=1)

    for p_data in info.values():
        if p_data["encontrada"]:
            for r, c in p_data["coords"]:
                x, y = margin + c * cell, margin + r * cell
                draw.rectangle([x + 1, y + 1, x + cell - 1, y + cell - 1], fill=(255, 105, 180), outline=(210, 55, 135), width=1)

    for r in range(rows):
        for c in range(cols):
            x, y = margin + c * cell, margin + r * cell
            achada = any(p_data["encontrada"] and (r, c) in p_data["coords"] for p_data in info.values())
            cor_letra = (255, 255, 255) if achada else (55, 55, 70)
            draw.text((x + 10, y + 6), grid[r][c], fill=cor_letra, font=font)

    bio = io.BytesIO()
    bio.name = 'caca.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_legenda_caca(chat_id):
    jogo = JOGOS_CACA[chat_id]
    info = jogo["palavras_info"]
    encontradas = sum(1 for item in info.values() if item["encontrada"])
    return (
        "🧩 <b>CAÇA-PALAVRAS</b> 🧩\n"
        f"🔍 Encontre as {len(info)} palavras escondidas\n"
        "📏 Mínimo de 4 letras\n"
        "🔄 Existem palavras invertidas\n"
        f"✅ Encontradas: {encontradas}\n"
        "🍀 <i>Boa sorte! Digite uma palavra quando encontrar.</i>"
    )


def gerar_grid_texto_caca(chat_id):
    jogo = JOGOS_CACA[chat_id]
    grid, info = jogo["grid"], jogo["palavras_info"]
    linhas = []
    for r in range(len(grid)):
        celulas = []
        for c in range(len(grid[0])):
            letra = grid[r][c]
            achada = any((r, c) in d["coords"] for d in info.values() if d["encontrada"])
            celulas.append(f"<b>{letra}</b>" if achada else letra)
        linhas.append(" ".join(celulas))
    return f"{gerar_legenda_caca(chat_id)}\n\n<pre>{chr(10).join(linhas)}</pre>"


def preparar_grade_cruzada(jogo):
    tamanho = 17
    grade = {}
    palavras = jogo["lista"]
    for indice, item in enumerate(palavras):
        palavra = item["palavra"]
        colocada = None
        orientacoes = ["H"] if indice == 0 else ["V", "H"]
        for orientacao in orientacoes:
            if colocada:
                break
            for linha in range(tamanho):
                for coluna in range(tamanho):
                    for posicao, letra in enumerate(palavra):
                        inicio_linha = linha - posicao if orientacao == "V" else linha
                        inicio_coluna = coluna if orientacao == "V" else coluna - posicao
                        coords = [
                            (inicio_linha + n if orientacao == "V" else inicio_linha,
                             inicio_coluna if orientacao == "V" else inicio_coluna + n)
                            for n in range(len(palavra))
                        ]
                        if any(r < 0 or r >= tamanho or c < 0 or c >= tamanho for r, c in coords):
                            continue
                        if any((r, c) in grade and grade[(r, c)] != palavra[n] for n, (r, c) in enumerate(coords)):
                            continue
                        vizinhos = [(r, c) for r, c in coords if (r, c) in grade]
                        if indice > 0 and not vizinhos:
                            continue
                        colocada = coords
                        break
                    if colocada:
                        break
                if colocada:
                    break
        if colocada is None:
            linha = min(indice * 2, tamanho - 1)
            colocada = [(linha, coluna) for coluna in range(min(len(palavra), tamanho))]
        item["coords"] = colocada
        for n, coordenada in enumerate(colocada):
            grade[coordenada] = palavra[n]
    min_linha = min(linha for linha, _ in grade)
    max_linha = max(linha for linha, _ in grade)
    min_coluna = min(coluna for _, coluna in grade)
    max_coluna = max(coluna for _, coluna in grade)
    deslocamento_linha = (tamanho - 1 - (max_linha - min_linha)) // 2 - min_linha
    deslocamento_coluna = (tamanho - 1 - (max_coluna - min_coluna)) // 2 - min_coluna
    for item in palavras:
        item["coords"] = [
            (linha + deslocamento_linha, coluna + deslocamento_coluna)
            for linha, coluna in item["coords"]
        ]
        item["reveladas"] = random.sample(range(len(item["palavra"])), min(1, len(item["palavra"])))
    grade = {
        (linha + deslocamento_linha, coluna + deslocamento_coluna): letra
        for (linha, coluna), letra in grade.items()
    }
    jogo["grade"] = grade
    jogo["grade_tamanho"] = tamanho


def gerar_imagem_cruzada(jogo):
    if "grade" not in jogo:
        preparar_grade_cruzada(jogo)
    tamanho = jogo["grade_tamanho"]
    cell_size, margin_top, margin_side = 30, 70, 28
    img = Image.new('RGB', (tamanho * cell_size + margin_side * 2, tamanho * cell_size + margin_top + 28), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 22)
        font_letra = ImageFont.truetype("arial.ttf", 16)
        font_numero = ImageFont.truetype("arial.ttf", 9)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_letra = ImageFont.load_default()
        font_numero = ImageFont.load_default()

    draw.text((margin_side, 22), "❤️  PALAVRAS CRUZADAS  ❤️", fill=(255, 133, 189), font=font_titulo)
    grade = jogo["grade"]
    numero_por_coord = {item["coords"][0]: indice + 1 for indice, item in enumerate(jogo["lista"])}
    for (linha, coluna), letra in grade.items():
        x = margin_side + coluna * cell_size
        y = margin_top + linha * cell_size
        revelada = any(item["encontrada"] or n in item["reveladas"] for item in jogo["lista"] for n, coord in enumerate(item["coords"]) if coord == (linha, coluna))
        preenchimento = (255, 105, 180) if revelada else (255, 255, 255)
        draw.rectangle([x, y, x + cell_size - 2, y + cell_size - 2], fill=preenchimento, outline=(118, 76, 125), width=2)
        if (linha, coluna) in numero_por_coord:
            draw.text((x + 3, y + 2), str(numero_por_coord[(linha, coluna)]), fill=(118, 76, 125), font=font_numero)
        draw.text((x + 9, y + 7), letra if revelada else "", fill=(70, 35, 70), font=font_letra)

    bio = io.BytesIO()
    bio.name = 'cruzada.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def montar_texto_cruzada(jogo):
    linhas = ["❤️ <b>PALAVRAS CRUZADAS</b> ❤️ (Valendo 15 pts por palavra)\n"]
    for idx, item in enumerate(jogo["lista"]):
        palavra = item["palavra"]
        reveladas = item["reveladas"]
        if item["encontrada"]:
            linhas.append(f"<b>{idx + 1}. {palavra}</b> — {len(palavra)} letras ✅")
        else:
            mascara = "".join([letra if i in reveladas else "_" for i, letra in enumerate(palavra)])
            linhas.append(f"{idx + 1}. <code>{mascara}</code> — {len(palavra)} letras")
    return "\n".join(linhas)


def build_keyboard_velha(game):
    board = game['board']
    markup = InlineKeyboardMarkup(row_width=3)
    botoes = [InlineKeyboardButton("⬛" if s == "➖" else s, callback_data=f"velha_play_{i}") for i, s in enumerate(board)]
    markup.add(botoes[0], botoes[1], botoes[2])
    markup.add(botoes[3], botoes[4], botoes[5])
    markup.add(botoes[6], botoes[7], botoes[8])
    return markup


def texto_memoria(game):
    cartas = []
    for idx, simbolo in enumerate(game["cards"]):
        if idx in game["matched"] or idx in game["revealed"]:
            cartas.append(simbolo)
        else:
            cartas.append("❔")
    nomes = " vs ".join(f"{player['nome']}: {player['pares']} pares" for player in game.get("players", [])) or "Aguardando jogadores..."
    turno = game.get("players", [])[game["turn"]]["nome"] if game.get("players") and game.get("status") == "PLAYING" else nomes
    linhas = ["🧠 <b>JOGO DA MEMÓRIA</b> 🧠", "", f"👥 {nomes}", "🎯 Encontre os pares escondidos!", "🔁 Acerte o par para jogar novamente", f"👉 Vez de: <b>{turno}</b>", ""]
    for inicio in range(0, len(cartas), 4):
        linhas.append("  ".join(cartas[inicio:inicio + 4]))
    return "\n".join(linhas)


def teclado_memoria(game):
    markup = InlineKeyboardMarkup(row_width=4)
    botoes = []
    for idx in range(len(game["cards"])):
        if idx in game["matched"] or idx in game["revealed"]:
            rotulo = game["cards"][idx]
        else:
            rotulo = "❔"
        botoes.append(InlineKeyboardButton(rotulo, callback_data=f"memo_card_{idx}"))
    for inicio in range(0, len(botoes), 4):
        markup.add(*botoes[inicio:inicio + 4])
    return markup


def esconder_cartas_memoria(chat_id, message_id):
    time.sleep(1.5)
    game = JOGOS_MEMORIA.get(chat_id)
    if not game or not game.get("erro_pendente") or game.get("msg_id") != message_id:
        return
    game["revealed"] = []
    game.pop("erro_pendente", None)
    game["turn"] = 1 - game["turn"]
    try:
        bot.edit_message_text(texto_memoria(game), chat_id, message_id, reply_markup=teclado_memoria(game), parse_mode="HTML")
    except Exception:
        pass


def teclado_batata(game):
    return InlineKeyboardMarkup().add(InlineKeyboardButton("🥔 PASSAR A BATATA", callback_data="batata_passar"))


def teclado_lobby_batata(game):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🥔 Participar", callback_data="batata_join"))
    markup.add(InlineKeyboardButton("🔥 Começar", callback_data="batata_start"))
    return markup


def texto_batata(game):
    atual = game["players"][game["turn"]]
    nomes = " → ".join(player["nome"] for player in game["players"])
    return f"🥔 <b>BATATA QUENTE</b> 🥔\n\n👥 {nomes}\n\n🔥 Passes restantes: <b>{game['passes']}</b>\n👉 Batata com: <b>{atual['nome']}</b>\n\nPasse rápido antes que esquente!"


def texto_lobby_batata(game):
    nomes = ", ".join(player["nome"] for player in game["players"]) or "ninguém ainda"
    return f"🥔 <b>BATATA QUENTE</b> 🥔\n\n👥 Jogadores ({len(game['players'])}):\n{nomes}\n\nClique em Participar e depois em Começar."


def teclado_detetive(game):
    markup = InlineKeyboardMarkup(row_width=2)
    for player in game["players"]:
        markup.add(InlineKeyboardButton(f"🕵️ {player['nome']}", callback_data=f"det_voto_{player['id']}"))
    return markup


def teclado_lobby_detetive():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🕵️ Participar", callback_data="det_join"))
    markup.add(InlineKeyboardButton("🔎 Começar investigação", callback_data="det_start"))
    return markup


def teclado_ver_papel():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("🔐 Ver meu papel", callback_data="det_papel"))


def teclado_acoes_detetive(game):
    markup = teclado_ver_papel()
    for player in game["players"]:
        markup.add(InlineKeyboardButton(f"🎯 {player['nome']}", callback_data=f"det_matar_{player['id']}"))
    for player in game["players"]:
        markup.add(InlineKeyboardButton(f"🔎 Investigar {player['nome']}", callback_data=f"det_investigar_{player['id']}"))
    return markup


def teclado_escolher_vitima(game):
    markup = InlineKeyboardMarkup(row_width=2)
    for player in game["players"]:
        if player["id"] != game["culpado"] and player["id"] not in game.get("mortos", set()):
            markup.add(InlineKeyboardButton(f"🎯 {player['nome']}", callback_data=f"det_matar_{player['id']}"))
    return markup


def teclado_investigar(game):
    markup = InlineKeyboardMarkup(row_width=2)
    for player in game["players"]:
        if player["id"] not in game.get("mortos", set()) and player["id"] != game["detetive"]:
            markup.add(InlineKeyboardButton(f"🔎 {player['nome']}", callback_data=f"det_investigar_{player['id']}"))
    return markup


def texto_lobby_detetive(game):
    nomes = ", ".join(player["nome"] for player in game["players"]) or "ninguém ainda"
    return f"🕵️ <b>DETETIVE</b> 🕵️\n\n👥 Jogadores ({len(game['players'])}):\n{nomes}\n\nMínimo de 3 pessoas. Clique em Participar e depois em Começar investigação."


def iniciar_detetive(chat_id, message_id):
    game = JOGOS_DETETIVE[chat_id]
    game["status"] = "AGUARDANDO_ASSASSINO"
    game["culpado"] = random.choice(game["players"])["id"]
    inocentes = [player for player in game["players"] if player["id"] != game["culpado"]]
    game["detetive"] = random.choice(inocentes)["id"]
    game["message_id"] = message_id
    game["votos"] = []
    bot.edit_message_text(f"🕵️ <b>DETETIVE</b> 🕵️\n\n📍 O caso começou em <b>{game['local']}</b>.\n🔒 Cada pessoa deve clicar para ver seu papel em um alerta individual.\n\nA investigação está em andamento...", chat_id, message_id, reply_markup=teclado_acoes_detetive(game), parse_mode="HTML")


def texto_lobby_naval(game):
    nomes = ", ".join(player["nome"] for player in game["players"]) or "ninguém ainda"
    return f"🚢 <b>BATALHA NAVAL</b> 🚢\n\n👥 Jogadores ({len(game['players'])}/2):\n{nomes}\n\nPreciso de 2 pessoas! Clique em Participar."


def teclado_lobby_naval():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("🚢 Participar", callback_data="naval_join"))


def teclado_ataque_naval(game):
    atacante_id = game["players"][game["turno"]]["id"]
    defensor_id = game["players"][1 - game["turno"]]["id"]
    atacados = game["atacados"].get(atacante_id, set())
    navios_defensor = game["navios"].get(defensor_id, set())
    markup = InlineKeyboardMarkup(row_width=TAMANHO_NAVAL)
    botoes = []
    for cell in range(TAMANHO_NAVAL * TAMANHO_NAVAL):
        if cell in atacados:
            rotulo = "💥" if cell in navios_defensor else "🌊"
        else:
            rotulo = "❔"
        botoes.append(InlineKeyboardButton(rotulo, callback_data=f"naval_atacar_{cell}"))
    for inicio in range(0, len(botoes), TAMANHO_NAVAL):
        markup.add(*botoes[inicio:inicio + TAMANHO_NAVAL])
    return markup


def texto_ataque_naval(game):
    atacante = game["players"][game["turno"]]
    defensor = game["players"][1 - game["turno"]]
    return f"🚢 <b>BATALHA NAVAL</b> 🚢\n\n🎯 Vez de: <b>{atacante['nome']}</b>\n🛡️ Atacando a frota de: <b>{defensor['nome']}</b>\n\nClique numa casa pra atacar!"


@bot.message_handler(content_types=['photo'])
def capturar_foto_pv(mensagem):
    if mensagem.chat.type == "private":
        ULTIMA_FOTO_PV[mensagem.chat.id] = mensagem.photo[-1].file_id
        bot.reply_to(mensagem, "🖼️ Foto guardadinha! Agora me manda: <code>/addlink [gatilho] [url]</code>\n\n<i>O gatilho é a palavra que, quando alguém falar no grupo, eu solto esse link automaticamente 😉</i>", parse_mode="HTML")


@bot.message_handler(content_types=['sticker'])
def capturar_sticker_pv(mensagem):
    if mensagem.chat.type != "private":
        return
    sticker_id = mensagem.sticker.file_id
    if mensagem.from_user.id in MODO_STICKER_BICHO:
        if sticker_id not in STICKER_BICHOS:
            STICKER_BICHOS.append(sticker_id)
            salvar_lista_json(STICKER_BICHOS, ARQUIVO_STICKERS_BICHO)
        bot.reply_to(mensagem, "🐾 Sticker de bicho guardado! Manda mais ou desliga o modo com <code>/addbicho</code>.", parse_mode="HTML")
        return
    if sticker_id not in STICKER_IDS:
        STICKER_IDS.append(sticker_id)
        salvar_stickers(STICKER_IDS)
    bot.reply_to(mensagem, "💗 Figurinha aprendida! Vou usar ela de vez em quando nas minhas saudações.")


@bot.message_handler(commands=['addbicho'])
def comando_addbicho(mensagem):
    if mensagem.chat.type != "private":
        return
    user_id = mensagem.from_user.id
    if user_id in MODO_STICKER_BICHO:
        MODO_STICKER_BICHO.discard(user_id)
        bot.reply_to(mensagem, "✅ Modo de cadastro de bicho desligado.")
    else:
        MODO_STICKER_BICHO.add(user_id)
        bot.reply_to(
            mensagem,
            "🐾 Modo ligado! Manda agora os stickers dos bichos que você criou (um de cada vez).\n\nQuando terminar, manda <code>/addbicho</code> de novo pra desligar.",
            parse_mode="HTML",
        )


@bot.message_handler(commands=['bichos'])
def comando_listar_bichos(mensagem):
    if mensagem.chat.type != "private":
        return
    bot.reply_to(mensagem, f"🐾 Tenho <b>{len(STICKER_BICHOS)}</b> sticker(s) de bicho cadastrado(s).\n\nNo grupo, só admin/dono pode falar <b>santos solta o bicho</b> pra eu soltar um aleatório.", parse_mode="HTML")


def texto_menu_pv():
    return "👑 <b>SANTOS — CENTRAL PRIVADA</b> 👑\n\nEscolha um assunto abaixo:"


def teclado_menu_pv():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("⚙️ Painel dos meus grupos", callback_data="menu_painel"))
    markup.add(InlineKeyboardButton("🔗 Links de plataforma", callback_data="menu_links"))
    markup.add(InlineKeyboardButton("🐾 Stickers do Solta o Bicho", callback_data="menu_bicho"))
    return markup


def texto_menu_links():
    return (
        "🔗 <b>LINKS DE PLATAFORMA</b>\n\n"
        "Quando alguém fala a palavra-gatilho no grupo, eu solto o link automaticamente.\n\n"
        "🖼️ <b>1.</b> Me manda a foto/banner (opcional)\n"
        "➕ <b>2.</b> <code>/addlink [gatilho] [url]</code> — salva o link\n"
        "<i>Ex: /addlink URBEPG https://exemplo.com\n"
        "Palavra com espaço: /addlink \"GRUPO DA GABI\" https://exemplo.com</i>\n"
        "📋 <b>3.</b> <code>/links</code> — vê tudo que já cadastrei\n"
        "🗑️ <b>4.</b> <code>/removerlink [gatilho]</code> — remove um link"
    )


def texto_menu_bicho():
    return (
        "🐾 <b>SOLTA O BICHO</b>\n\n"
        "1. <code>/addbicho</code> — liga o modo de cadastro\n"
        "2. Manda os stickers dos bichos que você criou (um de cada vez)\n"
        "3. <code>/addbicho</code> de novo — desliga o modo\n\n"
        "No grupo, só admin/dono pode escrever <b>santos solta o bicho</b> para ela soltar um sticker aleatório."
    )


def teclado_voltar_menu():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Voltar", callback_data="menu_inicio"))


def eh_admin_no_grupo(chat_id, user_id):
    return eh_admin_por_id(chat_id, user_id)


def teclado_painel_grupos(user_id):
    grupos = [(chat_id, config.get("nome") or str(chat_id)) for chat_id, config in CONFIG_GRUPOS.items() if eh_admin_no_grupo(chat_id, user_id)]
    markup = InlineKeyboardMarkup(row_width=1)
    for chat_id, nome in grupos:
        markup.add(InlineKeyboardButton(f"⚙️ {nome}", callback_data=f"painel_grupo_{chat_id}"))
    markup.add(InlineKeyboardButton("⬅️ Voltar", callback_data="menu_inicio"))
    return markup, grupos


CAMPOS_PAINEL = [("r", "auto_reacoes", "Reações automáticas"), ("i", "auto_ia", "Respostas automáticas (IA)"), ("j", "auto_jogos", "Jogos automáticos")]


def texto_painel_grupo(chat_id):
    config = CONFIG_GRUPOS.get(chat_id, config_grupo_padrao())
    linhas = [f"⚙️ <b>PAINEL DO GRUPO</b>\n<b>{config.get('nome', chat_id)}</b>\n"]
    for _, campo, nome in CAMPOS_PAINEL:
        marcador = "✅" if config.get(campo, True) else "❌"
        linhas.append(f"{marcador} {nome}")
    linhas.append("\nClique para ligar/desligar:")
    return "\n".join(linhas)


def teclado_painel_grupo(chat_id):
    config = CONFIG_GRUPOS.get(chat_id, config_grupo_padrao())
    markup = InlineKeyboardMarkup(row_width=1)
    for codigo, campo, nome in CAMPOS_PAINEL:
        marcador = "✅" if config.get(campo, True) else "❌"
        markup.add(InlineKeyboardButton(f"{marcador} {nome}", callback_data=f"painel_toggle_{chat_id}_{codigo}"))
    markup.add(InlineKeyboardButton("⬅️ Voltar", callback_data="painel_voltar"))
    return markup


@bot.message_handler(commands=['painel'])
def comando_painel(mensagem):
    if mensagem.chat.type != "private":
        return
    markup, grupos = teclado_painel_grupos(mensagem.from_user.id)
    if not grupos:
        bot.reply_to(mensagem, "🔒 Não encontrei nenhum grupo onde você seja administrador com a Santos presente.")
        return
    bot.reply_to(mensagem, "⚙️ <b>PAINEL DOS GRUPOS</b>\n\nEscolha o grupo que quer configurar:", reply_markup=markup, parse_mode="HTML")


@bot.message_handler(commands=['addlink', 'removerlink', 'links', 'start', 'help', 'ajuda'])
def comandos_pv_geral(mensagem):
    if mensagem.chat.type != "private":
        return
    texto = mensagem.text.strip()
    texto_lower = texto.lower()

    if texto_lower.startswith(('/start', '/help', '/ajuda')):
        bot.reply_to(mensagem, texto_menu_pv(), reply_markup=teclado_menu_pv(), parse_mode="HTML")
        return

    if texto_lower.startswith("/addlink"):
        try:
            partes = shlex.split(texto)
        except ValueError:
            partes = []
        if len(partes) < 3:
            bot.reply_to(
                mensagem,
                "⚠️ Faltou informação! Usa assim: <code>/addlink [gatilho] [url]</code>\n<i>Para várias palavras, coloque o gatilho entre aspas: /addlink \"GRUPO DA GABI\" https://exemplo.com</i>",
                parse_mode="HTML",
            )
            return
        gatilho, url = partes[1].strip().upper(), partes[2].strip()
        if len(gatilho) < 2 or not url.lower().startswith(("http://", "https://")):
            bot.reply_to(mensagem, "⚠️ Confira o gatilho e use um link começando com <code>http://</code> ou <code>https://</code>.", parse_mode="HTML")
            return
        file_id = ULTIMA_FOTO_PV.get(mensagem.chat.id, "")
        GATILHOS_PLATAFORMAS[gatilho] = {"url": url, "file_id": file_id}
        salvar_gatilhos(GATILHOS_PLATAFORMAS)
        preview = escolher_sem_repetir("preview_pv", [frase.format(g=gatilho) for frase in FRASES_PLATAFORMA])
        aviso_foto = "" if file_id else "\n\n⚠️ <i>Você não me mandou foto ainda, então vou soltar só o texto + link quando o gatilho for falado.</i>"
        bot.reply_to(
            mensagem,
            f"✅ Prontinho, gravei a plataforma <b>{gatilho}</b>! 💾\n\n"
            f"Toda vez que alguém falar <b>{gatilho}</b> no grupo, eu solto algo tipo:\n"
            f"<i>«{preview}»</i>{aviso_foto}",
            parse_mode="HTML",
        )
        return

    if texto_lower.startswith("/removerlink"):
        partes = texto.split()
        if len(partes) < 2:
            bot.reply_to(mensagem, "⚠️ Usa assim: <code>/removerlink [gatilho]</code>", parse_mode="HTML")
            return
        gatilho = partes[1].upper()
        if gatilho in GATILHOS_PLATAFORMAS:
            del GATILHOS_PLATAFORMAS[gatilho]
            salvar_gatilhos(GATILHOS_PLATAFORMAS)
            bot.reply_to(mensagem, f"🗑️ Beleza, tirei a <b>{gatilho}</b> da lista!", parse_mode="HTML")
        else:
            bot.reply_to(mensagem, f"🤔 Não achei nenhuma plataforma <b>{gatilho}</b> cadastrada.", parse_mode="HTML")
        return

    if texto_lower.startswith("/links"):
        if not GATILHOS_PLATAFORMAS:
            bot.reply_to(mensagem, "📋 Ainda não tenho nenhuma plataforma cadastrada. Manda uma foto + <code>/addlink</code> pra eu aprender!", parse_mode="HTML")
            return
        markup = InlineKeyboardMarkup(row_width=1)
        linhas = ["📋 <b>Plataformas cadastradas:</b>\n"]
        for g, d in GATILHOS_PLATAFORMAS.items():
            linhas.append(f"• <b>{g}</b> ➔ {d['url']}")
            markup.add(InlineKeyboardButton(f"🗑️ Remover {g}", callback_data=f"rmlink_{g}"))
        bot.reply_to(mensagem, "\n".join(linhas), reply_markup=markup, parse_mode="HTML")
        return

 

@bot.message_handler(func=lambda mensagem: mensagem.chat.type == "private")
def processar_acao_privada(mensagem):
    acao = DETETIVE_ACOES.get(mensagem.from_user.id)
    if not acao:
        return
    game = JOGOS_DETETIVE.get(acao["chat_id"])
    if not game:
        DETETIVE_ACOES.pop(mensagem.from_user.id, None)
        return
    nome = (mensagem.text or "").strip().casefold()
    jogadores_ativos = [player for player in game["players"] if player["id"] not in game.get("mortos", set())]
    if acao["acao"] == "matar":
        alvo = next((player for player in jogadores_ativos if player["nome"].casefold() == nome and player["id"] != mensagem.from_user.id), None)
        if not alvo:
            bot.reply_to(mensagem, "Não encontrei esse nome. Escreva exatamente como aparece na lista.")
            return
        game.setdefault("mortos", set()).add(alvo["id"])
        DETETIVE_ACOES.pop(mensagem.from_user.id, None)
        detetive = next(player for player in game["players"] if player["id"] == game["detetive"])
        game["status"] = "AGUARDANDO_DETETIVE"
        DETETIVE_ACOES[detetive["id"]] = {"chat_id": acao["chat_id"], "acao": "investigar"}
        opcoes = ", ".join(player["nome"] for player in jogadores_ativos if player["id"] not in (mensagem.from_user.id, alvo["id"]))
        bot.reply_to(mensagem, "✅ A vítima foi escolhida. Aguarde a investigação.")
        bot.send_message(detetive["id"], f"🔎 Escolha alguém para investigar escrevendo o nome exato.\nAlvos: <b>{opcoes}</b>", parse_mode="HTML")
        bot.edit_message_text(f"🕵️ <b>NOITE ENCERRADA</b>\n\n💔 {alvo['nome']} foi encontrado fora do jogo.\n🔎 O Detetive está investigando...", acao["chat_id"], game["message_id"], parse_mode="HTML")
        return
    if acao["acao"] == "investigar":
        alvo = next((player for player in jogadores_ativos if player["nome"].casefold() == nome and player["id"] != game["detetive"]), None)
        if not alvo:
            bot.reply_to(mensagem, "Não encontrei esse nome. Escreva exatamente como aparece na lista.")
            return
        papel = "ASSASSINO" if alvo["id"] == game["culpado"] else "INOCENTE"
        bot.reply_to(mensagem, f"🔎 Resultado secreto: <b>{alvo['nome']}</b> é <b>{papel}</b>.")
        DETETIVE_ACOES.pop(mensagem.from_user.id, None)
        game["status"] = "VOTANDO"
        sobreviventes = [player for player in game["players"] if player["id"] not in game.get("mortos", set())]
        game["votos"] = []
        markup = InlineKeyboardMarkup(row_width=2)
        for player in sobreviventes:
            markup.add(InlineKeyboardButton(f"🔎 {player['nome']}", callback_data=f"det_voto_{player['id']}"))
        bot.edit_message_text("🕵️ <b>HORA DA VOTAÇÃO</b>\n\nQuem vocês acham que é o assassino?", acao["chat_id"], game["message_id"], reply_markup=markup, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: True)
def botoes_callback(call):
    try:
        processar_callback(call)
    except Exception as erro:
        print(f"Erro isolado em callback: {type(erro).__name__}: {erro}")


def processar_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    user_name = call.from_user.first_name or "Membro"
    user_id = call.from_user.id

    if data == "menu_inicio":
        bot.edit_message_text(texto_menu_pv(), chat_id, call.message.message_id, reply_markup=teclado_menu_pv(), parse_mode="HTML")
        return

    if data == "menu_links":
        bot.edit_message_text(texto_menu_links(), chat_id, call.message.message_id, reply_markup=teclado_voltar_menu(), parse_mode="HTML")
        return

    if data == "menu_bicho":
        bot.edit_message_text(texto_menu_bicho(), chat_id, call.message.message_id, reply_markup=teclado_voltar_menu(), parse_mode="HTML")
        return

    if data == "menu_painel":
        markup, grupos = teclado_painel_grupos(user_id)
        if not grupos:
            bot.edit_message_text("🔒 Não encontrei nenhum grupo onde você seja administrador com a Santos presente.", chat_id, call.message.message_id, reply_markup=teclado_voltar_menu())
            return
        bot.edit_message_text("⚙️ <b>PAINEL DOS GRUPOS</b>\n\nEscolha o grupo que quer configurar:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data.startswith("painel_grupo_"):
        alvo_chat_id = int(data.replace("painel_grupo_", "", 1))
        if not eh_admin_no_grupo(alvo_chat_id, user_id):
            bot.answer_callback_query(call.id, "Você não é admin desse grupo.", show_alert=True)
            return
        bot.edit_message_text(texto_painel_grupo(alvo_chat_id), chat_id, call.message.message_id, reply_markup=teclado_painel_grupo(alvo_chat_id), parse_mode="HTML")
        return

    if data.startswith("painel_toggle_"):
        resto = data.replace("painel_toggle_", "", 1)
        alvo_chat_id_str, codigo = resto.rsplit("_", 1)
        alvo_chat_id = int(alvo_chat_id_str)
        if not eh_admin_no_grupo(alvo_chat_id, user_id):
            bot.answer_callback_query(call.id, "Você não é admin desse grupo.", show_alert=True)
            return
        campo = next((campo for cod, campo, _ in CAMPOS_PAINEL if cod == codigo), None)
        if not campo:
            return
        config = CONFIG_GRUPOS.setdefault(alvo_chat_id, config_grupo_padrao())
        config[campo] = not config.get(campo, True)
        salvar_config_grupos(CONFIG_GRUPOS)
        bot.answer_callback_query(call.id, "Atualizado!")
        bot.edit_message_text(texto_painel_grupo(alvo_chat_id), chat_id, call.message.message_id, reply_markup=teclado_painel_grupo(alvo_chat_id), parse_mode="HTML")
        return

    if data == "painel_voltar":
        markup, grupos = teclado_painel_grupos(user_id)
        if not grupos:
            bot.edit_message_text("🔒 Não encontrei nenhum grupo onde você seja administrador.", chat_id, call.message.message_id, reply_markup=teclado_voltar_menu())
            return
        bot.edit_message_text("⚙️ <b>PAINEL DOS GRUPOS</b>\n\nEscolha o grupo que quer configurar:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data == "naval_join":
        game = JOGOS_NAVAL.get(chat_id)
        if not game or game["status"] != "LOBBY":
            return
        if any(player["id"] == user_id for player in game["players"]):
            bot.answer_callback_query(call.id, "Você já entrou!")
            return
        if len(game["players"]) >= 2:
            bot.answer_callback_query(call.id, "Já tem 2 jogadores nessa partida!", show_alert=True)
            return
        game["players"].append({"id": user_id, "nome": user_name})
        if len(game["players"]) < 2:
            bot.answer_callback_query(call.id, "Você entrou! Esperando o segundo jogador...")
            bot.edit_message_text(texto_lobby_naval(game), chat_id, call.message.message_id, reply_markup=teclado_lobby_naval(), parse_mode="HTML")
            return
        # As posições ficam ocultas (só reveladas por acerto/erro no ataque); não dá pra mostrar um tabuleiro privado dentro do grupo, então a Santos sorteia sozinha.
        game["status"] = "JOGANDO"
        game["msg_id"] = call.message.message_id
        game["turno"] = 0
        for player in game["players"]:
            game["navios"][player["id"]] = set(random.sample(range(TAMANHO_NAVAL * TAMANHO_NAVAL), QTD_NAVIOS_NAVAL))
            game["atacados"][player["id"]] = set()
        bot.answer_callback_query(call.id, "Partida completa! Frotas sorteadas.")
        bot.edit_message_text(texto_ataque_naval(game), chat_id, call.message.message_id, reply_markup=teclado_ataque_naval(game), parse_mode="HTML")
        return

    if data.startswith("naval_atacar_"):
        game = JOGOS_NAVAL.get(chat_id)
        if not game or game["status"] != "JOGANDO":
            return
        atacante = game["players"][game["turno"]]
        defensor = game["players"][1 - game["turno"]]
        if user_id != atacante["id"]:
            bot.answer_callback_query(call.id, "Não é sua vez!", show_alert=True)
            return
        cell = int(data.replace("naval_atacar_", "", 1))
        atacados = game["atacados"].setdefault(atacante["id"], set())
        if cell in atacados:
            bot.answer_callback_query(call.id, "Você já atacou essa casa!")
            return
        atacados.add(cell)
        navios_defensor = game["navios"].get(defensor["id"], set())
        acertou = cell in navios_defensor
        bot.answer_callback_query(call.id, "💥 Acertou!" if acertou else "🌊 Água!")
        if acertou and navios_defensor.issubset(atacados):
            adicionar_pontos(chat_id, atacante["id"], atacante["nome"], 30)
            bot.edit_message_text(f"🚢 <b>BATALHA NAVAL ENCERRADA</b> 🚢\n\n🏆 <b>{atacante['nome']}</b> afundou toda a frota de {defensor['nome']} e venceu! (+30 pts)", chat_id, call.message.message_id, parse_mode="HTML")
            JOGOS_NAVAL.pop(chat_id, None)
            liberar_jogo(chat_id, "naval")
            return
        if not acertou:
            game["turno"] = 1 - game["turno"]
        bot.edit_message_text(texto_ataque_naval(game), chat_id, call.message.message_id, reply_markup=teclado_ataque_naval(game), parse_mode="HTML")
        return

    if data == "batata_join":
        game = JOGOS_BATATA.get(chat_id)
        if not game or game["status"] != "LOBBY":
            bot.answer_callback_query(call.id, "Essa rodada já foi encerrada ou começou.")
            return
        if any(player["id"] == user_id for player in game["players"]):
            bot.answer_callback_query(call.id, "Você já entrou!")
            return
        game["players"].append({"id": user_id, "nome": user_name})
        bot.answer_callback_query(call.id, "Você entrou na roda!")
        bot.edit_message_text(texto_lobby_batata(game), chat_id, call.message.message_id, reply_markup=teclado_lobby_batata(game), parse_mode="HTML")
        return

    if data == "batata_start":
        game = JOGOS_BATATA.get(chat_id)
        if not game or game["status"] != "LOBBY":
            return
        if len(game["players"]) < 2:
            bot.answer_callback_query(call.id, "É preciso ter pelo menos 2 jogadores.", show_alert=True)
            return
        game["status"] = "ATIVA"
        game["turn"] = random.randrange(len(game["players"]))
        game["passes"] = random.randint(5, 9)
        bot.answer_callback_query(call.id, "A bomba foi ativada!")
        bot.edit_message_text(texto_batata(game), chat_id, call.message.message_id, reply_markup=teclado_batata(game), parse_mode="HTML")
        return

    if data == "batata_passar":
        game = JOGOS_BATATA.get(chat_id)
        if not game or game["status"] != "ATIVA":
            return
        atual = game["players"][game["turn"]]
        if user_id != atual["id"]:
            bot.answer_callback_query(call.id, f"A batata está com {atual['nome']}!")
            return
        game["passes"] -= 1
        if game["passes"] <= 0:
            game["status"] = "ENCERRADA"
            adicionar_pontos(chat_id, atual["id"], atual["nome"], -5)
            bot.edit_message_text(f"💥 <b>A BATATA ESTOUROU!</b> 💥\n\n🥔 {atual['nome']} ficou com a batata e perdeu 5 pontos!", chat_id, call.message.message_id, parse_mode="HTML")
            JOGOS_BATATA.pop(chat_id, None)
            liberar_jogo(chat_id, "batata")
            return
        game["turn"] = (game["turn"] + 1) % len(game["players"])
        bot.answer_callback_query(call.id, "Batata passada! Não deixe esquentar!")
        bot.edit_message_text(texto_batata(game), chat_id, call.message.message_id, reply_markup=teclado_batata(game), parse_mode="HTML")
        return

    if data == "det_papel":
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game.get("status") == "LOBBY":
            bot.answer_callback_query(call.id, "A investigação ainda não começou.")
            return
        player = next((player for player in game["players"] if player["id"] == user_id), None) if game else None
        if not player:
            bot.answer_callback_query(call.id, "Você não participa desta investigação.", show_alert=True)
            return
        papel = "ASSASSINO" if user_id == game["culpado"] else "DETETIVE" if user_id == game["detetive"] else "VÍTIMA"
        bot.answer_callback_query(call.id, f"Você é: {papel}\nLocal: {game['local']}", show_alert=True)
        if user_id == game["culpado"] and game["status"] == "AGUARDANDO_ASSASSINO":
            game["status"] = "ESCOLHENDO_VITIMA"
        elif user_id == game["detetive"] and game["status"] == "AGUARDANDO_DETETIVE":
            game["status"] = "ESCOLHENDO_INVESTIGACAO"
        return

    if data.startswith("det_matar_"):
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game["status"] != "ESCOLHENDO_VITIMA" or user_id != game["culpado"]:
            bot.answer_callback_query(call.id, "Apenas o assassino pode escolher a vítima.")
            return
        alvo_id = int(data.replace("det_matar_", ""))
        alvo = next((player for player in game["players"] if player["id"] == alvo_id and player["id"] != game["culpado"]), None)
        if not alvo:
            return
        game.setdefault("mortos", set()).add(alvo_id)
        game["status"] = "AGUARDANDO_DETETIVE"
        bot.answer_callback_query(call.id, "A vítima foi escolhida.")
        bot.edit_message_text(f"🕵️ <b>NOITE ENCERRADA</b>\n\n💔 {alvo['nome']} foi eliminado.\n🔎 A investigação continua em segredo.", chat_id, call.message.message_id, reply_markup=teclado_acoes_detetive(game), parse_mode="HTML")
        return

    if data.startswith("det_investigar_"):
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game["status"] != "ESCOLHENDO_INVESTIGACAO" or user_id != game["detetive"]:
            bot.answer_callback_query(call.id, "Somente o detetive pode investigar.")
            return
        alvo_id = int(data.replace("det_investigar_", ""))
        alvo = next((player for player in game["players"] if player["id"] == alvo_id and player["id"] not in game.get("mortos", set())), None)
        if not alvo:
            return
        papel = "ASSASSINO" if alvo_id == game["culpado"] else "INOCENTE"
        bot.answer_callback_query(call.id, f"Resultado: {alvo['nome']} é {papel}.", show_alert=True)
        game["status"] = "VOTANDO"
        vivos = [player for player in game["players"] if player["id"] not in game.get("mortos", set())]
        game["votos"] = []
        markup = InlineKeyboardMarkup(row_width=2)
        for player in vivos:
            markup.add(InlineKeyboardButton(f"🔎 {player['nome']}", callback_data=f"det_voto_{player['id']}"))
        bot.edit_message_text("🕵️ <b>HORA DA VOTAÇÃO</b>\n\nQuem vocês acham que é o assassino?", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data == "det_join":
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game["status"] != "LOBBY":
            return
        if any(player["id"] == user_id for player in game["players"]):
            bot.answer_callback_query(call.id, "Você já entrou!")
            return
        if len(game["players"]) >= 10:
            bot.answer_callback_query(call.id, "A sala já está cheia.")
            return
        game["players"].append({"id": user_id, "nome": user_name})
        bot.answer_callback_query(call.id, "Você entrou na investigação!")
        bot.edit_message_text(texto_lobby_detetive(game), chat_id, call.message.message_id, reply_markup=teclado_lobby_detetive(), parse_mode="HTML")
        return

    if data == "det_start":
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game["status"] != "LOBBY":
            return
        if len(game["players"]) < 3:
            bot.answer_callback_query(call.id, "São necessárias pelo menos 3 pessoas.", show_alert=True)
            return
        iniciar_detetive(chat_id, call.message.message_id)
        return

    if data.startswith("det_voto_"):
        game = JOGOS_DETETIVE.get(chat_id)
        if not game or game["status"] != "VOTANDO":
            return
        if any(voto["id"] == user_id for voto in game["votos"]):
            bot.answer_callback_query(call.id, "Você já votou!")
            return
        vivos = [player for player in game["players"] if player["id"] not in game.get("mortos", set())]
        alvo = int(data.replace("det_voto_", ""))
        if user_id not in {player["id"] for player in vivos} or alvo not in {player["id"] for player in vivos}:
            bot.answer_callback_query(call.id, "Esse voto não está disponível.")
            return
        game["votos"].append({"id": user_id, "alvo": alvo})
        if len(game["votos"]) < len(vivos):
            bot.answer_callback_query(call.id, "Voto registrado!")
            return
        contagem = {}
        for voto in game["votos"]:
            contagem[voto["alvo"]] = contagem.get(voto["alvo"], 0) + 1
        escolhido = max(contagem, key=contagem.get)
        nome_escolhido = next(player["nome"] for player in game["players"] if player["id"] == escolhido)
        acertou = escolhido == game["culpado"]
        texto = f"🕵️ <b>CASO ENCERRADO!</b> 🕵️\n\nVotaram em: <b>{nome_escolhido}</b>\n"
        texto += "✅ O culpado foi descoberto!" if acertou else "❌ Era inocente! O culpado escapou."
        bot.edit_message_text(texto, chat_id, call.message.message_id, parse_mode="HTML")
        if acertou:
            for player in game["players"]:
                if player["id"] != game["culpado"]:
                    adicionar_pontos(chat_id, player["id"], player["nome"], 15)
        JOGOS_DETETIVE.pop(chat_id, None)
        liberar_jogo(chat_id, "detetive")
        return

    if data.startswith("forca_cat_"):
        game = JOGOS_FORCA.get(chat_id)
        if not game or game.get("status") != "CATEGORIA":
            return
        categoria = data.replace("forca_cat_", "", 1)
        if categoria == "aleatorio":
            opcoes = sorted({palavra for palavras in CATEGORIAS_FORCA.values() for palavra in palavras})
        else:
            opcoes = CATEGORIAS_FORCA.get(categoria, [])
        palavra = sortear_sem_repetir(chat_id, "forca", opcoes)
        game.update({"status": "ativo", "categoria": categoria, "palavra": palavra, "certas": set(), "erradas": set(), "erros": 0})
        mascara = " ".join(["_" for _ in palavra])
        try:
            bot.edit_message_media(
                InputMediaPhoto(gerar_imagem_forca(0), caption=f"💀 <b>FORCA</b>\nCategoria: <b>{categoria.upper()}</b>\nPalavra: <code>{mascara}</code>\nErros: 0/6", parse_mode="HTML"),
                chat_id, call.message.message_id,
            )
        except Exception:
            pass
        return

    if data == "memo_join":
        game = JOGOS_MEMORIA.get(chat_id)
        if not game or game.get("status") != "LOBBY":
            return
        if any(player["id"] == user_id for player in game["players"]):
            bot.answer_callback_query(call.id, "Você já entrou!")
            return
        if len(game["players"]) >= 2:
            bot.answer_callback_query(call.id, "Essa partida já tem duas jogadoras.")
            return
        game["players"].append({"id": user_id, "nome": user_name, "pares": 0})
        if len(game["players"]) < 2:
            bot.answer_callback_query(call.id, "Você entrou! Falta mais uma pessoa.")
            try:
                markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Participar", callback_data="memo_join"))
                bot.edit_message_text(f"🧠 <b>JOGO DA MEMÓRIA</b> 🧠\n\n👥 {user_name} entrou! Falta mais uma pessoa.\n\n👇 Clique para participar!", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
            except Exception:
                pass
            return
        game["status"] = "PLAYING"
        bot.answer_callback_query(call.id, "Partida iniciada!")
        try:
            bot.edit_message_text(texto_memoria(game), chat_id, call.message.message_id, reply_markup=teclado_memoria(game), parse_mode="HTML")
        except Exception:
            pass
        return

    if data.startswith("memo_card_"):
        game = JOGOS_MEMORIA.get(chat_id)
        if not game or game.get("status") != "PLAYING" or len(game["matched"]) == len(game["cards"]):
            return
        if game.get("erro_pendente"):
            bot.answer_callback_query(call.id, "Aguarde as cartas virarem.")
            return
        jogador = game["players"][game["turn"]]
        if user_id != jogador["id"]:
            bot.answer_callback_query(call.id, f"Agora é a vez de {jogador['nome']}.")
            return
        idx = int(data.replace("memo_card_", ""))
        if idx in game["matched"] or idx in game["revealed"]:
            bot.answer_callback_query(call.id, "Essa carta já está virada!")
            return
        game["revealed"].append(idx)
        if len(game["revealed"]) == 1:
            bot.answer_callback_query(call.id, "Escolha a segunda carta!")
        else:
            primeiro, segundo = game["revealed"]
            if game["cards"][primeiro] == game["cards"][segundo]:
                game["matched"].update((primeiro, segundo))
                jogador["pares"] += 1
                adicionar_pontos(chat_id, user_id, user_name, 10)
                game["revealed"] = []
                bot.answer_callback_query(call.id, "Par encontrado! Você continua.")
            else:
                game["erro_pendente"] = True
                bot.answer_callback_query(call.id, "Não formou par. A vez passou!")
                threading.Thread(target=esconder_cartas_memoria, args=(chat_id, call.message.message_id), daemon=True).start()
        try:
            bot.edit_message_text(texto_memoria(game), chat_id, call.message.message_id, reply_markup=teclado_memoria(game), parse_mode="HTML")
        except Exception:
            pass
        if len(game["matched"]) == len(game["cards"]):
            placar = "\n".join(f"🏆 <b>{player['nome']}</b>: {player['pares']} pares" for player in sorted(game["players"], key=lambda item: item["pares"], reverse=True))
            bot.send_message(chat_id, f"✨ <b>RESULTADO FINAL DA MEMÓRIA</b> ✨\n\n{placar}", parse_mode="HTML")
            JOGOS_MEMORIA.pop(chat_id, None)
            liberar_jogo(chat_id, "memoria")
        return

    if data.startswith("moeda_"):
        game = JOGOS_MOEDA.get((chat_id, call.message.message_id))
        if not game or game.get("encerrado"):
            bot.answer_callback_query(call.id, "Essa rodada já terminou. Inicie outra com .moeda.")
            return
        escolha = data.replace("moeda_", "")
        resultado = random.choice(["cara", "coroa"])
        game["encerrado"] = True
        if resultado == escolha:
            adicionar_pontos(chat_id, user_id, user_name, 5)
            texto = f"🪙 Deu <b>{resultado.upper()}</b>! <b>{user_name}</b> acertou! (+5 pts)"
        else:
            texto = f"🪙 Deu <b>{resultado.upper()}</b>! <b>{user_name}</b> não acertou dessa vez."
        bot.answer_callback_query(call.id, "Rodada encerrada!")
        try:
            bot.edit_message_text(texto, chat_id, call.message.message_id, parse_mode="HTML")
        except Exception:
            pass
        JOGOS_MOEDA.pop((chat_id, call.message.message_id), None)
        return

    if data.startswith("quiz_"):
        game = JOGOS_QUIZ.get(chat_id)
        if not game:
            return
        pergunta = game["pergunta"]
        idx = int(data.replace("quiz_", ""))
        if idx == pergunta["certa"]:
            adicionar_pontos(chat_id, user_id, user_name, 15)
            try:
                bot.edit_message_text(
                    f"✅ <b>{user_name}</b> acertou! 🧠\n\n❓ {pergunta['pergunta']}\n🏆 Resposta certa: <b>{pergunta['opcoes'][pergunta['certa']]}</b> (+15 pts)",
                    chat_id, call.message.message_id, parse_mode="HTML",
                )
            except Exception:
                pass
            JOGOS_QUIZ.pop(chat_id, None)
            liberar_jogo(chat_id, "quiz")
        else:
            bot.answer_callback_query(call.id, "❌ Não foi essa... tenta de novo!")
        return

    if data == "pi_join":
        game = JOGOS_PARIMPAR.get(chat_id)
        if not game or game.get('status') != 'LOBBY':
            return
        if any(p['id'] == user_id for p in game['players']):
            return
        game['players'].append({'id': user_id, 'name': user_name})
        if len(game['players']) == 2:
            game['status'] = 'ESCOLHENDO_PARIDADE'
            p1 = game['players'][0]
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Par", callback_data="pi_par"),
                InlineKeyboardButton("🔀 Ímpar", callback_data="pi_impar"),
            )
            bot.edit_message_text(f"✌️ <b>PAR OU ÍMPAR</b>\n{p1['name']} vs {game['players'][1]['name']}\n\n<b>{p1['name']}</b>, escolhe: par ou ímpar?", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        else:
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✌️ Entrar", callback_data="pi_join"))
            bot.edit_message_text(f"✌️ <b>PAR OU ÍMPAR</b> ✌️\n{game['players'][0]['name']} está esperando um adversário!", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data in ("pi_par", "pi_impar"):
        game = JOGOS_PARIMPAR.get(chat_id)
        if not game or game.get('status') != 'ESCOLHENDO_PARIDADE':
            return
        if user_id != game['players'][0]['id']:
            return
        game['paridade'] = "par" if data == "pi_par" else "impar"
        game['status'] = 'ESCOLHENDO_NUMERO'
        game['numeros'] = {}
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(*[InlineKeyboardButton(str(n), callback_data=f"pi_num_{n}") for n in range(6)])
        nomes = f"{game['players'][0]['name']} ({game['paridade'].upper()}) vs {game['players'][1]['name']} ({'IMPAR' if game['paridade'] == 'par' else 'PAR'.upper()})"
        bot.edit_message_text(f"✌️ <b>PAR OU ÍMPAR</b>\n{nomes}\n\n👇 Escolham um número de 0 a 5 (na moral, sem espiar)!", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data.startswith("pi_num_"):
        game = JOGOS_PARIMPAR.get(chat_id)
        if not game or game.get('status') != 'ESCOLHENDO_NUMERO':
            return
        if not any(p['id'] == user_id for p in game['players']):
            return
        if user_id in game['numeros']:
            return
        game['numeros'][user_id] = int(data.replace("pi_num_", ""))
        bot.answer_callback_query(call.id, "✅ Escolhido!")
        if len(game['numeros']) == 2:
            p1, p2 = game['players']
            n1, n2 = game['numeros'][p1['id']], game['numeros'][p2['id']]
            soma = n1 + n2
            par_venceu = soma % 2 == 0
            jogador_par = p1 if game['paridade'] == "par" else p2
            jogador_impar = p2 if game['paridade'] == "par" else p1
            vencedor = jogador_par if par_venceu else jogador_impar
            adicionar_pontos(chat_id, vencedor['id'], vencedor['name'], 20)
            texto = (
                f"✌️ <b>RESULTADO</b> ✌️\n\n"
                f"{p1['name']}: <b>{n1}</b>\n{p2['name']}: <b>{n2}</b>\n"
                f"Soma: <b>{soma}</b> ({'PAR' if par_venceu else 'ÍMPAR'})\n\n"
                f"🏆 <b>{vencedor['name']} venceu!</b> (+20 pts)"
            )
            try:
                bot.edit_message_text(texto, chat_id, call.message.message_id, parse_mode="HTML")
            except Exception:
                pass
            JOGOS_PARIMPAR.pop(chat_id, None)
            liberar_jogo(chat_id, "parimpar")
        return

    if data.startswith("rmlink_"):
        if call.message.chat.type != "private":
            return
        gatilho = data.replace("rmlink_", "", 1)
        if gatilho in GATILHOS_PLATAFORMAS:
            del GATILHOS_PLATAFORMAS[gatilho]
            salvar_gatilhos(GATILHOS_PLATAFORMAS)
            bot.answer_callback_query(call.id, f"🗑️ {gatilho} removida!")
        else:
            bot.answer_callback_query(call.id, "Já tinha sido removida.")
        if not GATILHOS_PLATAFORMAS:
            try:
                bot.edit_message_text("📋 Nenhuma plataforma cadastrada no momento.", chat_id, call.message.message_id)
            except Exception:
                pass
            return
        markup = InlineKeyboardMarkup(row_width=1)
        linhas = ["📋 <b>Plataformas cadastradas:</b>\n"]
        for g, d in GATILHOS_PLATAFORMAS.items():
            linhas.append(f"• <b>{g}</b> ➔ {d['url']}")
            markup.add(InlineKeyboardButton(f"🗑️ Remover {g}", callback_data=f"rmlink_{g}"))
        try:
            bot.edit_message_text("\n".join(linhas), chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            pass
        return

    if data in ("caca_modo_texto", "caca_modo_imagem"):
        if JOGO_ATIVO.get(chat_id) != "caca" or chat_id in JOGOS_CACA:
            return
        modo = "texto" if data == "caca_modo_texto" else "imagem"
        palavras = sortear_palavras_caca(chat_id)
        grid, p_info = criar_grid_caca(palavras)
        JOGOS_CACA[chat_id] = {"grid": grid, "palavras_info": p_info, "status": "ativo", "modo": modo}
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        if modo == "texto":
            msg = bot.send_message(chat_id, gerar_grid_texto_caca(chat_id), parse_mode="HTML")
        else:
            msg = bot.send_photo(chat_id, gerar_imagem_caca(chat_id), caption=gerar_legenda_caca(chat_id), parse_mode="HTML")
        JOGOS_CACA[chat_id]["msg_id"] = msg.message_id
        return

    if data == "ppt_join":
        game = JOGOS_PPT.get(chat_id)
        if not game or game.get('status') != 'LOBBY':
            return
        if any(p['id'] == user_id for p in game['players']):
            return

        game['players'].append({'id': user_id, 'name': user_name})
        if len(game['players']) >= 6:
            game['status'] = 'PLAYING'
            iniciar_partida_ppt(chat_id, call.message.message_id)
        else:
            nomes = ", ".join([p['name'] for p in game['players']])
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✊✋✌️ Entrar na Batalha", callback_data="ppt_join"))
            texto_lobby = (
                f"✊ <b>BATALHA DE PEDRA, PAPEL E TESOURA</b> ✌️\n\n"
                f"👥 Participantes ({len(game['players'])}/6):\n{nomes}\n\n"
                f"⏳ <i>O jogo começa em até 30 segundos (Se ninguém mais entrar, jogará contra o robô).</i>"
            )
            try:
                bot.edit_message_text(texto_lobby, chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("ppt_escolha_"):
        game = JOGOS_PPT.get(chat_id)
        if not game or game.get('status') != 'PLAYING':
            return
        escolha = data.replace("ppt_escolha_", "")
        for p in game['players']:
            if p['id'] == user_id and 'escolha' not in p:
                p['escolha'] = escolha
                bot.answer_callback_query(call.id, f"✅ Escolheu {escolha.upper()}!")
                if all('escolha' in participante for participante in game['players']):
                    apurar_resultado_ppt(chat_id, call.message.message_id)
                return
        return

    if data == "penalti_join":
        game = JOGOS_PENALTI.get(chat_id)
        if not game or game.get('status') != 'LOBBY':
            return
        if any(p['id'] == user_id for p in game['players']):
            return
        papel = "Batedor ⚽" if len(game['players']) == 0 else "Goleiro 🧤"
        game['players'].append({'id': user_id, 'name': user_name, 'role': papel})
        if len(game['players']) == 2:
            game['status'] = 'BATEDOR_ESCOLHENDO'
            batedor = game['players'][0]
            markup = InlineKeyboardMarkup(row_width=3)
            markup.add(
                InlineKeyboardButton("👈 Esquerdo", callback_data="p_chute_esquerdo"),
                InlineKeyboardButton("🎯 Meio", callback_data="p_chute_meio"),
                InlineKeyboardButton("👉 Direito", callback_data="p_chute_direito"),
            )
            bot.edit_message_text(
                f"⚽ <b>PÊNALTI</b>\nBatedor: <b>{batedor['name']}</b>\nGoleiro: <b>{game['players'][1]['name']}</b>\n\n<i>{batedor['name']}, escolha onde chutar!</i>",
                chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML",
            )
        return

    if data.startswith("p_chute_"):
        game = JOGOS_PENALTI.get(chat_id)
        if not game or game.get('status') != 'BATEDOR_ESCOLHENDO':
            return
        if user_id != game['players'][0]['id']:
            return
        game['chute'] = data.replace("p_chute_", "")
        game['status'] = 'GOLEIRO_ESCOLHENDO'
        goleiro = game['players'][1]
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("👈 Esquerdo", callback_data="p_def_esquerdo"),
            InlineKeyboardButton("🎯 Meio", callback_data="p_def_meio"),
            InlineKeyboardButton("👉 Direito", callback_data="p_def_direito"),
        )
        bot.edit_message_text(f"⚽ <b>PÊNALTI</b>\nBatedor escolheu!\nAgora <b>{goleiro['name']}</b> escolhe onde defender:", chat_id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        return

    if data.startswith("p_def_"):
        game = JOGOS_PENALTI.get(chat_id)
        if not game or game.get('status') != 'GOLEIRO_ESCOLHENDO':
            return
        goleiro = game['players'][1]
        if user_id != goleiro['id']:
            return
        defesa, chute, batedor = data.replace("p_def_", ""), game['chute'], game['players'][0]
        if chute == defesa:
            adicionar_pontos(chat_id, goleiro['id'], goleiro['name'], 20)
            res = "🛡️ <b>DEFESA DO GOLEIRO!</b> (+20 pts)"
            gif = buscar_gif("goalkeeper save mock laugh funny")
        else:
            adicionar_pontos(chat_id, batedor['id'], batedor['name'], 20)
            res = "🚀 <b>GOLAÇO!</b> (+20 pts para o Batedor)"
            gif = buscar_gif("soccer goal celebration funny")
        try:
            bot.edit_message_text(res, chat_id, call.message.message_id, parse_mode="HTML")
        except Exception:
            pass
        try:
            if gif:
                bot.send_animation(chat_id, gif)
            elif chute == defesa:
                bot.send_photo(chat_id, gerar_imagem_penalti_defesa(goleiro['name'], batedor['name']))
            else:
                bot.send_photo(chat_id, gerar_imagem_penalti_gol(batedor['name']))
        except Exception:
            pass
        JOGOS_PENALTI.pop(chat_id, None)
        liberar_jogo(chat_id, "penalti")
        return

    if data == "velha_join":
        game = JOGOS_VELHA.get(chat_id)
        if not game or game.get('status') != 'LOBBY':
            return
        if any(p['id'] == user_id for p in game['players']):
            return
        simbolo = "❌" if len(game['players']) == 0 else "⭕"
        game['players'].append({'id': user_id, 'name': user_name, 'symbol': simbolo})
        if len(game['players']) == 2:
            game['status'] = 'PLAYING'
            p1, p2 = game['players']
            try:
                bot.edit_message_caption(f"<b>VELHA</b>\n❌ {p1['name']} vs ⭕ {p2['name']}\nVez de: {p1['name']}", chat_id, call.message.message_id, reply_markup=build_keyboard_velha(game), parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("velha_play_"):
        game = JOGOS_VELHA.get(chat_id)
        if not game or game.get('status') != 'PLAYING':
            return
        p_idx = game['turn']
        if user_id != game['players'][p_idx]['id']:
            return
        pos = int(data.replace("velha_play_", ""))
        if game['board'][pos] != "➖":
            return
        game['board'][pos] = game['players'][p_idx]['symbol']
        b = game['board']
        vitorias = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]]
        if any(b[v[0]] == b[v[1]] == b[v[2]] != "➖" for v in vitorias):
            adicionar_pontos(chat_id, user_id, user_name, 25)
            perdedor = game['players'][1 - p_idx]['name']
            gif = buscar_gif("winning mocking laugh funny")
            try:
                if gif:
                    bot.edit_message_media(
                        media=InputMediaAnimation(gif, caption=f"🏆 <b>Vencedor: {user_name} (+25 pts)</b>", parse_mode="HTML"),
                        chat_id=chat_id, message_id=call.message.message_id,
                    )
                else:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_velha_vitoria(user_name, perdedor), caption=f"🏆 <b>Vencedor: {user_name} (+25 pts)</b>", parse_mode="HTML"),
                        chat_id=chat_id, message_id=call.message.message_id,
                    )
            except Exception:
                pass
            JOGOS_VELHA.pop(chat_id, None)
            liberar_jogo(chat_id, "velha")
            return
        if all(c != "➖" for c in b):
            p1, p2 = game['players']
            gif = buscar_gif("friends hugging cute funny")
            try:
                if gif:
                    bot.edit_message_media(
                        media=InputMediaAnimation(gif, caption="🤝 <b>Deu Velha!</b>", parse_mode="HTML"),
                        chat_id=chat_id, message_id=call.message.message_id,
                    )
                else:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_velha_empate(p1['name'], p2['name']), caption="🤝 <b>Deu Velha!</b>", parse_mode="HTML"),
                        chat_id=chat_id, message_id=call.message.message_id,
                    )
            except Exception:
                pass
            JOGOS_VELHA.pop(chat_id, None)
            liberar_jogo(chat_id, "velha")
            return
        game['turn'] = 1 - p_idx
        nxt = game['players'][game['turn']]['name']
        try:
            bot.edit_message_caption(f"Vez de: {nxt}", chat_id, call.message.message_id, reply_markup=build_keyboard_velha(game), parse_mode="HTML")
        except Exception:
            pass
        return


def iniciar_partida_ppt(chat_id, message_id):
    game = JOGOS_PPT.get(chat_id)
    if not game:
        return
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("✊ Pedra", callback_data="ppt_escolha_pedra"),
        InlineKeyboardButton("✋ Papel", callback_data="ppt_escolha_papel"),
        InlineKeyboardButton("✌️ Tesoura", callback_data="ppt_escolha_tesoura"),
    )
    if len(game['players']) == 1:
        game['contra_bot'] = True
        nomes = f"{game['players'][0]['name']} vs 🤖 Robô da Santos"
    else:
        game['contra_bot'] = False
        nomes = ", ".join([p['name'] for p in game['players']])
    try:
        bot.edit_message_text(f"⚔️ <b>BATALHA INICIADA!</b>\n\nConfronto: {nomes}\n\n👇 <i>Escolha no botão abaixo!</i>", chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass


def apurar_resultado_ppt(chat_id, message_id):
    game = JOGOS_PPT.get(chat_id)
    if not game:
        return
    opcoes = ["pedra", "papel", "tesoura"]
    resultados = []
    if game.get('contra_bot'):
        p = game['players'][0]
        u_esc = p.get('escolha', random.choice(opcoes))
        bot_esc = random.choice(opcoes)
        if u_esc == bot_esc:
            res = "🤝 Empate!"
        elif (u_esc == "pedra" and bot_esc == "tesoura") or (u_esc == "papel" and bot_esc == "pedra") or (u_esc == "tesoura" and bot_esc == "papel"):
            res = "🏆 Vitória! (+15 pts)"
            adicionar_pontos(chat_id, p['id'], p['name'], 15)
        else:
            res = "❌ Derrota!"
        resultados.append(f"👤 {p['name']} ({u_esc.upper()}) vs 🤖 Robô ({bot_esc.upper()}) ➔ {res}")
    else:
        for p in game['players']:
            if 'escolha' not in p:
                p['escolha'] = random.choice(opcoes)
        p1, p2 = game['players'][0], game['players'][1]
        e1, e2 = p1['escolha'], p2['escolha']
        if e1 == e2:
            r1 = r2 = "🤝 Empate!"
        elif (e1 == "pedra" and e2 == "tesoura") or (e1 == "papel" and e2 == "pedra") or (e1 == "tesoura" and e2 == "papel"):
            r1, r2 = "🏆 Vitória! (+15 pts)", "❌ Derrota!"
            adicionar_pontos(chat_id, p1['id'], p1['name'], 15)
        else:
            r1, r2 = "❌ Derrota!", "🏆 Vitória! (+15 pts)"
            adicionar_pontos(chat_id, p2['id'], p2['name'], 15)
        resultados.append(f"• {p1['name']} ({e1.upper()}) ➔ {r1}")
        resultados.append(f"• {p2['name']} ({e2.upper()}) ➔ {r2}")

    try:
        bot.edit_message_text("🏁 <b>RESULTADO PPT</b> 🏁\n\n" + "\n".join(resultados), chat_id, message_id, parse_mode="HTML")
    except Exception:
        pass
    JOGOS_PPT.pop(chat_id, None)
    liberar_jogo(chat_id, "ppt")


def timer_lobby_ppt(chat_id, message_id):
    time.sleep(30)
    game = JOGOS_PPT.get(chat_id)
    if game and game.get('status') == 'LOBBY':
        game['status'] = 'PLAYING'
        iniciar_partida_ppt(chat_id, message_id)


def worker_timer_cruzada():
    while True:
        time.sleep(10)
        for chat_id, jogo in list(JOGOS_CRUZADA.items()):
            if jogo.get("status") != "ativo":
                continue
            pendentes = [i for i in jogo["lista"] if not i["encontrada"] and len(i["reveladas"]) < len(i["palavra"])]
            if not pendentes:
                continue
            alvo = random.choice(pendentes)
            ocultas = [idx for idx in range(len(alvo["palavra"])) if idx not in alvo["reveladas"]]
            if ocultas:
                alvo["reveladas"].append(random.choice(ocultas))
                try:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_cruzada(jogo), caption=montar_texto_cruzada(jogo), parse_mode="HTML"),
                        chat_id=chat_id, message_id=jogo["msg_id"],
                    )
                except Exception:
                    pass


threading.Thread(target=worker_timer_cruzada, daemon=True).start()


COMANDOS_RESET = {
    ".LOADALL": ("todos", None),
    ".LOADFORCA": ("forca", JOGOS_FORCA),
    ".LOADCACA": ("caca", JOGOS_CACA),
    ".LOADCAÇA": ("caca", JOGOS_CACA),
    ".LOADCRUZADA": ("cruzada", JOGOS_CRUZADA),
    ".LOADVELHA": ("velha", JOGOS_VELHA),
    ".LOADPPT": ("ppt", JOGOS_PPT),
    ".LOADFUT": ("penalti", JOGOS_PENALTI),
    ".LOADQUIZ": ("quiz", JOGOS_QUIZ),
    ".LOADPARIMPAR": ("parimpar", JOGOS_PARIMPAR),
    ".LOADMEMO": ("memoria", JOGOS_MEMORIA),
    ".LOADEMOJI": ("emoji", JOGOS_EMOJI),
    ".LOADQUEM": ("quem", JOGOS_QUEM),
    ".LOADMISTERIO": ("misterio", JOGOS_MISTERIO),
    ".LOADRAPIDO": ("rapido", JOGOS_RAPIDO),
    ".LOADVF": ("vf", JOGOS_VF),
    ".LOADOCULTO": ("oculto", JOGOS_OCULTO),
    ".LOADCHARADA": ("charada", JOGOS_CHARADA),
    ".LOADSTOP": ("stop", JOGOS_STOP),
    ".LOADBATATA": ("batata", JOGOS_BATATA),
    ".LOADDETETIVE": ("detetive", JOGOS_DETETIVE),
    ".LOADNAVAL": ("naval", JOGOS_NAVAL),
}


@bot.message_handler(content_types=['text', 'photo', 'sticker', 'video', 'animation', 'voice', 'audio', 'document', 'video_note', 'new_chat_members', 'left_chat_member'])
def processador_grupos(mensagem):
    try:
        processar_mensagem_grupo(mensagem)
    except Exception as erro:
        print(f"Erro isolado em mensagem: {type(erro).__name__}: {erro}")


@bot.my_chat_member_handler()
def registrar_grupo_ao_mudar_status(atualizacao):
    chat = atualizacao.chat
    if chat.type == "private":
        return
    if chat.id not in CONFIG_GRUPOS:
        CONFIG_GRUPOS[chat.id] = config_grupo_padrao()
    CONFIG_GRUPOS[chat.id]["nome"] = chat.title or CONFIG_GRUPOS[chat.id].get("nome") or str(chat.id)
    salvar_config_grupos(CONFIG_GRUPOS)


def processar_mensagem_grupo(mensagem):
    if mensagem.chat.type == "private":
        return
    chat_id = mensagem.chat.id
    novo_grupo = chat_id not in CONFIG_GRUPOS
    if novo_grupo:
        CONFIG_GRUPOS[chat_id] = config_grupo_padrao()
    nome_atual = mensagem.chat.title or CONFIG_GRUPOS[chat_id].get("nome") or str(chat_id)
    if novo_grupo or CONFIG_GRUPOS[chat_id].get("nome") != nome_atual:
        CONFIG_GRUPOS[chat_id]["nome"] = nome_atual
        salvar_config_grupos(CONFIG_GRUPOS)

    texto = (mensagem.text or "").strip()
    texto_upper = texto.upper()
    user_id = mensagem.from_user.id
    user_name = mensagem.from_user.first_name or "Membro"

    registrar_interacao(chat_id, user_id, user_name)

    marcador_todos = "/todos"
    texto_sem_marcador = texto
    if marcador_todos in texto.casefold():
        if not administrador_do_grupo(mensagem):
            bot.reply_to(mensagem, "🔒 Esse comando é só para administradores do grupo.")
            return
        texto_sem_marcador = re.sub(r"/todos", "", texto, count=1, flags=re.IGNORECASE).strip()
        mencoes = criar_mencoes_grupo(chat_id)
        if not mencoes:
            bot.reply_to(mensagem, "👀 Ainda não conheço participantes suficientes para fazer as menções.")
            return
        mensagem_todos = texto_sem_marcador or "Atenção, pessoal!"
        bot.send_message(chat_id, f"{html.escape(mensagem_todos)}\n\n{mencoes}", parse_mode="HTML")
        return

    frase_normalizada = normalizar_resposta(re.sub(r"[^\w\s]", "", texto))
    if frase_normalizada == "santos solta o bicho":
        if not administrador_do_grupo(mensagem):
            bot.reply_to(mensagem, "🔒 Esse comando é só para administradores ou dono do grupo.")
            return
        if not STICKER_BICHOS:
            bot.reply_to(mensagem, "🐾 Ainda não tenho nenhum sticker de bicho cadastrado. Manda pra mim no PV com <code>/addbicho</code>!", parse_mode="HTML")
            return
        bicho = escolher_sem_repetir("solta_bicho", STICKER_BICHOS)
        bot.send_sticker(chat_id, bicho)
        bot.send_message(chat_id, "🎤 <b>SOLTA O BICHO!</b>\n\nManda um áudio de até 5 segundos imitando esse bicho! O dono do grupo vai avaliar quem mandou melhor 😏", parse_mode="HTML")
        return

    # Reset manual de qualquer jogo travado (evita que um jogo preso bloqueie os outros)
    if texto_upper in COMANDOS_RESET:
        nome_jogo, dicionario = COMANDOS_RESET[texto_upper]
        if nome_jogo == "todos":
            for jogos in (JOGOS_CACA, JOGOS_VELHA, JOGOS_MEMORIA, JOGOS_CRUZADA, JOGOS_PPT, JOGOS_PENALTI, JOGOS_FORCA, JOGOS_QUIZ, JOGOS_PARIMPAR, JOGOS_EMOJI, JOGOS_QUEM, JOGOS_MISTERIO, JOGOS_RAPIDO, JOGOS_VF, JOGOS_OCULTO, JOGOS_CHARADA, JOGOS_STOP, JOGOS_BATATA, JOGOS_DETETIVE, JOGOS_NAVAL):
                jogos.pop(chat_id, None)
            JOGO_ATIVO.pop(chat_id, None)
            bot.reply_to(mensagem, "🔄 Todas as partidas deste grupo foram resetadas. Agora dá para começar uma nova.")
            return
        jogo = dicionario.get(chat_id)
        detalhe = ""
        if nome_jogo == "cruzada" and jogo:
            faltantes = [item["palavra"] for item in jogo["lista"] if not item["encontrada"]]
            detalhe = f"\n📝 Faltaram: <b>{', '.join(faltantes)}</b>" if faltantes else "\n✅ Todas já tinham sido encontradas."
        elif nome_jogo == "caca" and jogo:
            faltantes = [palavra for palavra, item in jogo["palavras_info"].items() if not item["encontrada"]]
            detalhe = f"\n📝 Faltaram: <b>{', '.join(faltantes)}</b>" if faltantes else "\n✅ Todas já tinham sido encontradas."
        elif nome_jogo == "forca" and jogo:
            detalhe = f"\n📝 A palavra era: <b>{jogo['palavra']}</b>"
        elif nome_jogo == "quiz" and jogo:
            pergunta = jogo["pergunta"]
            detalhe = f"\n📝 A resposta era: <b>{pergunta['opcoes'][pergunta['certa']]}</b>"
        dicionario.pop(chat_id, None)
        liberar_jogo(chat_id, nome_jogo)
        bot.reply_to(mensagem, f"🔄 Jogo de <b>{nome_jogo.upper()}</b> resetado!{detalhe}", parse_mode="HTML")
        return

    if texto_upper in [".MENU", ".AJUDA", "/AJUDA", "/MENU"]:
        menu = (
            "👑 <b>PAINEL DE JOGOS E PONTUAÇÃO DA SANTOS</b> 👑\n\n"
            "🏆 <code>.top</code> ou <code>.ranking</code> - Ranking Semanal\n"
            "💀 <code>.forca</code> - Jogo da Forca (+20 pts)\n"
            "   ↳ Escolha uma categoria e mande letras; cada erro completa o bonequinho.\n"
            "⚽ <code>.fut</code> - Pênalti em Dupla (+20 pts)\n"
            "   ↳ Um chuta, outro defende; escolham os lados nos botões.\n"
            "✊ <code>.ppt</code> ou <code>/ppt</code> - Pedra, Papel e Tesoura\n"
            "   ↳ Clique em participar e escolha sua jogada quando a partida começar.\n"
            "❤️ <code>.caça</code> - Caça-Palavras (+15 pts)\n"
            "   ↳ Escolha texto ou imagem e digite as palavras encontradas.\n"
            "❤️ <code>.cruzada</code> - Palavras Cruzadas (+15 pts)\n"
            "   ↳ Descubra as palavras; letras são reveladas aos poucos automaticamente.\n"
            "❌⭕ <code>.velha</code> - Jogo da Velha (+25 pts)\n"
            "   ↳ Duas pessoas entram e cada uma joga apenas no seu turno.\n"
            "🧠 <code>.quiz</code> - Perguntas com botões (+15 pts)\n"
            "   ↳ Clique na alternativa correta antes das outras pessoas.\n"
            "✌️ <code>.parimpar</code> - Par ou Ímpar (+20 pts)\n"
            "   ↳ Duas pessoas escolhem paridade e depois um número de 0 a 5.\n"
            "🪙 <code>.moeda</code> - Cara ou Coroa (+5 pts)\n"
            "   ↳ Clique em uma opção; a rodada tem um único sorteio e vencedor.\n"
            "🧠 <code>.memo</code> - Jogo da Memória (+10 pts por par)\n"
            "   ↳ Duas pessoas entram; vire duas cartas no seu turno e encontre os pares.\n"
            "💘 <code>.amor</code> - Termômetro do amor\n"
            "   ↳ Mostra uma porcentagem recreativa de sintonia.\n"
            "🍀 <code>.sorte</code> - Termômetro da sorte\n"
            "   ↳ Mostra uma porcentagem recreativa de sorte do momento.\n"
            "💡 <code>.conselho</code> - Conselho do dia\n"
            "   ↳ Receba uma mensagem curta para refletir.\n"
            "🔮 <code>.signo</code> ou <code>.horoscopo</code> - Horóscopo do dia\n"
            "   ↳ Digite o signo com ponto para receber a previsão.\n"
            "🚢 <code>.naval</code> - Batalha Naval (+30 pts)\n"
            "   ↳ Duas pessoas entram, a Santos sorteia a frota de cada uma e vocês atacam o tabuleiro por botões.\n"
            "🎭 <code>.quem</code> - Quem Sou Eu (+15 pts)\n"
            "   ↳ Leia a dica e digite o palpite; a Santos confirma se acertou.\n"
            "🎯 <code>.misterio</code> - Mistério da Santos (+20 pts)\n"
            "   ↳ Descubra a palavra escondida a partir de uma pista curiosa.\n"
            "⚡ <code>.rapido</code> - Jogo Rápido (+15 pts)\n"
            "   ↳ O grupo responde em um impulso e quem acertar rápido ganha.\n"
            "✅ <code>.vf</code> - Verdadeiro ou Falso (+15 pts)\n"
            "   ↳ Responda rápido com verdadeiro ou falso e ganhe pontos.\n"
            "🕵️ <code>.oculto</code> - Palavra Oculta (+20 pts)\n"
            "   ↳ Resolva a pista e descubra a palavra secreta.\n"
            "🧩 <code>.charada</code> - Charada da Santos (+20 pts)\n"
            "   ↳ Clássico «o que é, o que é» pra decifrar.\n"
            "🧩 <code>.emoji</code> - Adivinhe o Emoji (+15 pts)\n"
            "   ↳ Interprete a combinação de emojis e digite a resposta simples.\n"
            "🛑 <code>.stop</code> - Stop relâmpago (+25 pts)\n"
            "   ↳ Use a letra sorteada e envie nome, animal, comida e objeto.\n"
            "🥔 <code>.batata</code> - Batata Quente\n"
            "   ↳ Reúna o grupo, comece e passe a bomba até ela estourar.\n"
            "🕵️ <code>.detetive</code> - Papéis secretos e votação\n"
            "   ↳ Reúna 3+, veja seu papel no alerta, investigue e vote no assassino.\n"
            "� <code>santos solta o bicho</code> - Só admin/dono\n"
            "   ↳ A Santos solta um sticker de bicho e o grupo manda áudio de até 5s imitando.\n"
            "�🔧 <code>.load[jogo]</code> - Reseta um jogo travado (ex: <code>.loadforca</code>)\n"
            "✨ <i>Interaja no chat para conversar com a Santos!</i>"
        )
        bot.reply_to(mensagem, menu, parse_mode="HTML")
        return

    if texto_upper in [".TOP", ".RANKING"]:
        bot.reply_to(mensagem, gerar_texto_top(chat_id), parse_mode="HTML")
        return

    if texto_upper in [".PPT", "/PPT"]:
        if jogo_ocupado(chat_id, "ppt"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        if chat_id in JOGOS_PPT and JOGOS_PPT[chat_id]['status'] == 'LOBBY':
            return
        travar_jogo(chat_id, "ppt")
        JOGOS_PPT[chat_id] = {"status": "LOBBY", "players": []}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✊✋✌️ Entrar na Batalha", callback_data="ppt_join"))
        msg = bot.send_message(
            chat_id,
            "✊ <b>BATALHA DE PEDRA, PAPEL E TESOURA</b> ✌️\n\n👥 Participantes (0/6):\n_Ninguém entrou ainda_\n\n⏳ <i>Clique no botão para entrar! Se ninguém entrar em 30s, você jogará contra o robô.</i>",
            reply_markup=markup, parse_mode="HTML",
        )
        threading.Thread(target=timer_lobby_ppt, args=(chat_id, msg.message_id), daemon=True).start()
        return

    if texto_upper == ".FORCA":
        if jogo_ocupado(chat_id, "forca"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        if chat_id in JOGOS_FORCA:
            return
        travar_jogo(chat_id, "forca")
        JOGOS_FORCA[chat_id] = {"status": "CATEGORIA"}
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🐶 Animais", callback_data="forca_cat_animais"),
            InlineKeyboardButton("🍕 Comidas", callback_data="forca_cat_comidas"),
            InlineKeyboardButton("🎬 Filmes", callback_data="forca_cat_filmes"),
            InlineKeyboardButton("🎵 Música", callback_data="forca_cat_musica"),
            InlineKeyboardButton("🌿 Natureza", callback_data="forca_cat_natureza"),
            InlineKeyboardButton("🎲 Aleatório", callback_data="forca_cat_aleatorio"),
        )
        msg = bot.send_message(chat_id, "💀 <b>FORCA DA SANTOS</b> 💀\n\nEscolha uma categoria para começar:", reply_markup=markup, parse_mode="HTML")
        JOGOS_FORCA[chat_id]["msg_id"] = msg.message_id
        return

    if chat_id in JOGOS_FORCA and JOGOS_FORCA[chat_id]["status"] == "ativo":
        jogo = JOGOS_FORCA[chat_id]
        if texto_upper == jogo["palavra"]:
            jogo["status"] = "encerrado"
            adicionar_pontos(chat_id, user_id, user_name, 20)
            bot.edit_message_media(InputMediaPhoto(gerar_imagem_forca(jogo["erros"]), caption=f"🔥 <b>OLHA O BRABO!</b> {user_name} gabaritou e acertou a palavra <b>{jogo['palavra']}</b>! Mandou demais! (+20 pts)", parse_mode="HTML"), chat_id, jogo["msg_id"])
            JOGOS_FORCA.pop(chat_id, None)
            liberar_jogo(chat_id, "forca")
            return
        if len(texto) == 1 and texto.isalpha():
            letra = texto_upper
            if letra in jogo["certas"] or letra in jogo["erradas"]:
                return
            if letra in jogo["palavra"]:
                jogo["certas"].add(letra)
            else:
                jogo["erradas"].add(letra)
                jogo["erros"] += 1
            mascara = " ".join([l if l in jogo["certas"] else "_" for l in jogo["palavra"]])
            if all(l in jogo["certas"] for l in jogo["palavra"]):
                jogo["status"] = "encerrado"
                adicionar_pontos(chat_id, user_id, user_name, 20)
                bot.edit_message_media(InputMediaPhoto(gerar_imagem_forca(jogo["erros"]), caption=f"🚀 <b>QUE ISSO, FAMÍLIA?!</b> {user_name} fechou a forca com a palavra <b>{jogo['palavra']}</b>! Brabo demais! (+20 pts)", parse_mode="HTML"), chat_id, jogo["msg_id"])
                JOGOS_FORCA.pop(chat_id, None)
                liberar_jogo(chat_id, "forca")
                return
            if jogo["erros"] >= 6:
                jogo["status"] = "encerrado"
                bot.edit_message_media(InputMediaPhoto(gerar_imagem_forca(6), caption=f"💀 <b>DEU RUIM!</b> O boneco foi de arrasta pra cima... A palavra era <b>{jogo['palavra']}</b>!", parse_mode="HTML"), chat_id, jogo["msg_id"])
                JOGOS_FORCA.pop(chat_id, None)
                liberar_jogo(chat_id, "forca")
                return
            bot.edit_message_media(InputMediaPhoto(gerar_imagem_forca(jogo["erros"]), caption=f"💀 <b>FORCA</b>\nPalavra: <code>{mascara}</code>\nErros: {jogo['erros']}/6", parse_mode="HTML"), chat_id, jogo["msg_id"])
            return

    if texto_upper == ".FUT":
        if jogo_ocupado(chat_id, "penalti"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "penalti")
        JOGOS_PENALTI[chat_id] = {"status": "LOBBY", "players": []}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⚽ Entrar na Disputa", callback_data="penalti_join"))
        bot.send_message(chat_id, "⚽ <b>PÊNALTI EM DUPLA</b>\nPreciso de 2 jogadores (Batedor e Goleiro)!", reply_markup=markup, parse_mode="HTML")
        return

    # CAÇA-PALAVRAS - igual ao Bil: escolhe o modo (texto ou imagem) antes de começar
    if texto_upper in [".CAÇA", ".CACA"]:
        if jogo_ocupado(chat_id, "caca"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "caca")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📝 TEXTO", callback_data="caca_modo_texto"),
            InlineKeyboardButton("🖼️ IMAGEM", callback_data="caca_modo_imagem"),
        )
        bot.send_message(chat_id, "🧩 <b>CAÇA-PALAVRAS</b>\n\n🎛️ Escolha o modo do caça-palavras:", reply_markup=markup, parse_mode="HTML")
        return

    if chat_id in JOGOS_CACA and JOGOS_CACA[chat_id].get("status") == "ativo":
        jogo = JOGOS_CACA[chat_id]
        if texto_upper in jogo["palavras_info"] and not jogo["palavras_info"][texto_upper]["encontrada"]:
            jogo["palavras_info"][texto_upper]["encontrada"] = True
            adicionar_pontos(chat_id, user_id, user_name, 15)

            bot.reply_to(
                mensagem,
                f"✅ <b>{user_name}</b> encontrou uma palavra! 🏆\n\n➥ <b>{texto_upper}</b> (+15 pts)",
                parse_mode="HTML",
            )

            try:
                if jogo["modo"] == "texto":
                    bot.edit_message_text(gerar_grid_texto_caca(chat_id), chat_id, jogo["msg_id"], parse_mode="HTML")
                else:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_caca(chat_id), caption=gerar_legenda_caca(chat_id), parse_mode="HTML"),
                        chat_id=chat_id, message_id=jogo["msg_id"],
                    )
            except Exception:
                pass

            if all(p["encontrada"] for p in jogo["palavras_info"].values()):
                bot.send_message(chat_id, "🏆 <b>PARABÉNS! Todas as palavras do Caça-Palavras foram encontradas!</b>", parse_mode="HTML")
                JOGOS_CACA.pop(chat_id, None)
                liberar_jogo(chat_id, "caca")
            return

    if texto_upper == ".CRUZADA":
        if jogo_ocupado(chat_id, "cruzada"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "cruzada")
        lista = [{"palavra": p, "reveladas": [], "encontrada": False} for p in sortear_cruzada(chat_id)]
        jogo = {"lista": lista, "status": "ativo"}
        JOGOS_CRUZADA[chat_id] = jogo
        msg = bot.send_photo(chat_id, gerar_imagem_cruzada(jogo), caption=montar_texto_cruzada(jogo), parse_mode="HTML")
        jogo["msg_id"] = msg.message_id
        return

    if chat_id in JOGOS_CRUZADA and JOGOS_CRUZADA[chat_id]["status"] == "ativo":
        jogo = JOGOS_CRUZADA[chat_id]
        for item in jogo["lista"]:
            if item["palavra"] == texto_upper and not item["encontrada"]:
                item["encontrada"] = True
                item["reveladas"] = list(range(len(item["palavra"])))
                adicionar_pontos(chat_id, user_id, user_name, 15)
                jogo.setdefault("pontuacao", {})[user_id] = {
                    "nome": user_name,
                    "pontos": jogo.setdefault("pontuacao", {}).get(user_id, {}).get("pontos", 0) + 15,
                }

                frases_cruzada = [
                    f"🔥 <b>AMASSOU!</b> {user_name} acertou a cruzada <b>{texto_upper}</b> com estilo! Visão braba! 🎯 (+15 pts)",
                    f"🏆 <b>MONSTRO!</b> {user_name} mandou a palavra <b>{texto_upper}</b> pra dentro! Respeita a tropa! 🚀 (+15 pts)",
                ]
                bot.reply_to(mensagem, escolher_sem_repetir("cruzada_acerto", frases_cruzada), parse_mode="HTML")

                try:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_cruzada(jogo), caption=montar_texto_cruzada(jogo), parse_mode="HTML"),
                        chat_id=chat_id, message_id=jogo["msg_id"],
                    )
                except Exception:
                    pass
                if all(i["encontrada"] for i in jogo["lista"]):
                    jogo["status"] = "encerrado"
                    placar = sorted(jogo.get("pontuacao", {}).values(), key=lambda jogador: jogador["pontos"], reverse=True)
                    linhas_placar = [f"🏆 <b>{jogador['nome']}</b> — {jogador['pontos']} pts" for jogador in placar]
                    texto_final = (
                        "💗 <b>CRUZADA ENCERRADA</b> 💗\n\n"
                        "🚨 Todas as letras foram reveladas!\n\n"
                        "➜ <b>PONTUAÇÃO DA PARTIDA</b>\n"
                        + ("\n".join(linhas_placar) if linhas_placar else "Ninguém pontuou nesta rodada.")
                    )
                    bot.send_message(chat_id, texto_final, parse_mode="HTML")
                    JOGOS_CRUZADA.pop(chat_id, None)
                    liberar_jogo(chat_id, "cruzada")
                return

    if texto_upper == ".VELHA":
        if jogo_ocupado(chat_id, "velha"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "velha")
        JOGOS_VELHA[chat_id] = {"status": "LOBBY", "players": [], "board": ["➖"] * 9, "turn": 0}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("#️⃣ JOGAR", callback_data="velha_join"))
        bot.send_photo(chat_id, gerar_imagem_velha_lobby(), caption="❌⭕ <b>JOGO DA VELHA</b> (Valendo 25 pts)", reply_markup=markup, parse_mode="HTML")
        return

    if texto_upper == ".QUIZ":
        if jogo_ocupado(chat_id, "quiz"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_quiz(chat_id)
        return

    if texto_upper == ".MISTERIO":
        if jogo_ocupado(chat_id, "misterio"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_misterio(chat_id)
        return

    if texto_upper == ".RAPIDO":
        if jogo_ocupado(chat_id, "rapido"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_rapido(chat_id)
        return

    if texto_upper in [".VF", ".VERDADEIRO", ".FALSO"]:
        if jogo_ocupado(chat_id, "vf"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_vf(chat_id)
        return

    if texto_upper == ".OCULTO":
        if jogo_ocupado(chat_id, "oculto"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_oculto(chat_id)
        return

    if texto_upper == ".CHARADA":
        if jogo_ocupado(chat_id, "charada"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_charada(chat_id)
        return

    if texto_upper in [".PARIMPAR", ".PI"]:
        if jogo_ocupado(chat_id, "parimpar"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "parimpar")
        JOGOS_PARIMPAR[chat_id] = {"status": "LOBBY", "players": []}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✌️ Entrar", callback_data="pi_join"))
        bot.send_message(chat_id, "✌️ <b>PAR OU ÍMPAR</b> ✌️\nPreciso de 2 jogadores!", reply_markup=markup, parse_mode="HTML")
        return

    if texto_upper == ".MOEDA":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🪙 Cara", callback_data="moeda_cara"),
            InlineKeyboardButton("🪙 Coroa", callback_data="moeda_coroa"),
        )
        msg = bot.send_message(chat_id, "🪙 <b>CARA OU COROA</b> 🪙\nEscolha e veja se acerta! (+5 pts)", reply_markup=markup, parse_mode="HTML")
        JOGOS_MOEDA[(chat_id, msg.message_id)] = {"encerrado": False}
        return

    if texto_upper == ".BATATA":
        if jogo_ocupado(chat_id, "batata"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "batata")
        JOGOS_BATATA[chat_id] = {"status": "LOBBY", "players": []}
        bot.send_message(chat_id, texto_lobby_batata(JOGOS_BATATA[chat_id]), reply_markup=teclado_lobby_batata(JOGOS_BATATA[chat_id]), parse_mode="HTML")
        return

    if texto_upper == ".DETETIVE":
        if jogo_ocupado(chat_id, "detetive"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "detetive")
        JOGOS_DETETIVE[chat_id] = {"status": "LOBBY", "players": [], "local": escolher_sem_repetir("local_detetive", LOCAIS_DETETIVE), "votos": []}
        bot.send_message(chat_id, texto_lobby_detetive(JOGOS_DETETIVE[chat_id]), reply_markup=teclado_lobby_detetive(), parse_mode="HTML")
        return

    if texto_upper == ".NAVAL":
        if jogo_ocupado(chat_id, "naval"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "naval")
        JOGOS_NAVAL[chat_id] = {"status": "LOBBY", "players": [], "navios": {}, "atacados": {}, "turno": 0, "msg_id": None}
        bot.send_message(chat_id, texto_lobby_naval(JOGOS_NAVAL[chat_id]), reply_markup=teclado_lobby_naval(), parse_mode="HTML")
        return

    if texto_upper in [".EMOJI", ".ADIVINHEEMOJI"]:
        if jogo_ocupado(chat_id, "emoji"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_emoji(chat_id)
        return

    if texto_upper == ".QUEM":
        if jogo_ocupado(chat_id, "quem"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_quem(chat_id)
        return

    if texto_upper == ".STOP":
        if jogo_ocupado(chat_id, "stop"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        iniciar_stop(chat_id)
        return

    if chat_id in JOGOS_STOP and JOGOS_STOP[chat_id]["status"] == "ativo":
        jogo = JOGOS_STOP[chat_id]
        respostas = [parte.strip() for parte in texto_upper.replace(";", ",").replace("\n", ",").split(",") if parte.strip()]
        if len(respostas) == 4 and all(resposta.startswith(jogo["letra"]) for resposta in respostas):
            adicionar_pontos(chat_id, user_id, user_name, 25)
            bot.reply_to(mensagem, f"🛑 <b>STOP!</b> {user_name} venceu a rodada! (+25 pts)", parse_mode="HTML")
            JOGOS_STOP.pop(chat_id, None)
            liberar_jogo(chat_id, "stop")
        elif len(respostas) >= 4:
            bot.reply_to(mensagem, f"👀 Algumas respostas não começam com <b>{jogo['letra']}</b>. Tenta novamente!", parse_mode="HTML")
        return

    if texto_upper == ".MEMO":
        if jogo_ocupado(chat_id, "memoria"):
            aviso_jogo_ocupado(mensagem, chat_id)
            return
        travar_jogo(chat_id, "memoria")
        simbolos = ["🌸", "🦋", "💎", "🌙", "🍓", "🦄", "🍀", "🎀", "🍉", "🧁"] * 2
        random.shuffle(simbolos)
        JOGOS_MEMORIA[chat_id] = {"cards": simbolos, "revealed": [], "matched": set(), "players": [], "status": "LOBBY", "turn": 0}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Participar", callback_data="memo_join"))
        msg = bot.send_message(chat_id, "🧠 <b>JOGO DA MEMÓRIA</b> 🧠\n\n👥 <b>2 jogadores</b>\n🎯 Encontre os pares mais rápido\n🏆 Quem fizer mais pontos vence\n\n👇 Clique para participar!", reply_markup=markup, parse_mode="HTML")
        JOGOS_MEMORIA[chat_id]["msg_id"] = msg.message_id
        return

    if texto_upper == ".AMOR":
        percentual = random.randint(35, 100)
        frases = ["O coração deu uma piscadinha!", "Tem química no ar hoje!", "Vai com calma, mas vai sorrindo!", "O cupido está trabalhando!"]
        bot.reply_to(mensagem, f"💘 <b>TERMÔMETRO DO AMOR</b> 💘\n\n{percentual}% de sintonia!\n<i>{escolher_sem_repetir('amor', frases)}</i>", parse_mode="HTML")
        return

    if texto_upper == ".SORTE":
        percentual = random.randint(35, 100)
        frases = ["Hoje é dia de confiar na sua intuição.", "Pequenas oportunidades podem render boas histórias.", "Olhos abertos: uma surpresa pode aparecer.", "Seu astral está brilhando hoje!"]
        bot.reply_to(mensagem, f"🍀 <b>TERMÔMETRO DA SORTE</b> 🍀\n\nSua sorte está em <b>{percentual}%</b>!\n<i>{escolher_sem_repetir('sorte', frases)}</i>", parse_mode="HTML")
        return

    if texto_upper == ".CONSELHO":
        bot.reply_to(mensagem, f"💡 <b>CONSELHO DO DIA DA SANTOS</b> 💡\n\n<i>{escolher_sem_repetir('conselho', CONSELHOS_DIA)}</i>\n\n💗 Guarda isso com carinho.", parse_mode="HTML")
        return

    if chat_id in JOGOS_EMOJI:
        jogo = JOGOS_EMOJI[chat_id]
        if normalizar_resposta(texto) == normalizar_resposta(jogo["resposta"]):
            adicionar_pontos(chat_id, user_id, user_name, 15)
            bot.reply_to(mensagem, f"🎉 <b>{user_name}</b> acertou! Era <b>{jogo['resposta']}</b>! (+15 pts)", parse_mode="HTML")
            JOGOS_EMOJI.pop(chat_id, None)
            liberar_jogo(chat_id, "emoji")
        return

    if chat_id in JOGOS_QUEM:
        jogo = JOGOS_QUEM[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        aceitas = RESPOSTAS_QUEM_SOU.get(jogo["resposta"], set())
        if resposta_normalizada in {normalizar_resposta(resposta) for resposta in aceitas}:
            adicionar_pontos(chat_id, user_id, user_name, 15)
            resposta_correta = sorted(aceitas, key=lambda item: len(item))[0].upper()
            bot.reply_to(mensagem, f"🎭 <b>{user_name}</b> acertou! A resposta era <b>{resposta_correta}</b> (+15 pts)", parse_mode="HTML")
            JOGOS_QUEM.pop(chat_id, None)
            liberar_jogo(chat_id, "quem")
        else:
            bot.reply_to(mensagem, f"👀 {user_name}, não foi dessa vez! Continua tentando.", parse_mode="HTML")
        return

    if chat_id in JOGOS_MISTERIO:
        jogo = JOGOS_MISTERIO[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        if resposta_normalizada in jogo["respostas"]:
            adicionar_pontos(chat_id, user_id, user_name, 20)
            bot.reply_to(mensagem, f"🎯 <b>{user_name}</b> resolveu o mistério! (+20 pts)", parse_mode="HTML")
            JOGOS_MISTERIO.pop(chat_id, None)
            liberar_jogo(chat_id, "misterio")
        return

    if chat_id in JOGOS_RAPIDO:
        jogo = JOGOS_RAPIDO[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        if resposta_normalizada in jogo["respostas"]:
            adicionar_pontos(chat_id, user_id, user_name, 15)
            bot.reply_to(mensagem, f"⚡ <b>{user_name}</b> acertou no impulso! (+15 pts)", parse_mode="HTML")
            JOGOS_RAPIDO.pop(chat_id, None)
            liberar_jogo(chat_id, "rapido")
        return

    if chat_id in JOGOS_VF:
        jogo = JOGOS_VF[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        if resposta_normalizada in {"verdadeiro", "falso"}:
            resposta_usuario = "verdadeiro" if resposta_normalizada == "verdadeiro" else "falso"
            acerto = (resposta_usuario == "verdadeiro" and jogo["resposta"] is True) or (resposta_usuario == "falso" and jogo["resposta"] is False)
            if acerto:
                adicionar_pontos(chat_id, user_id, user_name, 15)
                bot.reply_to(mensagem, f"✅ <b>{user_name}</b> acertou! (+15 pts)", parse_mode="HTML")
            else:
                bot.reply_to(mensagem, f"❌ <b>{user_name}</b> errou. A resposta correta era <b>{'verdadeiro' if jogo['resposta'] else 'falso'}</b>.", parse_mode="HTML")
            JOGOS_VF.pop(chat_id, None)
            liberar_jogo(chat_id, "vf")
        return

    if chat_id in JOGOS_OCULTO:
        jogo = JOGOS_OCULTO[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        if resposta_normalizada == jogo["resposta"]:
            adicionar_pontos(chat_id, user_id, user_name, 20)
            bot.reply_to(mensagem, f"🕵️ <b>{user_name}</b> descobriu a palavra oculta! (+20 pts)", parse_mode="HTML")
            JOGOS_OCULTO.pop(chat_id, None)
            liberar_jogo(chat_id, "oculto")
        return

    if chat_id in JOGOS_CHARADA:
        jogo = JOGOS_CHARADA[chat_id]
        resposta_normalizada = normalizar_resposta(texto)
        if resposta_normalizada in jogo["respostas"]:
            adicionar_pontos(chat_id, user_id, user_name, 20)
            bot.reply_to(mensagem, f"🧩 <b>{user_name}</b> decifrou a charada! (+20 pts)", parse_mode="HTML")
            JOGOS_CHARADA.pop(chat_id, None)
            liberar_jogo(chat_id, "charada")
        return

    if texto_upper in [".SIGNO", ".MEUSIGNO", ".HOROSCOPO"]:
        signo = escolher_sem_repetir("signo", LISTA_SIGNOS_VALIDOS)
        txt = gerar_texto_ia(
            f"Gere uma previsão curta e positiva para o signo {signo}, em português do Brasil, falando de energia, trabalho, relações e conselho prático. Use no máximo 3 frases, sem mencionar inteligência artificial, apostas ou promessas de dinheiro.",
            "O dia favorece conversas sinceras, foco nas tarefas e escolhas feitas com calma.",
        )
        bot.reply_to(mensagem, montar_horoscopo(signo, txt), parse_mode="HTML")
        return

    limpo = texto_upper.replace(".", "")
    if limpo in LISTA_SIGNOS_VALIDOS:
        txt = gerar_texto_ia(
            f"Gere uma previsão curta e positiva para o signo {limpo}, em português do Brasil, falando de energia, trabalho, relações e conselho prático. Use no máximo 3 frases, sem mencionar inteligência artificial, apostas ou promessas de dinheiro.",
            "Sua intuição está afiada hoje; organize as prioridades e escolha com tranquilidade.",
        )
        bot.reply_to(mensagem, montar_horoscopo(limpo, txt), parse_mode="HTML")
        return

    # Handlers de jogo acima já retornam quando consomem a mensagem; se chegou aqui, nenhum jogo travou o texto.
    for g, dados in GATILHOS_PLATAFORMAS.items():
        if g in texto_upper:
            frase = escolher_sem_repetir("plataforma_" + g, [frase.format(g=g) for frase in FRASES_PLATAFORMA])
            if dados.get('file_id'):
                bot.send_photo(chat_id, dados['file_id'], caption=f"{frase}\n\n{dados['url']}", parse_mode="HTML")
            else:
                bot.reply_to(mensagem, f"{frase}\n\n{dados['url']}", parse_mode="HTML")
            return

    saudacao = next((saudacao for saudacao in RESPOSTAS_SAUDACAO if saudacao in texto_upper), None)
    if saudacao:
        bot.reply_to(mensagem, escolher_sem_repetir("saudacao_" + saudacao, RESPOSTAS_SAUDACAO[saudacao]))
        return

    if random.random() < 0.18 and CONFIG_GRUPOS.get(chat_id, {}).get("auto_reacoes", True):
        try:
            bot.set_message_reaction(chat_id, mensagem.message_id, [ReactionTypeEmoji(random.choice(["❤️", "😂", "🔥", "👏"]))])
            enviar_sticker_interacao(chat_id)
        except Exception:
            pass
        return

    if CONFIG_GRUPOS.get(chat_id, {}).get("auto_ia", True) and (random.random() < 0.45 or "SANTOS" in texto_upper):
        resposta_ia = gerar_texto_ia(
            f"Você é a Santos, assistente de resenha de um grupo de Telegram. Seja bem extrovertida, brincalhona e use gírias como 'visão', 'marcha', 'tropa'. Responda curto ao que {user_name} disse: '{texto}'",
            "",
        )
        if resposta_ia:
            bot.reply_to(mensagem, resposta_ia)
            enviar_sticker_interacao(chat_id)


print("Santos - versão corrigida (trava de jogo + variáveis de ambiente)")
threading.Thread(target=rotina_jogos_automaticos, daemon=True).start()
bot.infinity_polling()
