# Armazenamento permanente no plano Free

O site pode usar o Render Free junto com Supabase e Cloudinary gratuitos:

- Supabase guarda a configuracao, links, textos e lista de stories.
- Cloudinary guarda as imagens enviadas pelo painel.
- Render executa a aplicacao.

## 1. Criar a tabela no Supabase

No SQL Editor do projeto Supabase, execute:

```sql
create table if not exists public.site_config (
  key text primary key,
  config jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.site_config enable row level security;
```

A aplicacao usa a chave de servico apenas no backend do Render. Nunca coloque essa chave no HTML ou no GitHub.

## 2. Criar a conta Cloudinary

No painel Cloudinary, copie:

- Cloud name
- API Key
- API Secret

As imagens enviadas pelo admin serao gravadas na pasta `gjfortunesinais/admin`.

## 3. Variaveis no Render

Em Environment, adicione os valores:

- `SUPABASE_URL`: URL do projeto Supabase
- `SUPABASE_SERVICE_KEY`: chave de servico do Supabase
- `CLOUDINARY_CLOUD_NAME`: Cloud name
- `CLOUDINARY_API_KEY`: API Key
- `CLOUDINARY_API_SECRET`: API Secret

Depois salve e faca um deploy manual.

## 4. Validacao

Apos o deploy, abra o admin e salve uma configuracao pequena. Confirme no Supabase se apareceu a linha com `key = main` e no Cloudinary se apareceu a imagem. Em seguida reinicie o servico e confirme que os dados continuam na home.

Enquanto essas variaveis nao estiverem configuradas, o site continua usando o armazenamento local atual como fallback.
