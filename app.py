import hashlib
import json
import os
import random
import re
import secrets
import smtplib
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
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
from flask import Flask, Response, jsonify, redirect, render_template, request, session, send_from_directory, url_for
from werkzeug.security import check_password_hash, generate_password_hash
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
USERS_PATH = DATA_DIR / "users.json"
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
FP_SINAIS_URL = "https://grupofpsinais.io/"
FP_GET_GAMES_ACTION = os.environ.get("FP_GET_GAMES_ACTION", "78273770f67e1f4a79df922ae8905c49681d230098")
FP_SYNC_INTERVAL = 15
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
app.permanent_session_lifetime = timedelta(days=30)
ultima_sincronizacao_pg = 0.0
lock_sincronizacao_pg = threading.Lock()
ultima_sincronizacao_fp = 0.0
lock_sincronizacao_fp = threading.Lock()
sinais_grupo_fp = {}
ordem_jogos_grupo_fp = []
jogos_grupo_fp = {}
ultima_atualizacao_fp_remota = 0.0
lock_usuarios = threading.Lock()
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


def carregar_usuarios():
	if not USERS_PATH.is_file():
		return {}
	try:
		with USERS_PATH.open(encoding="utf-8") as arquivo:
			usuarios = json.load(arquivo)
		return usuarios if isinstance(usuarios, dict) else {}
	except (OSError, json.JSONDecodeError):
		return {}


def salvar_usuarios(usuarios):
	with lock_usuarios:
		USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
		temporario = USERS_PATH.with_suffix(".tmp")
		with temporario.open("w", encoding="utf-8") as arquivo:
			json.dump(usuarios, arquivo, ensure_ascii=False, indent=2)
			arquivo.flush()
			os.fsync(arquivo.fileno())
		temporario.replace(USERS_PATH)


def usuario_logado():
	return session.get("usuario_email") or ""


def smtp_configurado():
	return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def enviar_link_redefinicao(email, link):
	if not smtp_configurado():
		return False
	mensagem = EmailMessage()
	mensagem["Subject"] = "Redefina sua senha - GJFORTUNESINAIS"
	mensagem["From"] = os.environ["SMTP_FROM"]
	mensagem["To"] = email
	mensagem.set_content(f"Use este link para criar uma nova senha: {link}\n\nO link expira em 30 minutos.")
	with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=15) as servidor:
		if os.environ.get("SMTP_TLS", "true").lower() != "false":
			servidor.starttls()
		if os.environ.get("SMTP_USER"):
			servidor.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
		servidor.send_message(mensagem)
	return True


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
	erro = ""
	if request.method == "POST":
		nome = request.form.get("nome", "").strip()
		email = request.form.get("email", "").strip().casefold()
		senha = request.form.get("senha", "")
		if len(nome.split()) < 2 or "@" not in email or len(senha) < 6:
			erro = "Informe seu nome completo, um e-mail válido e uma senha com pelo menos 6 caracteres."
		else:
			usuarios = carregar_usuarios()
			if email in usuarios:
				erro = "Este e-mail já está cadastrado."
			else:
				usuarios[email] = {"nome": nome, "senha": generate_password_hash(senha), "criado_em": time.time()}
				salvar_usuarios(usuarios)
				session["usuario_email"] = email
				return redirect(url_for("index"))
	return render_template("auth.html", modo="cadastro", erro=erro)


@app.route("/login", methods=["GET", "POST"])
def login():
	erro = ""
	if request.method == "POST":
		email = request.form.get("email", "").strip().casefold()
		senha = request.form.get("senha", "")
		usuario = carregar_usuarios().get(email, {})
		if usuario and check_password_hash(usuario.get("senha", ""), senha):
			session["usuario_email"] = email
			session.permanent = request.form.get("lembrar") == "on"
			return redirect(url_for("index"))
		erro = "E-mail ou senha incorretos."
	return render_template("auth.html", modo="login", erro=erro)


@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
	mensagem = ""
	if request.method == "POST":
		email = request.form.get("email", "").strip().casefold()
		usuarios = carregar_usuarios()
		usuario = usuarios.get(email)
		if usuario:
			token = secrets.token_urlsafe(32)
			usuario["reset_token"] = generate_password_hash(token)
			usuario["reset_expira_em"] = time.time() + 30 * 60
			salvar_usuarios(usuarios)
			try:
				enviar_link_redefinicao(email, url_for("redefinir_senha", token=token, _external=True))
			except (OSError, smtplib.SMTPException):
				pass
		mensagem = "Se existir uma conta com este e-mail, enviaremos um link para redefinir a senha."
	return render_template("auth.html", modo="esqueci", mensagem=mensagem)


@app.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
	usuarios = carregar_usuarios()
	email = next((chave for chave, usuario in usuarios.items() if usuario.get("reset_expira_em", 0) > time.time() and check_password_hash(usuario.get("reset_token", ""), token)), None)
	if not email:
		return render_template("auth.html", modo="redefinir", erro="Este link é inválido ou expirou."), 400
	if request.method == "POST":
		senha = request.form.get("senha", "")
		if len(senha) < 6:
			return render_template("auth.html", modo="redefinir", erro="A senha deve ter pelo menos 6 caracteres."), 400
		usuarios[email]["senha"] = generate_password_hash(senha)
		usuarios[email].pop("reset_token", None)
		usuarios[email].pop("reset_expira_em", None)
		salvar_usuarios(usuarios)
		return redirect(url_for("login"))
	return render_template("auth.html", modo="redefinir")


@app.get("/logout")
def logout():
	session.pop("usuario_email", None)
	return redirect(url_for("index"))


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
	for jogo in jogos_grupo_fp.values():
		if str(jogo.get("id")) == str(jogo_id):
			return normalizar_faixas_jogo(jogo)
	return None


def mesclar_jogos_grupo_fp(jogos):
	existentes = {str(jogo.get("nome", "")).strip().casefold() for jogo in jogos}
	nomes_fp = list(ordem_jogos_grupo_fp)
	nomes_fp.extend(nome for nome in jogos_grupo_fp if nome not in nomes_fp)
	for nome in nomes_fp:
		jogo_fp = jogos_grupo_fp.get(nome)
		if not jogo_fp or nome in existentes:
			continue
		bets = jogo_fp.get("bets", [])
		jogos.append(
			{
				"id": jogo_fp["id"],
				"nome": jogo_fp["nome"],
				"min": bets[0] if bets else "0,40",
				"pad": bets[6] if len(bets) > 6 else (bets[0] if bets else "0,40"),
				"max": bets[-1] if bets else "100,00",
				"imagem": jogo_fp.get("imagem", ""),
			}
		)
	return jogos


def classificar_volatilidade(jogo):
	maximo = converter_valor(jogo.get("exibir_max"), 100.0)
	if maximo <= 30:
		return "baixa"
	if maximo <= 60:
		return "media"
	if maximo <= 150:
		return "alta"
	return "muito_alta"


def extrair_resposta_server_action(resposta):
	for linha in resposta.text.splitlines():
		if not linha.startswith("1:"):
			continue
		try:
			conteudo = json.loads(linha[2:])
		except (TypeError, ValueError):
			continue
		if isinstance(conteudo, dict) and isinstance(conteudo.get("games"), list):
			return conteudo
	return None


def faixas_aposta_grupo_fp(bets):
	valores = [str(valor).strip() for valor in bets or [] if str(valor).strip()]
	if len(valores) < 2:
		return None
	quantidade_minima = 6 if len(valores) > 11 else max(1, len(valores) // 3)
	quantidade_padrao = 5 if len(valores) > 11 else quantidade_minima
	indice_padrao = quantidade_minima
	indice_maxima = min(indice_padrao + quantidade_padrao, len(valores) - 1)
	return {
		"minima": f"R$ {valores[0]} a R$ {valores[quantidade_minima - 1]}",
		"padrao": f"R$ {valores[indice_padrao]} a R$ {valores[indice_maxima - 1]}",
		"maxima": f"Acima de R$ {valores[indice_maxima]}",
	}


def apostas_sugeridas_grupo_fp(bets, minima, padrao, maxima, categoria="PG"):
	valores = [str(valor).strip() for valor in bets or [] if str(valor).strip()]
	if not valores:
		return {}
	if categoria == "PG" and len(valores) > 11:
		blocos = {"minimum": 6, "standard": 5, "maximum": len(valores) - 11}
	else:
		bloco = max(1, len(valores) // 3)
		blocos = {"minimum": bloco, "standard": bloco, "maximum": bloco}
	inicios = {"minimum": 0, "standard": blocos["minimum"], "maximum": blocos["minimum"] + blocos["standard"]}

	def nivel(valor):
		return 1 if valor >= 90 else 2 if valor >= 80 else 3 if valor >= 70 else 4 if valor >= 60 else 5 if valor >= 50 else None

	def conexao(valor):
		return min(int(valor // 10) + 1, 10)

	def escolher(bloco, indice):
		inicio = inicios[bloco]
		quantidade = blocos[bloco]
		deslocamento = min(quantidade, max(1, int((indice / 10) * quantidade + 0.999)))
		posicao = inicio + deslocamento - 1
		return valores[posicao] if posicao < len(valores) else ""

	bonus_extra = min(max(round((0.3 * padrao + 0.2 * minima + 0.5 * maxima) / 10), 1), 10)
	resultado = {"minima": {}, "padrao": {}, "maxima": {}}
	for chave, valor in (("minima", minima), ("padrao", padrao), ("maxima", maxima)):
		faixa = nivel(valor)
		if faixa:
			resultado[chave]["bonus"] = escolher("minimum" if chave == "minima" else "standard" if chave == "padrao" else "maximum", faixa)
		resultado[chave]["conexao"] = escolher("minimum" if chave == "minima" else "standard" if chave == "padrao" else "maximum", conexao(valor))
	if nivel(minima):
		resultado["minima"]["extra"] = escolher("minimum", bonus_extra)
	return resultado


def sincronizar_sinais_grupo_fp():
	global ultima_sincronizacao_fp, ordem_jogos_grupo_fp, jogos_grupo_fp, ultima_atualizacao_fp_remota
	if requests is None or time.time() - ultima_sincronizacao_fp < FP_SYNC_INTERVAL:
		return

	with lock_sincronizacao_fp:
		if time.time() - ultima_sincronizacao_fp < FP_SYNC_INTERVAL:
			return
		try:
			novos_sinais = {}
			nova_ordem = []
			novos_jogos = {}
			ultima_atualizacao = 0.0
			headers = {
				"Accept": "text/x-component",
				"Content-Type": "text/plain;charset=UTF-8",
				"User-Agent": "Mozilla/5.0",
				"Next-Action": FP_GET_GAMES_ACTION,
				"Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C16%5D",
			}
			for pagina in range(1, 21):
				resposta = requests.post(
					FP_SINAIS_URL,
					headers=headers,
					data=json.dumps(["PG", None, "all", pagina]),
					timeout=12,
				)
				resposta.raise_for_status()
				conteudo = extrair_resposta_server_action(resposta)
				if not conteudo:
					break
				for jogo in conteudo.get("games", []):
					try:
						ultima_atualizacao = max(ultima_atualizacao, datetime.fromisoformat(str(jogo.get("updatedAt", "")).replace("Z", "+00:00")).timestamp())
					except (TypeError, ValueError):
						pass
					nome = str(jogo.get("nomeJogo", "")).strip().casefold()
					if nome and nome not in nova_ordem:
						nova_ordem.append(nome)
					if nome:
						imagem = str(jogo.get("imageUrl", "")).strip()
						if imagem.startswith("/"):
							imagem = f"{FP_SINAIS_URL.rstrip('/')}{imagem}"
						novos_jogos[nome] = {
						"id": f"fp-{jogo.get('id')}",
						"nome": str(jogo.get("nomeJogo", "")).strip(),
						"imagem": imagem,
						"bets": [str(valor).strip() for valor in jogo.get("bets", [])],
					}
					valores = {
						"minima": jogo.get("minima"),
						"padrao": jogo.get("padrao"),
						"maxima": jogo.get("maxima"),
						"distribuicao": jogo.get("porcentagem"),
						"faixas_aposta": faixas_aposta_grupo_fp(jogo.get("bets")),
						"apostas_sugeridas": apostas_sugeridas_grupo_fp(jogo.get("bets"), jogo.get("minima", 0), jogo.get("padrao", 0), jogo.get("maxima", 0), jogo.get("categoriaJogo", "PG")),
					}
					if nome and all(isinstance(valores[chave], int) for chave in ("minima", "padrao", "maxima", "distribuicao")):
						novos_sinais[nome] = valores
				if not conteudo.get("hasMore"):
					break
			if novos_sinais:
				sinais_grupo_fp.clear()
				sinais_grupo_fp.update(novos_sinais)
				ordem_jogos_grupo_fp = nova_ordem
				jogos_grupo_fp = novos_jogos
				ultima_atualizacao_fp_remota = ultima_atualizacao or time.time()
			ultima_sincronizacao_fp = time.time()
		except (OSError, ValueError, requests.RequestException):
			return


FAIXAS_PERCENTUAIS_POR_VOLATILIDADE = {
	"baixa": {"minima": (28, 68), "padrao": (32, 62), "maxima": (42, 74), "distribuicao": (90, 99)},
	"media": {"minima": (20, 80), "padrao": (24, 76), "maxima": (34, 88), "distribuicao": (86, 98)},
	"alta": {"minima": (14, 86), "padrao": (18, 84), "maxima": (30, 94), "distribuicao": (82, 97)},
	"muito_alta": {"minima": (10, 88), "padrao": (15, 88), "maxima": (25, 96), "distribuicao": (78, 96)},
}


def gerar_sinal_do_ciclo(jogo_id, jogo, agora=None):
	sincronizar_sinais_grupo_fp()
	sinal_fp = sinais_grupo_fp.get(str(jogo.get("nome", "")).strip().casefold())
	if sinal_fp:
		ciclo = int((time.time() if agora is None else agora) // INTERVALO_SINAIS_SEGUNDOS)
		return {
			"ciclo": ciclo,
			"valido_ate": (ciclo + 1) * INTERVALO_SINAIS_SEGUNDOS,
			**sinal_fp,
			"apostas": {},
			"faixas_aposta": sinal_fp.get("faixas_aposta"),
			"fp_atualizado_em": ultima_atualizacao_fp_remota,
		}
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
		"fp_atualizado_em": 0,
		"apostas": {
			"minima": formatar_valor_aposta(minima_aposta),
			"padrao": formatar_valor_aposta(gerador.choice(meio)),
			"maxima": formatar_valor_aposta(gerador.choice(altas)),
		},
	}


def extrair_valor_real(jogo, chave_curta, chave_longa):
	# Le o valor ja existente no catalogo (verificado ou nao), sem inventar nada novo
	valor = jogo.get(chave_curta)
	if valor:
		return str(valor).strip()
	valor_longo = jogo.get(chave_longa)
	if valor_longo:
		return str(valor_longo).replace("R$", "").strip()
	return None


def normalizar_faixas_jogo(jogo, indice=0):
	# Usa sempre o que ja esta no catalogo (min/pad/max ou minbet/padbet/maxbet), verificado ou nao.
	# So cai no combo determinístico por id se o jogo realmente nao tiver nenhum valor cadastrado.
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
		jogo["volatilidade"] = classificar_volatilidade(jogo)
		jogo["sinal"] = gerar_sinal_do_ciclo(jogo.get("id"), jogo)
		jogo["faixas_aposta"] = gerar_faixas_aposta(jogo)


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


def gerar_faixas_aposta(jogo):
	minima = converter_valor(jogo.get("exibir_min"), 0.4)
	maxima = converter_valor(jogo.get("exibir_max"), 100.0)
	baixa_fim = min(minima * 10, maxima)
	padrao_inicio = min(minima * 12, maxima)
	padrao_fim = min(minima * 40, maxima)
	return {
		"minima": f"R$ {formatar_valor_aposta(minima)} a R$ {formatar_valor_aposta(baixa_fim)}",
		"padrao": f"R$ {formatar_valor_aposta(padrao_inicio)} a R$ {formatar_valor_aposta(padrao_fim)}",
		"maxima": f"Acima de R$ {formatar_valor_aposta(padrao_fim)}",
	}


def ordenar_jogos_pg(jogos):
	if ordem_jogos_grupo_fp:
		posicoes_fp = {nome: indice for indice, nome in enumerate(ordem_jogos_grupo_fp)}
		return sorted(
			jogos,
			key=lambda jogo: (posicoes_fp.get(str(jogo.get("nome", "")).strip().casefold(), 10000), jogo.get("nome", "").lower()),
		)
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
	sincronizar_sinais_grupo_fp()
	
	# Exibe apenas jogos PG enquanto as apostas dos demais provedores não são verificadas.
	catalogo = {"pg": mesclar_jogos_grupo_fp(carregar_catalogo_provedor("pg"))}
	
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
		usuario_email=usuario_logado(),
		fp_atualizado_em=ultima_atualizacao_fp_remota,
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
		if str(imagem).startswith("/"):
			imagem = f"{FP_SINAIS_URL.rstrip('/')}{imagem}"
		try:
			resposta = requests.get(imagem, headers={"User-Agent": "Mozilla/5.0"}, timeout=12) if requests else None
			if resposta is not None and resposta.ok and resposta.content:
				return Response(resposta.content, mimetype=resposta.headers.get("Content-Type", "image/jpeg"))
		except Exception:
			pass
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
