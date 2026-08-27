import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaAnimation
import google.generativeai as genai
import random
import datetime
import time
import threading
import json
import io
import string
import math
import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

# === 1. TOKENS E CHAVES (nunca deixe valores reais direto no código) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
GIPHY_API_KEY = os.environ.get("GIPHY_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_KEY:
    raise RuntimeError(
        "Defina TELEGRAM_TOKEN e GEMINI_KEY como variáveis de ambiente (veja .env.example) antes de rodar o bot."
    )

bot = telebot.TeleBot(TELEGRAM_TOKEN)

genai.configure(api_key=GEMINI_KEY)
generation_config = {"temperature": 0.7, "max_output_tokens": 300}
model_ia = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=generation_config)


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
CONFIG_GRUPOS = {}
PONTOS_SEMANAL = {}

JOGOS_CACA = {}
JOGOS_VELHA = {}
JOGOS_MEMORIA = {}
JOGOS_CRUZADA = {}
JOGOS_PPT = {}
JOGOS_PENALTI = {}
JOGOS_FORCA = {}
JOGOS_QUIZ = {}
JOGOS_PARIMPAR = {}

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
]

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
    bot.reply_to(
        mensagem,
        f"⚠️ Já tem um jogo de <b>{atual.upper()}</b> rolando aqui! Espere terminar ou use <code>.load{atual}</code> pra resetar.",
        parse_mode="HTML",
    )


ARQUIVO_GATILHOS = "gatilhos_plataformas.json"


def carregar_gatilhos():
    try:
        with open(ARQUIVO_GATILHOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_gatilhos(dados):
    with open(ARQUIVO_GATILHOS, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)


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

# Igual ao Bil: só entram palavras com 4+ letras no caça-palavras
POOL_PALAVRAS_CACA = sorted({p for tema in BANCO_TEMAS_CACA for p in tema if len(p) >= 4})
QTD_PALAVRAS_CACA = 5


def adicionar_pontos(chat_id, user_id, nome, quantidade=10):
    if chat_id not in PONTOS_SEMANAL:
        PONTOS_SEMANAL[chat_id] = {}
    if user_id not in PONTOS_SEMANAL[chat_id]:
        PONTOS_SEMANAL[chat_id][user_id] = {"nome": nome, "pontos": 0}
    PONTOS_SEMANAL[chat_id][user_id]["pontos"] += quantidade
    PONTOS_SEMANAL[chat_id][user_id]["nome"] = nome


def gerar_texto_top(chat_id):
    if chat_id not in PONTOS_SEMANAL or not PONTOS_SEMANAL[chat_id]:
        return "🏆 <b>RANKING SEMANAL DA SANTOS</b> 🏆\n\nNinguém pontuou essa semana ainda!"
    ranking = sorted(PONTOS_SEMANAL[chat_id].values(), key=lambda x: x["pontos"], reverse=True)
    medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    texto = "🏆 <b>RANKING SEMANAL DE PONTUAÇÃO</b> 🏆\n\n"
    for idx, jogador in enumerate(ranking[:10]):
        icone = medalhas[idx] if idx < len(medalhas) else "🎖️"
        texto += f"{icone} <b>{jogador['nome']}</b> — <code>{jogador['pontos']} pts</code>\n"
    texto += "\n✨ <i>Zera automaticamente todo domingo às 17h!</i>"
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
    rows, cols = 12, 12
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
    cell, margin = 32, 40
    img = Image.new('RGB', (cols * cell + margin * 2, rows * cell + margin * 2), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    for p, p_data in info.items():
        if p_data["encontrada"]:
            for (r, c) in p_data["coords"]:
                x, y = margin + c * cell, margin + r * cell
                draw.rectangle([x, y, x + cell, y + cell], fill=(255, 105, 180))

    for r in range(rows):
        for c in range(cols):
            x, y = margin + c * cell, margin + r * cell
            draw.text((x + 10, y + 6), grid[r][c], fill=(255, 244, 250), font=font)
            draw.rectangle([x, y, x + cell, y + cell], outline=(90, 60, 95), width=1)

    bio = io.BytesIO()
    bio.name = 'caca.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def gerar_legenda_caca(chat_id):
    jogo = JOGOS_CACA[chat_id]
    info = jogo["palavras_info"]
    # Nunca mostrar a palavra em texto puro: só o tamanho (senão vira "copia e cola", não caça)
    lista_str = ", ".join(
        [f"<b>{p}</b> ✅" if d["encontrada"] else " ".join(["_"] * len(p)) for p, d in info.items()]
    )
    return (
        "🧩 <b>CAÇA-PALAVRAS</b> 🧩\n\n"
        f"🔍 Encontre as {len(info)} palavras escondidas\n"
        "📏 Mínimo de 4 letras\n"
        "🔄 Existem palavras invertidas\n\n"
        f"📋 {lista_str}\n\n"
        "🍀 <i>Boa sorte!</i>"
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


def gerar_imagem_cruzada(jogo):
    img = Image.new('RGB', (650, 420), color=(45, 18, 48))
    draw = ImageDraw.Draw(img)
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 22)
        font_caixa = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_caixa = ImageFont.load_default()

    draw.text((35, 25), "❤️  PALAVRAS CRUZADAS  ❤️", fill=(255, 133, 189), font=font_titulo)

    y_offset = 75
    box_size = 32
    box_margin = 8

    for idx, item in enumerate(jogo["lista"]):
        palavra = item["palavra"]
        reveladas = item["reveladas"]

        draw.text((35, y_offset + 4), f"{idx + 1}.", fill=(230, 200, 220), font=font_caixa)

        x_offset = 80
        for i, letra in enumerate(palavra):
            if item["encontrada"] or (i in reveladas):
                cor_caixa = (255, 105, 180) if item["encontrada"] else (110, 60, 110)
                cor_texto = (255, 244, 250)
                char_exibido = letra
            else:
                cor_caixa = (60, 30, 60)
                cor_texto = (200, 160, 190)
                char_exibido = "_"

            draw.rectangle([x_offset, y_offset, x_offset + box_size, y_offset + box_size], fill=cor_caixa, outline=(140, 80, 130), width=2)
            draw.text((x_offset + 9, y_offset + 5), char_exibido, fill=cor_texto, font=font_caixa)
            x_offset += box_size + box_margin

        y_offset += box_size + 14

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


@bot.message_handler(content_types=['photo'])
def capturar_foto_pv(mensagem):
    if mensagem.chat.type == "private":
        ULTIMA_FOTO_PV[mensagem.chat.id] = mensagem.photo[-1].file_id
        bot.reply_to(mensagem, "🖼️ Foto guardadinha! Agora me manda: <code>/addlink [gatilho] [url]</code>\n\n<i>O gatilho é a palavra que, quando alguém falar no grupo, eu solto esse link automaticamente 😉</i>", parse_mode="HTML")


def _painel_privado_texto():
    return (
        "👑 <b>PAINEL PRIVADO DA SANTOS</b> 👑\n\n"
        "Aqui você controla os links de plataforma que eu solto lá no grupo quando alguém fala a palavra-gatilho.\n\n"
        "🖼️ <b>1.</b> Me manda a foto/banner da plataforma\n"
        "➕ <b>2.</b> <code>/addlink [gatilho] [url]</code> — salva o link\n"
        "   <i>ex: /addlink URBEPG https://urbepg.vip/?id=123</i>\n"
        "📋 <b>3.</b> <code>/links</code> — vê tudo que já cadastrei\n"
        "🗑️ <b>4.</b> <code>/removerlink [gatilho]</code> — remove um link (ou clica no botão em /links)\n\n"
        "✨ <i>O gatilho é a palavra que, quando mencionada no grupo, eu jogo o link automático com uma frase diferente toda vez!</i>"
    )


@bot.message_handler(commands=['addlink', 'removerlink', 'links', 'start', 'help', 'ajuda'])
def comandos_pv_geral(mensagem):
    if mensagem.chat.type != "private":
        return
    texto = mensagem.text.strip()
    texto_lower = texto.lower()

    if texto_lower.startswith(('/start', '/help', '/ajuda')):
        bot.reply_to(mensagem, _painel_privado_texto(), parse_mode="HTML")
        return

    if texto_lower.startswith("/addlink"):
        partes = texto.split(maxsplit=2)
        if len(partes) < 3:
            bot.reply_to(
                mensagem,
                "⚠️ Faltou informação! Usa assim: <code>/addlink [gatilho] [url]</code>\n<i>ex: /addlink URBEPG https://urbepg.vip/?id=123</i>",
                parse_mode="HTML",
            )
            return
        gatilho, url = partes[1].upper(), partes[2]
        file_id = ULTIMA_FOTO_PV.get(mensagem.chat.id, "")
        GATILHOS_PLATAFORMAS[gatilho] = {"url": url, "file_id": file_id}
        salvar_gatilhos(GATILHOS_PLATAFORMAS)
        preview = random.choice(FRASES_PLATAFORMA).format(g=gatilho)
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


@bot.callback_query_handler(func=lambda call: True)
def botoes_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    user_name = call.from_user.first_name or "Membro"
    user_id = call.from_user.id

    if data.startswith("moeda_"):
        escolha = data.replace("moeda_", "")
        resultado = random.choice(["cara", "coroa"])
        if resultado == escolha:
            adicionar_pontos(chat_id, user_id, user_name, 5)
            bot.answer_callback_query(call.id, f"🪙 Deu {resultado.upper()}! Você acertou! (+5 pts)", show_alert=True)
        else:
            bot.answer_callback_query(call.id, f"🪙 Deu {resultado.upper()}! Não foi dessa vez...", show_alert=True)
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
        palavras = random.sample(POOL_PALAVRAS_CACA, QTD_PALAVRAS_CACA)
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
    ".LOADFORCA": ("forca", JOGOS_FORCA),
    ".LOADCACA": ("caca", JOGOS_CACA),
    ".LOADCAÇA": ("caca", JOGOS_CACA),
    ".LOADCRUZADA": ("cruzada", JOGOS_CRUZADA),
    ".LOADVELHA": ("velha", JOGOS_VELHA),
    ".LOADPPT": ("ppt", JOGOS_PPT),
    ".LOADFUT": ("penalti", JOGOS_PENALTI),
    ".LOADQUIZ": ("quiz", JOGOS_QUIZ),
    ".LOADPARIMPAR": ("parimpar", JOGOS_PARIMPAR),
}


@bot.message_handler(func=lambda msg: True)
def processador_grupos(mensagem):
    if mensagem.chat.type == "private":
        return
    chat_id = mensagem.chat.id
    if chat_id not in CONFIG_GRUPOS:
        CONFIG_GRUPOS[chat_id] = True

    texto = (mensagem.text or "").strip()
    texto_upper = texto.upper()
    user_id = mensagem.from_user.id
    user_name = mensagem.from_user.first_name or "Membro"

    adicionar_pontos(chat_id, user_id, user_name, 1)

    # Reset manual de qualquer jogo travado (evita que um jogo preso bloqueie os outros)
    if texto_upper in COMANDOS_RESET:
        nome_jogo, dicionario = COMANDOS_RESET[texto_upper]
        dicionario.pop(chat_id, None)
        liberar_jogo(chat_id, nome_jogo)
        bot.reply_to(mensagem, f"🔄 Jogo de <b>{nome_jogo.upper()}</b> resetado!", parse_mode="HTML")
        return

    if texto_upper in [".MENU", ".AJUDA", "/AJUDA", "/MENU"]:
        menu = (
            "👑 <b>PAINEL DE JOGOS E PONTUAÇÃO DA SANTOS</b> 👑\n\n"
            "🏆 <code>.top</code> ou <code>.ranking</code> - Ranking Semanal\n"
            "💀 <code>.forca</code> - Jogo da Forca (+20 pts)\n"
            "⚽ <code>.fut</code> - Pênalti em Dupla (+20 pts)\n"
            "✊ <code>.ppt</code> ou <code>/ppt</code> - Pedra, Papel e Tesoura\n"
            "❤️ <code>.caça</code> - Caça-Palavras, escolha modo texto ou imagem (+15 pts)\n"
            "❤️ <code>.cruzada</code> - Palavras Cruzadas com caixinhas (+15 pts)\n"
            "❌⭕ <code>.velha</code> - Jogo da Velha (+25 pts)\n"
            "🧠 <code>.quiz</code> - Perguntas e respostas com botões (+15 pts)\n"
            "✌️ <code>.parimpar</code> - Par ou Ímpar em dupla (+20 pts)\n"
            "🪙 <code>.moeda</code> - Cara ou Coroa rápido (+5 pts)\n"
            "🔮 <code>.signo</code> ou <code>.escorpiao</code> - Horóscopo por IA\n"
            "🔧 <code>.load[jogo]</code> - Reseta um jogo travado (ex: <code>.loadforca</code>)\n"
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
        if chat_id in JOGOS_FORCA and JOGOS_FORCA[chat_id]["status"] == "ativo":
            return
        travar_jogo(chat_id, "forca")
        palavra = random.choice(["PIX", "TIGRINHO", "CASSINO", "FUTEBOL", "LUCRO", "BANCA", "SORTE", "VIP", "APOSTA"])
        JOGOS_FORCA[chat_id] = {"status": "ativo", "palavra": palavra, "certas": set(), "erradas": set(), "erros": 0}
        mascara = " ".join(["_" for _ in palavra])
        msg = bot.send_photo(chat_id, gerar_imagem_forca(0), caption=f"💀 <b>FORCA</b>\nPalavra: <code>{mascara}</code>\nErros: 0/6", parse_mode="HTML")
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
        lista = [{"palavra": p, "reveladas": [], "encontrada": False} for p in random.choice(BANCO_CRUZADAS)]
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

                frases_cruzada = [
                    f"🔥 <b>AMASSOU!</b> {user_name} acertou a cruzada <b>{texto_upper}</b> com estilo! Visão braba! 🎯 (+15 pts)",
                    f"🏆 <b>MONSTRO!</b> {user_name} mandou a palavra <b>{texto_upper}</b> pra dentro! Respeita a tropa! 🚀 (+15 pts)",
                ]
                bot.reply_to(mensagem, random.choice(frases_cruzada), parse_mode="HTML")

                try:
                    bot.edit_message_media(
                        media=InputMediaPhoto(gerar_imagem_cruzada(jogo), caption=montar_texto_cruzada(jogo), parse_mode="HTML"),
                        chat_id=chat_id, message_id=jogo["msg_id"],
                    )
                except Exception:
                    pass
                if all(i["encontrada"] for i in jogo["lista"]):
                    jogo["status"] = "encerrado"
                    bot.send_message(chat_id, "🏆 <b>PARABÉNS! Todas as Cruzadas resolvidas! O grupo tá afiado!</b>", parse_mode="HTML")
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
        travar_jogo(chat_id, "quiz")
        pergunta = random.choice(BANCO_QUIZ)
        JOGOS_QUIZ[chat_id] = {"pergunta": pergunta}
        emojis_num = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        markup = InlineKeyboardMarkup(row_width=1)
        for i, opc in enumerate(pergunta["opcoes"]):
            markup.add(InlineKeyboardButton(f"{emojis_num[i]} {opc}", callback_data=f"quiz_{i}"))
        msg = bot.send_message(chat_id, f"🧠 <b>QUIZ DA SANTOS</b> 🧠\n\n❓ {pergunta['pergunta']}\n\n<i>Quem acertar primeiro leva os pontos!</i>", reply_markup=markup, parse_mode="HTML")
        JOGOS_QUIZ[chat_id]["msg_id"] = msg.message_id
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
        bot.send_message(chat_id, "🪙 <b>CARA OU COROA</b> 🪙\nEscolha e veja se acerta! (+5 pts)", reply_markup=markup, parse_mode="HTML")
        return

    if texto_upper in [".SIGNO", ".MEUSIGNO", ".HOROSCOPO"]:
        signo = random.choice(LISTA_SIGNOS_VALIDOS)
        try:
            resp = model_ia.generate_content(f"Gere um horóscopo curto de 1 frase para {signo} focado em sorte com gírias leves.")
            txt = resp.text.strip()
        except Exception:
            txt = "Hoje o dia tá com o fluxo pago, vai pra cima!"
        bot.reply_to(mensagem, f"🔮 <b>HORÓSCOPO ({signo})</b>\n\n{txt}", parse_mode="HTML")
        return

    limpo = texto_upper.replace(".", "")
    if limpo in LISTA_SIGNOS_VALIDOS:
        try:
            resp = model_ia.generate_content(f"Gere um horóscopo curto de 1 frase para {limpo} focado em sorte com gírias leves.")
            txt = resp.text.strip()
        except Exception:
            txt = "Sua intuição tá afiada hoje, só vai!"
        bot.reply_to(mensagem, f"🔮 <b>HORÓSCOPO ({limpo})</b>\n\n{txt}", parse_mode="HTML")
        return

    # Gatilhos de plataforma só disparam se não houver jogo ativo esperando exatamente essa palavra
    if not JOGO_ATIVO.get(chat_id):
        for g, dados in GATILHOS_PLATAFORMAS.items():
            if g in texto_upper:
                frase = random.choice(FRASES_PLATAFORMA).format(g=g)
                if dados.get('file_id'):
                    bot.send_photo(chat_id, dados['file_id'], caption=f"{frase}\n\n{dados['url']}", parse_mode="HTML")
                else:
                    bot.reply_to(mensagem, f"{frase}\n\n{dados['url']}", parse_mode="HTML")
                return

    if random.random() < 0.35 or "SANTOS" in texto_upper:
        try:
            resp = model_ia.generate_content(f"Você é a Santos, assistente de resenha de um grupo de Telegram. Seja bem extrovertida, brincalhona e use gírias como 'visão', 'marcha', 'tropa'. Responda curto ao que {user_name} disse: '{texto}'")
            if resp and resp.text:
                bot.reply_to(mensagem, resp.text.strip())
        except Exception:
            pass


print("Santos - versão corrigida (trava de jogo + variáveis de ambiente)")
bot.infinity_polling()
