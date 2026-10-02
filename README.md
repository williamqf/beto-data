# Beto Data

Nome do repositório: `beto-data`.

Infraestrutura pública de dados do Beto. Este repositório é independente do app Android e contém apenas importadores, testes, documentação e dados agregados de fontes públicas.

## Fonte e escopo atual

A Fase 1 consome o resumo semanal oficial da ANP: [Levantamento de preços de combustíveis — últimas semanas pesquisadas](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas). A planilha é descoberta pelo índice oficial, validada e normalizada sem recalcular médias. O pacote contém dados nacionais e por UF, inclusive agregados municipais divulgados pela própria ANP; não contém preços identificáveis por posto.

Os dados publicados têm origem na ANP e são atribuídos à agência; não são propriedade do Beto. O Beto não reivindica titularidade sobre os dados de origem. Consulte a fonte oficial para metodologia, período de referência e condições de reutilização.

> O Beto é um projeto independente e não é afiliado, patrocinado ou endossado pela Agência Nacional do Petróleo, Gás Natural e Biocombustíveis — ANP.

### INMETRO — PBE Veicular (Fase 2)

O pipeline descobre os ciclos na [página oficial de veículos automotivos do PBE Veicular](https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/veiculos-automotivos-pbe-veicular), baixa as tabelas oficiais e só publica após reconhecer o perfil da tabela, validar os registros e gerar os checksums. Os perfis de extração cobrem as edições de 2010–2026, com esquemas separados para 2010–2012, 2013–2016, 2017–2020 e os formatos posteriores. Os ciclos históricos já validados são reutilizados do catálogo publicado enquanto a referência do documento oficial permanecer igual; isso evita baixar e reprocessar todos os PDFs antigos diariamente. Se a extração de uma atualização não alinhar os campos com segurança, o último dataset PBE válido é preservado e a etapa ANP continua independente. Ciclo PBE é guardado como origem e **não** é interpretado como ano/modelo.

O dataset mantém atributos técnicos para busca e, quando publicados, consumo urbano/rodoviário, consumo energético, autonomia elétrica, classe e selo. A sugestão automática do app nesta fase limita-se a consumo urbano para gasolina e etanol; cada combustível flex permanece separado. GNV, elétricos, híbridos e PHEV continuam manuais no app. PDFs não são incluídos na publicação Pages.

Os dados do PBE Veicular são atribuídos ao INMETRO e não pertencem ao Beto. O Beto é independente e não é afiliado, patrocinado ou endossado pelo INMETRO.

## Licença do código

O código original do pipeline neste repositório é licenciado sob GNU GPL versão 3 (GPL-3.0-only), em linha com a licença já adotada no repositório principal do Beto. Consulte o [texto completo da GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html). Esta licença cobre o código do pipeline, não os dados da ANP, marcas, nomes ou materiais de terceiros. Os datasets mantêm a atribuição e as condições aplicáveis à fonte original.

O app baixa o manifesto e somente os arquivos JSON versionados necessários. Cidade, placa, localização precisa, preferências, identificadores e logs dos motoristas não são enviados nem armazenados aqui. O nome da cidade escolhido no app permanece local; a UF seleciona o arquivo regional.

Diesel e GLP podem existir no dataset da ANP, mas a UI atual do app oferece apenas combustíveis que ela suporta. Consulta por placa não faz parte do escopo deste repositório.

### IPVA estadual (Fase 2B)

As regras de IPVA consumidas pelo Android ficam neste repositório; não há alíquotas por UF/exercício embutidas no app. O primeiro recorte contempla MG, SP e PR para o exercício 2026, com categoria e combustível explicitamente suportados. Tipos de veículo, propulsões e exceções não cobertos ficam para preenchimento manual no app.

O pipeline valida as páginas oficiais antes de montar a publicação. MG usa a [SEF/MG — legislação e dúvidas frequentes](https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ipva/duvidas_frequentes/) e o índice oficial das [tabelas de base do exercício](https://diarioeletronico.fazenda.mg.gov.br/opendiariogeral/resultados-ipva/index.html). SP usa a [Lei estadual 13.296/2008 compilada](https://www.al.sp.gov.br/repositorio/legislacao/lei/2008/lei-13296-23.12.2008.html) e a página da [SEFAZ/SP sobre IPVA e valores venais](https://portal.fazenda.sp.gov.br/servicos/ipva/Paginas/perguntas-frequentes.aspx). PR usa as publicações oficiais sobre [alíquotas de 2026](https://www.fazenda.pr.gov.br/Noticia/Com-aliquota-de-19-e-desconto-vista-Fazenda-divulga-datas-do-IPVA-2026) e [valor venal de mercado](https://www.fazenda.pr.gov.br/Noticia/Com-reducao-de-45-Parana-tera-menor-aliquota-de-IPVA-do-Brasil-em-2026).

Os datasets distinguem a regra legal da base. Nesta versão ainda não há tabela estadual normalizada com correspondência confiável por veículo; por isso o app usa FIPE compatível como base estimada, com sua origem e qualidade identificadas, ou exige valor manual quando não há correspondência segura. Não classifica FIPE como base oficial exata. A redução legal de 30% da base em MG só é aplicada ao combustível exclusivamente álcool, conforme a fonte estadual. No PR a regra especial de GNV é separada da alíquota geral de automóveis. Outras exceções só entram depois de validação oficial explícita.

O manifesto público integrado é [`https://williamqf.github.io/beto-data/manifest.json`](https://williamqf.github.io/beto-data/manifest.json). A ramificação IPVA lista os arquivos anuais. Para 2026, os caminhos esperados são:

- [`datasets/taxes/ipva/2026/MG.json`](https://williamqf.github.io/beto-data/datasets/taxes/ipva/2026/MG.json)
- [`datasets/taxes/ipva/2026/SP.json`](https://williamqf.github.io/beto-data/datasets/taxes/ipva/2026/SP.json)
- [`datasets/taxes/ipva/2026/PR.json`](https://williamqf.github.io/beto-data/datasets/taxes/ipva/2026/PR.json)

Esses links ficam ativos depois que o repositório público e o GitHub Pages recebem esta versão. O Android baixa o manifesto e o dataset da UF, valida schema, exercício, versão, checksum e origem, e mantém cópia válida local para uso offline. Se não houver dados remotos nem cache, o fluxo continua com entrada manual.

## Estrutura

```text
.github/workflows/update-anp.yml  # valida ANP + PBE e publica a distribuição
.github/workflows/update-ipva.yml # valida regras fiscais e publica IPVA sazonalmente
src/update_anp.py                 # pipeline ANP
src/update_inmetro.py             # descoberta/PDF/validação do PBE Veicular
src/update_ipva.py                # valida fontes oficiais e gera regras estaduais
tests/                             # fixtures pequenas e testes offline
requirements.txt                   # dependências do pipeline
dist/manifest.json                 # manifesto público consumido pelo Android
dist/datasets/fuel/<versão>/*.json # dados públicos ANP por Brasil/UF
dist/datasets/vehicle-efficiency/  # catálogo e ciclos PBE normalizados
```

O GitHub Pages publica **somente `dist/`**. Planilhas XLSX/CSV, arquivos temporários, cache do runner e código Android não são publicados.

## Atualização e publicação

O workflow roda diariamente às 12:20 UTC (09:20 no horário de Brasília) e também pode ser iniciado manualmente em **Actions → Beto Data — ANP + INMETRO → Run workflow**. A ANP só republica quando a versão semanal muda; o PBE verifica a página oficial e republica quando ciclos/tabelas ou conteúdos mudarem. Ambos preservam as ramificações um do outro no manifesto/distribuição. Se descoberta, download, esquema ou validação falharem, a execução falha sem substituir o último conjunto válido.

Não há secrets necessários para ANP ou INMETRO. O workflow usa somente `GITHUB_TOKEN` efêmero com permissões `contents: read`, `pages: write` e `id-token: write`, concedidas pelo próprio GitHub Actions. Não configure token pessoal.

## Configuração inicial no GitHub

1. Crie `beto-data` como **Public** na conta `williamqf`.
2. Envie o conteúdo desta pasta como raiz do repositório, incluindo `.github/` e `dist/`.
3. Em **Settings → Pages → Build and deployment**, escolha **GitHub Actions**.
4. Em **Settings → Actions → General → Workflow permissions**, mantenha acesso de leitura ao conteúdo; as permissões de Pages estão declaradas no workflow.
5. Em **Actions**, execute **Beto Data — ANP + INMETRO** manualmente. O job atualiza ambas as fontes oficiais e publica a distribuição integrada.
6. Confirme `https://williamqf.github.io/beto-data/manifest.json`, o ramo `vehicleEfficiency` e os arquivos listados em `datasets`/`cycles`.

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
python src/update_inmetro.py
python src/update_ipva.py
```

Os testes usam workbooks e registros sintéticos pequenos, sem depender de rede. O parser também é validado localmente contra os PDFs oficiais baixados durante o desenvolvimento; eles não são fixtures nem são publicados no Pages. O diretório `dist/` contém a cópia versionada que inicializa a primeira publicação e permite validar os hashes.
