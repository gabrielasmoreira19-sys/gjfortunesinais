import json
import re
from urllib.request import Request, urlopen

URL = "https://www.grupofpsinais.fun"


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_tags(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def extract_games(clean_text: str, limit: int = 10):
    matches = []
    pattern = re.compile(
        r"(?P<nome>[A-Za-zÀ-ÿ0-9' .-]+?)\s+(?:Aposta Mínima:\s*(?P<minimo>\d{1,3})%\s*Aposta Padrão:\s*(?P<padrao>\d{1,3})%\s*Aposta Máxima:\s*(?P<maximo>\d{1,3})%\s*Distribuição:\s*(?P<distribuicao>\d{1,3})%|Aposta Mínima:\s*(?P<minimo2>\d{1,3})%\s*Aposta Padrão:\s*(?P<padrao2>\d{1,3})%\s*Aposta Máxima:\s*(?P<maximo2>\d{1,3})%\s*Distribuição:\s*(?P<distribuicao2>\d{1,3})%)",
        re.I,
    )
    for match in pattern.finditer(clean_text):
        nome = re.sub(r"\s+", " ", match.group("nome")).strip()
        if not nome or len(nome) < 3:
            continue
        minimo = match.group("minimo") or match.group("minimo2")
        padrao = match.group("padrao") or match.group("padrao2")
        maximo = match.group("maximo") or match.group("maximo2")
        distribuicao = match.group("distribuicao") or match.group("distribuicao2")
        matches.append({
            "nome": nome,
            "aposta_minima": int(minimo) if minimo else None,
            "aposta_padrao": int(padrao) if padrao else None,
            "aposta_maxima": int(maximo) if maximo else None,
            "distribuicao": int(distribuicao) if distribuicao else None,
        })
        if len(matches) >= limit:
            break
    return matches


if __name__ == "__main__":
    html = fetch_html(URL)
    clean_text = strip_tags(html)
    games = extract_games(clean_text, limit=12)
    print(f"HTML capturado: {len(html)} caracteres")
    print(f"Jogos extraídos: {len(games)}")
    print(json.dumps(games, ensure_ascii=False, indent=2))
