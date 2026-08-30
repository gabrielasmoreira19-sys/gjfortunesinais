import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD")
if not PANEL_PASSWORD:
    raise RuntimeError("Defina PANEL_PASSWORD no arquivo .env antes de iniciar o painel.")

app = Flask(__name__)
app.secret_key = os.urandom(32)
processo_santos = None
lock_processo = threading.Lock()


def santos_ativa():
    return processo_santos is not None and processo_santos.poll() is None


def exige_login():
    return session.get("autorizado") is not True


@app.route("/", methods=["GET"])
def inicio():
    if exige_login():
        return redirect(url_for("login"))
    return render_template("painel_santos.html", ativa=santos_ativa())


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        if request.form.get("senha") == PANEL_PASSWORD:
            session["autorizado"] = True
            return redirect(url_for("inicio"))
        erro = "Senha incorreta."
    return render_template("login_santos.html", erro=erro)


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
