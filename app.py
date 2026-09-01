import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

try:
	import cloudinary
	import cloudinary.uploader
except ImportError:
	cloudinary = None

try:
	import requests
except ImportError:
	requests = None
from flask import Flask, jsonify, redirect, render_template, request, session, send_from_directory, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "jogos_pg.json"
CATALOGS_PROVEDORES = {
	"pg": BASE_DIR / "jogos_pg.json",
	"pragmatic": BASE_DIR / "jogos_pragmatic.json",
	"tada": BASE_DIR / "jogos_tada.json",
	"wg": BASE_DIR / "jogos_wg.json",
}
DATA_DIR = Path(os.environ.get("SITE_DATA_DIR", BASE_DIR / "instance"))
CONFIG_PATH = DATA_DIR / "site_config.json"
ADMIN_UPLOADS_DIR = DATA_DIR / "uploads" / "admin"
UPLOADS_DIR = BASE_DIR / "static" / "uploads" / "slots"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_CONFIG_TABLE = os.environ.get("SUPABASE_CONFIG_TABLE", "site_config")
ultimo_erro_supabase = ""
CLOUDINARY_CONFIGURED = cloudinary is not None and all(os.environ.get(chave) for chave in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))
if CLOUDINARY_CONFIGURED:
	cloudinary.config(
		cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
		api_key=os.environ["CLOUDINARY_API_KEY"],
		api_secret=os.environ["CLOUDINARY_API_SECRET"],
		secure=True,
	)
PG_GAMES_URL = "https://www.pgsoft.com/pt/games/all/"
PG_SYNC_INTERVAL = 6 * 60 * 60
INTERVALO_SINAIS_SEGUNDOS = 5 * 60
PG_REMOVED_NAMES = {
	"World Cup",
	"Zeus vs Hades - Gods of War",
	"Gates of Olympus",
	"Rise of the Sun God",
	"3 Buzzing Wilds",
	"Raider Jane's Crypt of Fortune",
	"Cleocatra",
}
ORDEM_DESTAQUES_PG = (
	"Fortune Tiger",
	"Fortune Mouse",
	"Fortune Ox",
	"Fortune Rabbit",
	"Fortune Dragon",
	"Fortune Horse",
	"Fortune Snake",
	"Ganesha Fortune",
	"Bikini Paradise",
	"Caishen Wins",
	"Wild Bandito",
	"Mahjong Ways 2",
	"Mahjong Ways",
	"Lucky Neko",
	"Midas Fortune",
	"Double Fortune",
)

app = Flask(__name__)
app.secret_key = os.environ.get("SITE_SECRET_KEY", "troque-esta-chave-em-producao")
ultima_sincronizacao_pg = 0.0
lock_sincronizacao_pg = threading.Lock()
FAIXAS_INDICATIVAS = (
	("0,20", "1,00", "20,00"),
	("0,20", "1,00", "30,00"),
	("0,40", "2,00", "40,00"),
	("0,40", "2,00", "60,00"),
	("0,50", "2,50", "50,00"),
	("0,50", "2,50", "75,00"),
	("0,80", "4,00", "100,00"),
	("0,80", "4,00", "120,00"),
	("1,00", "5,00", "150,00"),
	("1,00", "5,00", "200,00"),
	("2,00", "10,00", "300,00"),
)


def combo_aposta_por_id(jogo_id):
	# Sem fonte oficial de aposta min/max por jogo (e config de plataforma, nao do provedor):
	# hash estavel do id garante variedade real e o mesmo jogo sempre mostra o mesmo valor.
	digest = hashlib.md5(str(jogo_id).encode("utf-8")).hexdigest()
	indice = int(digest, 16) % len(FAIXAS_INDICATIVAS)
	return FAIXAS_INDICATIVAS[indice]
CONFIG_PADRAO = {
	"banner": {"ativo": True, "titulo": "GJFORTUNESINAIS", "texto": "Sinais e informações dos seus jogos favoritos em um só lugar.", "imagem": "", "link": "#catalogo"},
	"tema": {"fundo_ativo": False, "fundo_imagem": "", "favicon_emoji": "🎰"},
	"popup": {"ativo": False, "titulo": "Novidade no catálogo", "texto": "Confira os lançamentos mais recentes.", "imagem": "", "link": "#lancamentos", "botao": "Ver lançamentos"},
	"popup_2": {"ativo": False, "titulo": "Nova plataforma", "texto": "Confira a segunda oferta de entrada.", "imagem": "", "link": "#lancamentos", "botao": "Entrar agora"},
	"popup_3": {"ativo": False, "titulo": "Oferta especial", "texto": "Confira a terceira oferta de entrada.", "imagem": "", "link": "#lancamentos", "botao": "Entrar agora"},
	"telegram": {"ativo": True, "nome": "Telegram", "link": "https://t.me/"},
	"whatsapp": {"ativo": False, "link": "", "texto": "Entre no canal de achadinhos"},
	"plataformas": [],
	"stories": [],
}


class PGGamesParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.jogos = []
		self.jogo_atual = None

	def handle_starttag(self, tag, atributos):
		atributos = dict(atributos)
		if tag == "a" and "/pt/games/" in atributos.get("href", ""):
			self.jogo_atual = {"link": atributos["href"], "nome": "", "imagem": ""}
		elif tag == "img" and self.jogo_atual is not None:
			self.jogo_atual["imagem"] = atributos.get("src", "")
			self.jogo_atual["nome"] = atributos.get("alt", "").strip()

	def handle_data(self, data):
		if self.jogo_atual is not None and not self.jogo_atual["nome"]:
			self.jogo_atual["nome"] += f" {data.strip()}"

	def handle_endtag(self, tag):
		if tag == "a" and self.jogo_atual is not None:
			self.jogo_atual["nome"] = self.jogo_atual["nome"].strip()
			self.jogos.append(self.jogo_atual)
			self.jogo_atual = None


def carregar_catalogo():
	with CATALOG_PATH.open(encoding="utf-8") as arquivo:
		return json.load(arquivo)


def carregar_catalogo_provedor(provedor="pg"):
	"""Carrega catálogo de um provedor específico"""
	caminho = CATALOGS_PROVEDORES.get(provedor, CATALOG_PATH)
	if not caminho.is_file():
		return []
	try:
		with caminho.open(encoding="utf-8") as arquivo:
			dados = json.load(arquivo)
	except (json.JSONDecodeError, IOError):
		return []
	# jogos_pg.json tem estrutura {"pg": [...]}, os demais são listas diretas
	if isinstance(dados, dict):
		return dados.get(provedor, dados.get("pg", []))
	return dados


def carregar_todos_catalogos():
	"""Carrega catálogos de todos os provedores e mescla"""
	todos = []
	for provedor in CATALOGS_PROVEDORES:
		jogos = carregar_catalogo_provedor(provedor)
		todos.extend(jogos)
	return todos


def carregar_configuracao():
	configuracao_remota = carregar_configuracao_supabase()
	if configuracao_remota:
		return combinar_configuracao(configuracao_remota)
	CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
	if not CONFIG_PATH.is_file():
		with CONFIG_PATH.open("w", encoding="utf-8") as arquivo:
			json.dump(CONFIG_PADRAO, arquivo, ensure_ascii=False, indent=4)
	with CONFIG_PATH.open(encoding="utf-8") as arquivo:
		configuracao = json.load(arquivo)
	return combinar_configuracao(configuracao)


def combinar_configuracao(configuracao):
	combinada = {**CONFIG_PADRAO, **configuracao}
	for chave, valor_padrao in CONFIG_PADRAO.items():
		if isinstance(valor_padrao, dict):
			valor_atual = combinada.get(chave, {})
			if isinstance(valor_atual, dict):
				combinada[chave] = {**valor_padrao, **valor_atual}
	for item in combinada.get("plataformas", []):
		imagem = str(item.get("imagem", "")).strip()
		if imagem.startswith("/admin/uploads/") and not imagem_config_disponivel(imagem):
			item["imagem"] = ""
	for chave in ("banner", "popup", "popup_2", "popup_3"):
		imagem = str(combinada.get(chave, {}).get("imagem", "")).strip()
		if imagem.startswith("/admin/uploads/") and not imagem_config_disponivel(imagem):
			combinada[chave]["imagem"] = ""
	for story in combinada.get("stories", []):
		imagem = str(story.get("imagem", "")).strip()
		if imagem.startswith("/admin/uploads/") and not imagem_config_disponivel(imagem):
			story["imagem"] = ""
	return combinada


def salvar_configuracao(configuracao):
	if supabase_configurado():
		if salvar_configuracao_supabase(configuracao):
			return True
		detalhe = f" Detalhe: {ultimo_erro_supabase}" if ultimo_erro_supabase else ""
		raise RuntimeError(f"Não foi possível salvar no Supabase. A configuração remota foi preservada.{detalhe}")
	CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
	with CONFIG_PATH.open("w", encoding="utf-8") as arquivo:
		json.dump(configuracao, arquivo, ensure_ascii=False, indent=4)
	return True


def cabecalhos_supabase():
	return {
		"apikey": SUPABASE_SERVICE_KEY,
		"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
		"Content-Type": "application/json",
	}


def supabase_configurado():
	return requests is not None and bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def carregar_configuracao_supabase():
	global ultimo_erro_supabase
	if not supabase_configurado():
		return None
	try:
		resposta = requests.get(
			f"{SUPABASE_URL}/rest/v1/{SUPABASE_CONFIG_TABLE}",
			params={"key": "eq.main", "select": "config", "limit": 1},
			headers=cabecalhos_supabase(),
			timeout=8,
		)
		resposta.raise_for_status()
		registros = resposta.json()
		ultimo_erro_supabase = ""
		return registros[0].get("config") if registros else {}
	except (requests.RequestException, ValueError, IndexError, AttributeError) as erro:
		ultimo_erro_supabase = str(erro)
		return None


def salvar_configuracao_supabase(configuracao):
	global ultimo_erro_supabase
	if not supabase_configurado():
		return False
	try:
		resposta = requests.post(
			f"{SUPABASE_URL}/rest/v1/{SUPABASE_CONFIG_TABLE}",
			params={"on_conflict": "key"},
			headers={**cabecalhos_supabase(), "Prefer": "resolution=merge-duplicates,return=minimal"},
			json={"key": "main", "config": configuracao},
			timeout=8,
		)
		resposta.raise_for_status()
		ultimo_erro_supabase = ""
		return True
	except requests.RequestException as erro:
		ultimo_erro_supabase = str(erro)
		return False


def filtrar_stories_ativas(stories):
	agora = time.time()
	ativas = []
	for story in stories or []:
		imagem = str(story.get("imagem", "")).strip()
		if not imagem:
			continue
		try:
			expira_em = float(story.get("expira_em", 0))
		except (TypeError, ValueError):
			continue
		if expira_em <= agora:
			continue
		ativas.append(
			{
				"titulo": str(story.get("titulo", "Story"))[:60],
				"imagem": imagem,
				"link": str(story.get("link", "")).strip(),
				"expira_em": expira_em,
			}
		)
	return ativas


def imagem_config_disponivel(imagem_url):
	imagem = str(imagem_url or "").strip()
	if not imagem:
		return False
	if imagem.startswith("/admin/uploads/"):
		nome = imagem.rsplit("/", 1)[-1]
		return (ADMIN_UPLOADS_DIR / nome).is_file()
	return True


def administrador_logado():
	return session.get("admin_logado") is True


def salvar_upload(campo):
	arquivo = request.files.get(campo)
	if not arquivo or not arquivo.filename:
		return ""
	nome = secure_filename(arquivo.filename)
	if not nome:
		return ""
	if CLOUDINARY_CONFIGURED:
		try:
			resultado = cloudinary.uploader.upload(
				arquivo,
				folder="gjfortunesinais/admin",
				resource_type="image",
				use_filename=True,
				unique_filename=True,
			)
			return resultado.get("secure_url", "")
		except Exception as erro:
			raise RuntimeError(f"Falha ao enviar a imagem para o Cloudinary: {erro}") from erro
	ADMIN_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
	arquivo.save(ADMIN_UPLOADS_DIR / nome)
	return url_for("admin_upload", nome=nome)


@app.route("/admin", methods=["GET", "POST"])
def admin():
	agora = time.time()
	if request.method == "POST":
		if request.form.get("senha") == os.environ.get("ADMIN_PASSWORD", "admin123"):
			session["admin_logado"] = True
			return redirect(url_for("admin"))
		return render_template("admin.html", erro="Senha incorreta.", configuracao=carregar_configuracao(), now=agora)
	if not administrador_logado():
		return render_template("admin.html", configuracao=carregar_configuracao(), now=agora)
	return render_template("admin.html", configuracao=carregar_configuracao(), logado=True, now=agora)


@app.post("/admin/salvar")
def salvar_admin():
	if not administrador_logado():
		return redirect(url_for("admin"))
	configuracao = carregar_configuracao()
	configuracao["banner"] = {
		"ativo": request.form.get("banner_ativo") == "on",
		"titulo": request.form.get("banner_titulo", "").strip(),
		"texto": request.form.get("banner_texto", "").strip(),
		"imagem": salvar_upload("banner_imagem") or request.form.get("banner_imagem_url", "").strip() or request.form.get("banner_imagem_atual", "").strip(),
		"link": request.form.get("banner_link", "#catalogo").strip(),
	}
	configuracao["tema"] = {
		"fundo_ativo": request.form.get("tema_fundo_ativo") == "on",
		"fundo_imagem": salvar_upload("tema_fundo_imagem") or request.form.get("tema_fundo_imagem_url", "").strip() or request.form.get("tema_fundo_imagem_atual", "").strip(),
		"favicon_emoji": request.form.get("tema_favicon_emoji", "🎰").strip() or "🎰",
	}
	configuracao["popup"] = {
		"ativo": request.form.get("popup_ativo") == "on",
		"titulo": request.form.get("popup_titulo", "").strip(),
		"texto": request.form.get("popup_texto", "").strip(),
		"imagem": salvar_upload("popup_imagem") or request.form.get("popup_imagem_url", "").strip() or request.form.get("popup_imagem_atual", "").strip(),
		"link": request.form.get("popup_link", "#lancamentos").strip(),
		"botao": request.form.get("popup_botao", "Ver lançamentos").strip(),
	}
	configuracao["popup_2"] = {
		"ativo": request.form.get("popup2_ativo") == "on",
		"titulo": request.form.get("popup2_titulo", "").strip(),
		"texto": request.form.get("popup2_texto", "").strip(),
		"imagem": salvar_upload("popup2_imagem") or request.form.get("popup2_imagem_url", "").strip() or request.form.get("popup2_imagem_atual", "").strip(),
		"link": request.form.get("popup2_link", "#lancamentos").strip(),
		"botao": request.form.get("popup2_botao", "Entrar agora").strip(),
	}
	configuracao["popup_3"] = {
		"ativo": request.form.get("popup3_ativo") == "on",
		"titulo": request.form.get("popup3_titulo", "").strip(),
		"texto": request.form.get("popup3_texto", "").strip(),
		"imagem": salvar_upload("popup3_imagem") or request.form.get("popup3_imagem_url", "").strip() or request.form.get("popup3_imagem_atual", "").strip(),
		"link": request.form.get("popup3_link", "#lancamentos").strip(),
		"botao": request.form.get("popup3_botao", "Entrar agora").strip(),
	}
	configuracao["telegram"] = {
		"ativo": request.form.get("telegram_ativo") == "on",
		"nome": request.form.get("telegram_nome", "Telegram").strip(),
		"link": request.form.get("telegram_link", "").strip(),
	}
	configuracao["whatsapp"] = {
		"ativo": request.form.get("whatsapp_ativo") == "on",
		"link": request.form.get("whatsapp_link", "").strip(),
		"texto": request.form.get("whatsapp_texto", "Entre no canal de achadinhos").strip() or "Entre no canal de achadinhos",
	}
	plataformas = []
	for indice in range(60):
		link = request.form.get(f"plataforma_link_{indice}", "").strip()
		imagem = salvar_upload(f"plataforma_imagem_{indice}") or request.form.get(f"plataforma_imagem_url_{indice}", "").strip() or request.form.get(f"plataforma_imagem_atual_{indice}", "").strip()
		if imagem or link:
			plataformas.append({"link": link, "imagem": imagem})
	configuracao["plataformas"] = plataformas
	stories = []
	for indice in range(60):
		titulo = request.form.get(f"story_titulo_{indice}", "Story").strip() or "Story"
		link = request.form.get(f"story_link_{indice}", "").strip()
		imagem = (
			salvar_upload(f"story_imagem_{indice}")
			or request.form.get(f"story_imagem_url_{indice}", "").strip()
			or request.form.get(f"story_imagem_atual_{indice}", "").strip()
		)
		if not imagem:
			continue
		expira_atual = request.form.get(f"story_expira_{indice}", "").strip()
		renovar = request.form.get(f"story_renovar_{indice}") == "on"
		if renovar or not expira_atual:
			expira_em = time.time() + 24 * 60 * 60
		else:
			try:
				expira_em = float(expira_atual)
			except ValueError:
				expira_em = time.time() + 24 * 60 * 60
		stories.append(
			{
				"titulo": titulo,
				"link": link,
				"imagem": imagem,
				"expira_em": expira_em,
			}
		)
	configuracao["stories"] = stories
	try:
		salvar_configuracao(configuracao)
	except Exception as erro:
		return render_template(
			"admin.html",
			erro=f"Falha ao salvar: {erro}",
			configuracao=configuracao,
			logado=True,
			now=time.time(),
		), 502
	return redirect(url_for("admin", salvo=1))


@app.get("/admin/logout")
def admin_logout():
	session.clear()
	return redirect(url_for("admin"))


@app.get("/admin/uploads/<nome>")
def admin_upload(nome):
	return send_from_directory(ADMIN_UPLOADS_DIR, nome)


def encontrar_jogo(jogo_id):
	# Procura em todos os provedores
	for provedor in CATALOGS_PROVEDORES:
		jogos = carregar_catalogo_provedor(provedor)
		jogo = next(
			(jogo for jogo in jogos if str(jogo.get("id")) == str(jogo_id)),
			None,
		)
		if jogo is not None:
			return normalizar_faixas_jogo(jogo)
	return None


def classificar_volatilidade(jogo):
	maximo = converter_valor(jogo.get("exibir_max"), 100.0)
	if maximo <= 30:
		return "baixa"
	if maximo <= 60:
		return "media"
	if maximo <= 150:
		return "alta"
	return "muito_alta"


FAIXAS_PERCENTUAIS_POR_VOLATILIDADE = {
	"baixa": {"minima": (28, 68), "padrao": (32, 62), "maxima": (42, 74), "distribuicao": (90, 99)},
	"media": {"minima": (20, 80), "padrao": (24, 76), "maxima": (34, 88), "distribuicao": (86, 98)},
	"alta": {"minima": (14, 86), "padrao": (18, 84), "maxima": (30, 94), "distribuicao": (82, 97)},
	"muito_alta": {"minima": (10, 88), "padrao": (15, 88), "maxima": (25, 96), "distribuicao": (78, 96)},
}


def gerar_sinal_do_ciclo(jogo_id, jogo, agora=None):
	instante = time.time() if agora is None else agora
	ciclo = int(instante // INTERVALO_SINAIS_SEGUNDOS)
	gerador = random.Random(f"gjfortunesinais:{ciclo}:{jogo_id}")
	faixas = FAIXAS_PERCENTUAIS_POR_VOLATILIDADE[classificar_volatilidade(jogo)]
	minima = gerador.randint(*faixas["minima"])
	padrao = gerador.randint(*faixas["padrao"])
	maxima = gerador.randint(*faixas["maxima"])
	distribuicao = gerador.randint(*faixas["distribuicao"])
	escada = gerar_escada_apostas(jogo)
	minima_aposta = escada[0]
	meio = escada[1:max(2, len(escada) // 2)] or escada
	altas = escada[max(1, len(escada) // 2):] or escada
	return {
		"ciclo": ciclo,
		"valido_ate": (ciclo + 1) * INTERVALO_SINAIS_SEGUNDOS,
		"minima": minima,
		"padrao": padrao,
		"maxima": maxima,
		"distribuicao": distribuicao,
		"apostas": {
			"minima": formatar_valor_aposta(minima_aposta),
			"padrao": formatar_valor_aposta(gerador.choice(meio)),
			"maxima": formatar_valor_aposta(gerador.choice(altas)),
		},
	}


def extrair_valor_real(jogo, chave_curta, chave_longa):
	# So considera valor real se o jogo foi marcado como verificado manualmente na plataforma
	if not jogo.get("aposta_verificada"):
		return None
	valor = jogo.get(chave_curta)
	if valor:
		return str(valor).strip()
	valor_longo = jogo.get(chave_longa)
	if valor_longo:
		return str(valor_longo).replace("R$", "").strip()
	return None


def normalizar_faixas_jogo(jogo, indice=0):
	# Prioriza valores reais verificados no catalogo (min/pad/max ou minbet/padbet/maxbet).
	# Para jogos ainda nao verificados, usa um combo determinístico por id (estavel e variado)
	# em vez de repetir sempre o mesmo valor, ja que nao existe fonte oficial publica disso.
	min_real = extrair_valor_real(jogo, "min", "minbet")
	pad_real = extrair_valor_real(jogo, "pad", "padbet")
	max_real = extrair_valor_real(jogo, "max", "maxbet")
	if min_real and pad_real and max_real:
		jogo["exibir_min"], jogo["exibir_pad"], jogo["exibir_max"] = min_real, pad_real, max_real
	else:
		jogo["exibir_min"], jogo["exibir_pad"], jogo["exibir_max"] = combo_aposta_por_id(jogo.get("id", indice))
	return jogo



def preparar_faixas_indicativas(catalogo):
	# Aceita tanto {"pg": [...]} quanto lista direta
	jogos = catalogo if isinstance(catalogo, list) else catalogo.get("pg", [])
	for indice, jogo in enumerate(jogos):
		normalizar_faixas_jogo(jogo, indice)
		jogo["sinal"] = gerar_sinal_do_ciclo(jogo.get("id"), jogo)


def converter_valor(valor, padrao):
	try:
		texto = str(valor).strip()
		if "," in texto:
			texto = texto.replace(".", "").replace(",", ".")
		return float(texto)
	except (TypeError, ValueError):
		return padrao


def gerar_escada_apostas(jogo):
	base = converter_valor(jogo.get("exibir_min") or jogo.get("min"), 0.4)
	limite = converter_valor(jogo.get("exibir_max") or jogo.get("max"), 100.0)
	valores = []
	for escala in (1, 10, 100):
		passo = base * escala
		inicio = base * escala
		fim = base * escala * 10
		valor = inicio
		while valor <= fim + 0.001 and valor <= limite + 0.001:
			valores.append(round(valor, 2))
			valor += passo
	return valores or [round(min(base, limite), 2)]


def formatar_valor_aposta(valor):
	return f"{valor:.2f}".replace(".", ",")


def ordenar_jogos_pg(jogos):
	posicoes = {nome: indice for indice, nome in enumerate(ORDEM_DESTAQUES_PG)}
	return sorted(jogos, key=lambda jogo: (posicoes.get(jogo.get("nome"), 1000), jogo.get("nome", "").lower()))


def sincronizar_lancamentos_pg():
	global ultima_sincronizacao_pg
	if time.time() - ultima_sincronizacao_pg < PG_SYNC_INTERVAL:
		return

	with lock_sincronizacao_pg:
		if time.time() - ultima_sincronizacao_pg < PG_SYNC_INTERVAL:
			return
		try:
			requisicao = urllib.request.Request(
				PG_GAMES_URL,
				headers={"User-Agent": "Mozilla/5.0"},
			)
			with urllib.request.urlopen(requisicao, timeout=8) as resposta:
				html = resposta.read().decode("utf-8", "ignore")
			catalogo = carregar_catalogo()
			jogos_existentes = {
				(str(jogo.get("id")), jogo.get("nome"))
				for jogo in catalogo.get("pg", [])
			}
			jogos_novos = []
			parser = PGGamesParser()
			parser.feed(html)
			for jogo_oficial in parser.jogos:
				link = jogo_oficial["link"]
				id_match = re.search(r"/games/(\d+)/", link)
				if not id_match:
					continue
				nome = jogo_oficial["nome"].split("Volatilidade")[0].strip()
				if not nome or nome in PG_REMOVED_NAMES:
					continue
				jogo_id = f"pgsoft-{id_match.group(1)}"
				if (jogo_id, nome) in jogos_existentes or any(
					jogo.get("nome") == nome for jogo in catalogo.get("pg", [])
				):
					continue
				imagem_url = jogo_oficial["imagem"]
				if imagem_url and imagem_url.startswith("/"):
					imagem_url = f"https://www.pgsoft.com{imagem_url}"
				jogos_novos.append(
					{
						"id": jogo_id,
						"nome": nome,
						"min": "0,40",
						"pad": "2,00",
						"max": "100,00",
						"imagem": imagem_url,
					}
				)
				if len(jogos_novos) == 20:
					break
			if jogos_novos:
				catalogo["pg"] = jogos_novos + catalogo.get("pg", [])
				with CATALOG_PATH.open("w", encoding="utf-8") as arquivo:
					json.dump(catalogo, arquivo, ensure_ascii=False, indent=4)
			ultima_sincronizacao_pg = time.time()
		except (OSError, ValueError):
			return


@app.route("/")
def index():
	sincronizar_lancamentos_pg()
	
	# Carregar catálogos de todos os provedores
	catalogo = {
		"pg": carregar_catalogo_provedor("pg"),
		"pragmatic": carregar_catalogo_provedor("pragmatic"),
		"tada": carregar_catalogo_provedor("tada"),
		"wg": carregar_catalogo_provedor("wg"),
	}
	
	# Preparar faixas para todos os jogos
	for jogos_provedor in catalogo.values():
		preparar_faixas_indicativas(jogos_provedor)
	
	configuracao = carregar_configuracao()
	stories_ativas = filtrar_stories_ativas(configuracao.get("stories", []))
	popups_ativos = []
	for chave in ("popup", "popup_2", "popup_3"):
		popup = configuracao.get(chave, {})
		imagem = str(popup.get("imagem", "")).strip()
		if popup.get("ativo") and imagem:
			popups_ativos.append(
				{
					"titulo": str(popup.get("titulo", "")).strip(),
					"texto": str(popup.get("texto", "")).strip(),
					"imagem": imagem,
					"link": str(popup.get("link", "")).strip() or "#",
					"botao": str(popup.get("botao", "Entrar agora")).strip() or "Entrar agora",
				}
			)
	popup_entrada = random.choice(popups_ativos) if popups_ativos else None
	lancamentos = [
		jogo for jogo in catalogo.get("pg", [])
		if str(jogo.get("id", "")).startswith("pg-")
		or str(jogo.get("id", "")).startswith("200")
	]
	catalogo["pg"] = ordenar_jogos_pg(catalogo.get("pg", []))
	return render_template(
		"index.html",
		dados=catalogo,
		lancamentos=lancamentos,
		configuracao=configuracao,
		stories_ativas=stories_ativas,
		popup_entrada=popup_entrada,
	)


@app.route("/api/capa/<jogo_id>")
def capa(jogo_id):
	jogo = encontrar_jogo(jogo_id)
	if jogo is None:
		return jsonify({"erro": "Jogo não encontrado"}), 404

	for extensao in (".avif", ".png", ".jpeg", ".jpg", ".webp"):
		capa_local = UPLOADS_DIR / f"{jogo_id}{extensao}"
		if capa_local.is_file():
			return send_from_directory(UPLOADS_DIR, capa_local.name)

	imagem = jogo.get("imagem")
	if imagem:
		return redirect(imagem)
	return jsonify({"erro": "Capa não encontrada"}), 404


@app.route("/api/sinal/<jogo_id>")
def sinal(jogo_id):
	jogo = encontrar_jogo(jogo_id)
	if jogo is None:
		return jsonify({"erro": "Jogo não encontrado"}), 404
	resposta = jsonify(gerar_sinal_do_ciclo(jogo_id, jogo))
	resposta.headers["Cache-Control"] = "no-store"
	return resposta


if __name__ == "__main__":
	app.run(debug=True)
