# Beto Data

Nome do repositório: `beto-data`.

Infraestrutura pública de dados do Beto. Este repositório é independente do app Android e contém apenas importadores, testes, documentação e dados agregados de fontes públicas.

## Fonte e escopo atual

A Fase 1 consome o resumo semanal oficial da ANP: [Levantamento de preços de combustíveis — últimas semanas pesquisadas](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas). A planilha é descoberta pelo índice oficial, validada e normalizada sem recalcular médias. O pacote contém dados nacionais e por UF, inclusive agregados municipais divulgados pela própria ANP; não contém preços identificáveis por posto.

O app baixa o manifesto e somente os arquivos JSON versionados necessários. Cidade, placa, localização precisa, preferências, identificadores e logs dos motoristas não são enviados nem armazenados aqui. O nome da cidade escolhido no app permanece local; a UF seleciona o arquivo regional.

Diesel e GLP podem existir no dataset da fonte, mas a UI atual do app oferece apenas combustíveis que ela suporta. Inmetro, placa e IPVA não fazem parte desta fase.

## Estrutura

```text
.github/workflows/update-anp.yml  # valida, atualiza e publica
src/update_anp.py                 # descoberta, parsing, validação e normalização
tests/                             # fixtures sintéticas e testes offline
requirements.txt                   # dependências do pipeline
dist/manifest.json                 # manifesto público consumido pelo Android
dist/datasets/fuel/<versão>/*.json # dados públicos por Brasil/UF
```

O GitHub Pages publica **somente `dist/`**. Planilhas XLSX/CSV, arquivos temporários, cache do runner e código Android não são publicados.

## Atualização e publicação

O workflow roda diariamente às 12:20 UTC (09:20 no horário de Brasília) e também pode ser iniciado manualmente em **Actions → Beto Data — ANP → Run workflow**. A fonte da ANP é semanal: o job valida diariamente, mas só substitui/publica os dados quando a versão semanal mudar. Se download, esquema ou validação falharem, a execução falha sem trocar o último dataset válido.

Não há secrets necessários para a ANP. O workflow usa somente `GITHUB_TOKEN` efêmero com permissões `contents: read`, `pages: write` e `id-token: write`, concedidas pelo próprio GitHub Actions. Não configure token pessoal.

## Configuração inicial no GitHub

1. Crie `beto-data` como **Public** na conta `williamqf`.
2. Envie o conteúdo desta pasta como raiz do repositório, incluindo `.github/` e `dist/`.
3. Em **Settings → Pages → Build and deployment**, escolha **GitHub Actions**.
4. Em **Settings → Actions → General → Workflow permissions**, mantenha acesso de leitura ao conteúdo; as permissões de Pages estão declaradas no workflow.
5. Em **Actions**, execute **Beto Data — ANP** manualmente. O primeiro deploy publica o `dist/` versionado; o job também tenta buscar o resumo mais recente da ANP.
6. Confirme `https://williamqf.github.io/beto-data/manifest.json` e um arquivo listado em `datasets`.

## Endpoint Android

Após a URL do Pages responder corretamente, configure uma única vez no build Release:

```text
https://williamqf.github.io/beto-data
```

O app Beto acrescenta `/manifest.json` e os caminhos relativos do manifesto. A URL é centralizada em `app/build.gradle` por `BuildConfig.BETO_DATA_BASE_URL`; não é repetida no repositório Android. O Debug aceita `BETO_DATA_DEBUG_URL` para apontar a servidor local, fixture servida por HTTP no ambiente de desenvolvimento ou endpoint de teste. Testes unitários usam fixtures em memória.

Até o endpoint ser ativado no app, o preenchimento manual continua disponível. Falha/404 de rede não causa crash, e o cache válido existente continua utilizável offline. A atualização do JSON publicado não exige rebuild do Android.

## Desenvolvimento local

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python src/update_anp.py
```

Os testes usam workbooks sintéticos pequenos, sem dados de motorista nem conexão externa. O diretório `dist/` contém a cópia versionada que inicializa a primeira publicação e permite validar os hashes.
