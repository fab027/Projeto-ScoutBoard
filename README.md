# ScoutBoard

Painel de análise de desempenho do Campeonato Brasileiro Série A (2019 a 2025), a partir de
eventos de partida no formato SPADL: rankings de jogadores e times, dispersão de métricas,
posição média no campo, perfil do técnico e busca, estruturado sobre banco relacional expansível
para novas competições e temporadas.

## Estrutura


```

ScoutBoard/
├── iniciar.py              ponto de entrada: atualiza os técnicos e sobe o site
├── app.py                  ponto de entrada WSGI e comandos `flask --app app.py ...`
├── config.py               caminhos compartilhados
├── requirements.txt        dependências do site, da coleta e do processamento
├── requirements-dev.txt    testes (pytest), além do requirements.txt
├── sb_web/                 aplicação Flask no padrão Application Factory (create_app)
│   ├── rotas.py            páginas e API do site, escudos e fotos
│   ├── painel.py           cálculos da tela (funções puras, sem Flask)
│   ├── classificacao.py    tabela da CBF: recortes, sequência, destaques (funções puras)
│   ├── fonte_cbf.py        liga times e jogadores da base à CBF, ao Commons e às reservas
│   ├── campeonato/         modelos de competições, temporadas, times, elencos, jogos e atletas
│   ├── analytics/          modelos dos eventos táticos de partida no formato SPADL
│   ├── scout/              observações de scout: modelo, formulário (Flask-WTF), serviço e rotas
│   ├── erros.py            páginas de erro (400, 404, 500) e JSON de erro da API
│   ├── ext/                configuração (config), log, CSRF (csrf), banco (db / Flask-SQLAlchemy) e terminal (cli)
│   ├── templates/          páginas Jinja2
│   └── static/             CSS, JavaScript, Plotly local e logo
├── coleta/                 fontes externas
│   ├── cbf.py              classificação, elencos, jogos e fotos pelo site da CBF
│   ├── espn.py             reserva da CBF: classificação, jogos e escudos pela ESPN
│   ├── fotmob.py           fotos de jogadores e escudos pelo id do FotMob (dados/fotmob_ids.json)
│   ├── commons.py          escudos, fotos de técnicos e reserva de fotos pelo Wikimedia Commons
│   ├── thesportsdb.py      reserva da CBF para fotos de jogadores
│   ├── treinadores.py      técnicos atuais (Wikipédia) e histórico (Wikidata)
│   ├── whoscored.py        eventos SPADL pelo WhoScored (soccerdata)
│   ├── wikipedia.py        leitura do infobox de clubes (pt)
│   └── nomes.py            comparação de nomes sem acento e caixa
├── processamento/
│   └── metricas.py         métricas por jogador e jogo a partir dos eventos
├── dados/
│   ├── brutos/             eventos SPADL por temporada (ex.: BRA-Brasileirao2019.parquet)
│   └── metricas_jogador_jogo.parquet, treinadores.parquet, treinadores_times.csv, ...
├── pesquisa/               notebooks e scripts exploratórios (Spark, ML, testes de extração)
├── ferramentas/
│   └── verificar.py        checa dependências, testes e site de uma vez
└── tests/                  testes automatizados

```

## Instalação

Na raiz do projeto, no PowerShell:

```powershell
py -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

```

Se o PowerShell bloquear a ativação, rode uma vez:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

```

## Configuração (.env)

As configurações vêm de variáveis de ambiente, lidas do arquivo `.env` na raiz (não versionado).
Copie o modelo e ajuste:

```powershell
Copy-Item .env.example .env
```

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `SECRET_KEY` | chave de desenvolvimento | Assina a sessão e os tokens CSRF dos formulários. |
| `DATABASE_URL` | `sqlite:///scoutboard.db` | Banco de dados do SQLAlchemy. |
| `FLASK_DEBUG` | `0` | `1` liga o modo de depuração do Flask. |
| `LOG_LEVEL` | `INFO` | Nível do log no terminal (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `SCOUTBOARD_CONTATO` | vazio | Contato no User-Agent das consultas à Wikimedia. |
| `SCOUTBOARD_FOTOS_LENTAS` | `0` | `1` liga as fotos da CBF e do TheSportsDB. |

## Como rodar o site

```bash
python iniciar.py

```

O programa atualiza os **técnicos atuais** (Wikipédia pt, com o histórico do Wikidata) e sobe o
site em [http://127.0.0.1:5000](https://www.google.com/search?q=http://127.0.0.1:5000). Se não houver internet, o site sobe com os dados que já estão em
disco e avisa no terminal. Sem essa opção, o site sobe sem atualizar nada (`python iniciar.py`).

**O site sobe na hora e não coleta nada ao iniciar.** A atualização dos técnicos, que levava de 2 a
3 minutos a cada início, agora só roda quando pedida: `python iniciar.py --atualizar-tecnicos`.
Nenhuma página espera uma fonte externa para mostrar imagem (seção "Imagens rápidas", abaixo).

Para checar tudo (dependências, testes e site):

```bash
venv\Scripts\python.exe ferramentas\verificar.py

```

## CBF: classificação, escudos e fotos

`coleta/cbf.py` lê o site da CBF (cbf.com.br), que traz os dados em JSON dentro do HTML.
Nenhuma imagem é baixada para o projeto:

* **Escudos:** vêm do Wikimedia Commons (seção seguinte). O clube que não tem escudo lá usa o da
CBF: `/escudo/<team_id>?temporada=` redireciona para `conteudo.cbf.com.br/clubes/{id}/escudo.jpg`
e o navegador carrega direto de lá.
* **Fotos (desligadas por padrão):** as fotos de jogadores vêm do FotMob e do Commons (seções
seguintes). A CBF embute a foto na página de cada atleta, o que custa uma requisição por foto
(0,6 s cada, em fila: 38 s para um ranking de 2021); por isso ela só entra com a variável de
ambiente `SCOUTBOARD_FOTOS_LENTAS=1`. Com ela ligada, `/foto/jogador/<player_id>?temporada=`
acha o atleta pelo nome no elenco do time naquela temporada e devolve a imagem, guardada só na
memória do servidor e no cache do navegador. Entre homônimos ("Pedro" e "Pedro"), vence o apelido
ou nome completo mais parecido e, se ainda empatar, quem tem número de partidas na CBF parecido
com o de jogos na base. Na dúvida, não mostra foto.
* **Página Times:** classificação oficial (2019 até a temporada atual), com recortes Geral,
Mandante e Visitante, zonas da tabela, sequência recente, próximo jogo, destaques, artilharia e
ataque e defesa.

**Tudo sob demanda.** Nada é buscado ao subir o site. Cada temporada é lida na primeira vez que uma
página a pede, e só o necessário:

| O que a página pede | O que é lido |
| --- | --- |
| Aba Geral da página Times, escudo de clube que não está no Commons | a tabela da temporada (1 página da CBF) |
| Foto de um jogador | a página do time dele naquela temporada e a do atleta |
| Abas Mandante e Visitante | as páginas dos times que ainda faltam (até 20) |

O texto lido fica em `dados/cache/` (fora do git). Temporadas encerradas não são lidas de novo; a
em andamento é conferida a cada 15 minutos (só a tabela; os times são relidos se ela mudou). A
coleta faz no máximo 2 requisições por vez, com meio segundo entre elas: a CBF bloqueia o IP por
alguns minutos depois de rajadas, e quando isso acontece a coleta pausa por 5 minutos.

**Reservas.** Se a CBF não responder, a classificação e os jogos vêm da API pública da ESPN
(`coleta/espn.py`, sem cartões). O TheSportsDB (`coleta/thesportsdb.py`) também só entra com
`SCOUTBOARD_FOTOS_LENTAS=1`: a chave pública dele aceitou cerca de 10 buscas seguidas e depois
respondeu 429 por um minuto. Se nenhuma fonte responder, a página Times usa a tabela calculada
pela base e as imagens dão lugar às iniciais.

O servidor da CBF não envia o certificado intermediário dele; o certificado público que falta
fica em `coleta/certificados/` e a verificação HTTPS continua completa.

## Imagens rápidas: FotMob pelo id

Os sites que serviram de referência (Brasileirão em Dados) não consultam nenhuma
fonte na hora do acesso: publicam um retrato pronto dos dados. O ScoutBoard faz o mesmo com as
imagens. `dados/fotmob_ids.json` (texto, versionado) liga o `player_id` e o `team_id` da base ao id
do FotMob, e o endereço da imagem depende só desse id
(`images.fotmob.com/image_resources/playerimages/{id}.png`): achar a foto de um jogador é uma
consulta à memória, e o navegador a carrega direto de lá.

A ligação vem do [Brasileirão em Dados](https://brasileiraoemdados.com.br/) (Ioannis Canteiro /
DataFutebol), que usa os mesmos ids do WhoScored da base e publica o id do FotMob de cada jogador e
time da temporada em andamento em `data/core.json`. Uma requisição (3 s) atualiza o arquivo, sem
perder os ids de quem saiu do campeonato:

```powershell
python -m coleta.fotmob
```

| Ordem das fontes | Fotos de jogadores | Escudos |
| --- | --- | --- |
| 1 | FotMob pelo id (memória) | Wikimedia Commons (cache de 30 dias) |
| 2 | Wikimedia Commons (cache por clube) | FotMob pelo id (memória) |
| 3 | iniciais do jogador | CBF ou ESPN (só para clube fora das duas) |

Medido em nov/2026, com o cache vazio e depois de lido: as 52 fotos e os 20 escudos do ranking de
2025 saem em 0,9 s no total (antes, 11 s; o de 2021 levava 38 s) e as 734 fotos da página Jogadores
em 10,7 s (antes, 290 s). Cobertura do id do FotMob: 43 das 52 fotos do ranking de 2025, 60% dos
jogadores de 2025 e 20% dos de 2019; com o Commons, o ranking de 2019 chega a 40 de 53.

## Wikimedia Commons: escudos e fotos

`coleta/commons.py` usa só as APIs oficiais da Wikimedia (MediaWiki no Commons e na Wikipédia, e a
consulta SPARQL do Wikidata); nada de raspagem de páginas. Nenhuma imagem é baixada: o site
redireciona o navegador para a miniatura de 120 px no Commons, e em `dados/cache/commons-*.json`
fica só texto (nome do arquivo, endereço, autor e licença).

| Imagem | De onde vem | Cobertura medida (nov/2026) | Sem ela |
| --- | --- | --- | --- |
| Escudo do clube | imagem do infobox do clube na Wikipédia (pt) ou, na falta dela, o logotipo (P154) do Wikidata | 26 dos 30 clubes da base | escudo da CBF ou da ESPN |
| Foto do técnico | imagem (P18) do técnico no Wikidata, gravada pela coleta de técnicos | 85 de 121 técnicos; 18 dos 30 atuais | iniciais |
| Foto do jogador (depois do FotMob) | imagem (P18) de quem jogou pelo clube (P54) e tem exatamente o mesmo nome | 9 de 40 jogadores de 2025 | iniciais |

* **Escudos.** Só vale arquivo que está no Commons (domínio público ou licença livre) e que não é
fotografia. O escudo que a Wikipédia guarda só nela, como "uso restrito" (Corinthians, Red Bull
Bragantino, Sport e Vasco, hoje), fica de fora e o site usa o da CBF. Os escudos de todos os clubes
são lidos de uma vez, em 3 requisições (cerca de 6 s), e conferidos de novo a cada 30 dias. Não
dependem mais da tabela da CBF nem da temporada.
* **Nenhum pedido de imagem espera a Wikimedia.** O que falta é lido por uma thread à parte (cerca
de 20 s para os escudos e os 30 clubes); até lá o site usa a fonte seguinte, e a imagem do Commons
aparece no próximo carregamento. Para o primeiro acesso já sair completo, leia tudo antes:
`python -m coleta.commons`.
* **Jogadores.** O Commons tem foto de cerca de um em cada quatro jogadores, e o Wikidata nem
sempre registra o clube atual; por isso ele vem depois do FotMob. Não custa uma busca por jogador:
a lista de quem tem foto é lida uma vez por clube (1 a 2 s) e vale 30 dias. Com dois donos para o
mesmo nome, ou com idade que não bate com a temporada, não mostra foto.
* **Créditos.** `/creditos` (link no rodapé) lista cada arquivo do Commons que o site mostra, com
autor, licença e o endereço da página dele. As fotos de pessoas têm licenças que pedem atribuição
(CC BY, CC BY-SA); os escudos estão em domínio público por direito autoral, mas são marcas dos clubes.
* **Limites da Wikimedia.** Desde 2026, quem não manda contato no `User-Agent` fica limitado a 10
requisições por minuto em todas as APIs (Wikipédia, Wikidata e Commons); com contato, a 200. Para
se identificar, defina a variável de ambiente antes de subir o site ou rodar a coleta:

```powershell
$env:SCOUTBOARD_CONTATO="seu-email-ou-endereco-do-projeto"
```

Sem ela o site funciona do mesmo jeito, porque tudo é pedido em lote e em série; se a Wikimedia
responder 429, a coleta respeita o `Retry-After`, pausa por 5 minutos e o site segue com as reservas.

## Banco de dados

A camada de persistência utiliza **Flask-SQLAlchemy** (SQLAlchemy 2.x com `Mapped` e
`mapped_column`) integrada ao padrão *Application Factory* (`sb_web/ext/db` e `sb_web/ext/config`).
Por padrão, utiliza SQLite (`instance/scoutboard.db`), podendo apontar para outro SGBD (como
PostgreSQL ou MySQL) pela variável de ambiente `DATABASE_URL`.

### Modelagem relacional

O esquema é dividido em 8 tabelas normalizadas para suportar múltiplas ligas/países, atletas
homônimos na mesma edição e transferências de jogadores entre temporadas ou no meio do campeonato:

| Tabela | Modelo (`sb_web`) | Chave Primária e Restrições | Descrição |
| --- | --- | --- | --- |
| `competicoes` | `campeonato.models.Competition` | `id` (PK), `UNIQUE(pais, liga)` | País e liga da competição (ex.: `BRA` / `Brasileirao`). |
| `temporadas` | `campeonato.models.Season` | `id` (PK), `UNIQUE(competicao_id, temporada)` | Edições de cada competição (ex.: `2019` a `2025` ou `2024-2025`). |
| `times` | `campeonato.models.Team` | `team_id` (PK SPADL) | Cadastro único de clubes. |
| `jogadores` | `campeonato.models.Player` | `player_id` (PK SPADL) | Cadastro único de atletas pelo ID da base (evita colisão entre homônimos). |
| `elencos_temporada` | `campeonato.models.SquadMember` | `id` (PK), `UNIQUE(temporada_id, team_id, player_id)` | Vínculo associativo atleta-clube por temporada (permite transferências na mesma edição). |
| `jogos` | `campeonato.models.Match` | `game_id` (PK SPADL) | Partidas ligadas à temporada e aos clubes mandante (`home_team_id`) e visitante (`away_team_id`). |
| `eventos_partida` | `analytics.models.MatchEvent` | `id` (PK), `UNIQUE(game_id, action_id)` | Eventos SPADL (`period_id`, `time_seconds`, `start_x/y`, `end_x/y`, `type_id`, `result_id`, `bodypart_id`, `original_event_id`) ligados ao jogo, clube e atleta do lance. |
| `observacoes` | `scout.models.Observacao` | `id` (PK), `CHECK(nota BETWEEN 1 AND 10)` | Anotação de scout sobre um atleta em uma temporada: autor, nota, texto e data (UTC). |

### Observações de scout (formulário e ORM)

A página **Observações** (`/observacoes/`) lê e grava no banco pelo SQLAlchemy. Em **Jogadores**,
o link “Anotar” abre o formulário de nova observação, feito com **Flask-WTF/WTForms**
(`sb_web/scout/forms.py`) e validado no servidor: campos obrigatórios, tamanho do nome e do texto,
nota de 1 a 10, temporada existente e jogador presente na base. Envio inválido volta com status 400,
os erros ao lado de cada campo e o que foi digitado. Todo POST exige token CSRF (`sb_web/ext/csrf`).

Ao gravar, o jogador entra na tabela `jogadores` se ainda não estiver lá, na mesma transação da
observação. A lista mostra as observações mais recentes e a média das notas por jogador.

### Carga de dados (Flask CLI)

O comando `importar-brutos` (`sb_web/ext/cli`) lê os arquivos `.parquet` em `dados/brutos/` no
padrão `<PAIS>-<Liga><Temporada>.parquet`, extrai automaticamente `pais`, `liga` e `temporada` do
nome do arquivo, cria as tabelas caso não existam e grava os registros em lotes:

```powershell
# Importa todas as temporadas do Brasileirão (padrão: BRA-Brasileirao20*.parquet)
flask --app app.py importar-brutos

# Importa apenas uma temporada específica
flask --app app.py importar-brutos --padrao "BRA-Brasileirao2025.parquet"

# Importa todas as competições presentes na pasta dados/brutos/
flask --app app.py importar-brutos --padrao "*.parquet" --tamanho-lote 25000

```

### Inspeção e validação no `flask shell`

Para validar modelos, relacionamentos e restrições de unicidade em um banco SQLite isolado em
memória (sem alterar o `scoutboard.db` local):

```powershell
$env:DATABASE_URL="sqlite:///:memory:"
flask --app app.py shell

```

Ao encerrar os testes em memória, remova a variável temporária da sessão do PowerShell:

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

```

## Coleta de dados

| O que | Comando | Observação |
| --- | --- | --- |
| Técnicos atuais | `python iniciar.py --atualizar-tecnicos` | Só quando pedido: leva de 2 a 3 minutos. |
| Ids do FotMob (fotos e escudos) | `python -m coleta.fotmob` | Uma requisição; grava `dados/fotmob_ids.json`. |
| Escudos e fotos do Commons | `python -m coleta.commons` | Opcional: o site lê sozinho, em segundo plano. |
| Técnicos (histórico completo) | `python -m coleta.treinadores` | Wikidata (histórico e foto) e Wikipédia (pt). Divergências em `dados/treinadores_status.json`. |
| Configurar o WhoScored | `python -m coleta.whoscored configurar` | Uma vez por máquina. |
| Eventos de uma temporada | `python -m coleta.whoscored temporada 2024` | Use `--ids-arquivo` se o calendário do soccerdata falhar. |
| Métricas por jogador e jogo | `python -m processamento.metricas` | Lê `dados/brutos/` e grava `dados/metricas_jogador_jogo.parquet`. |

Ao rodar `coleta.treinadores`, o arquivo de técnicos é reescrito do zero. Para ver o técnico
atual atualizado depois disso, rode `python iniciar.py` de novo.

O que o site busca sozinho, quando uma página pede (texto em `dados/cache/`, fora do git):

| Fonte | O que | Quando | Se falhar |
| --- | --- | --- | --- |
| CBF (`coleta/cbf.py`) | classificação, artilharia, elencos e jogos | página Times (0,5 a 3 s por temporada; aba Mandante, 11 s na primeira vez) | ESPN |
| Wikimedia Commons (`coleta/commons.py`) | escudos, fotos de técnicos e de jogadores | em segundo plano; vale 30 dias | FotMob; iniciais |
| ESPN (`coleta/espn.py`) | classificação, jogos, artilharia e escudos | só quando a CBF não responde | tabela calculada pela base |
| CBF e TheSportsDB, fotos | foto de um jogador, uma requisição cada | só com `SCOUTBOARD_FOTOS_LENTAS=1` | iniciais |

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest

```

## Pontos de atenção

* **Técnico atual:** a Wikipédia tem prioridade sobre o Wikidata. Quando os dois divergem, a
divergência fica em `dados/treinadores_status.json`, para conferência.
* **Credenciais:** nenhum arquivo de credencial vai para o git (`.env` e `*.db` estão no `.gitignore`).
O projeto não usa mais credenciais do Google Drive. Se alguma já esteve num commit, revogue-a.
* **Minutos** são estimativas (intervalo entre o primeiro e o último evento do jogador).

## Autores
* **Fabricio Nascimento**
* **Mateus Fonseca**
* **Yago Van Der Maas**
