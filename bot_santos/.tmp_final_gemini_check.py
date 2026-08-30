from dotenv import load_dotenv
import os
load_dotenv(dotenv_path=r'C:\Users\tikooh\Downloads\gjfortunesinais-correto\bot_santos\.env')
import google.generativeai as genai
genai.configure(api_key=os.environ.get('GEMINI_KEY'))
models = ['gemini-3.6-flash', 'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest']
for nome in models:
    try:
        model = genai.GenerativeModel(model_name=nome, generation_config={'temperature': 0.7, 'max_output_tokens': 100})
        resp = model.generate_content('Diga apenas: teste ok')
        print(f"{nome} -> SUCESSO: {repr(resp.text)[:80]}")
    except Exception as e:
        print(f"{nome} -> ERRO: {type(e).__name__} {str(e)[:200]}")
