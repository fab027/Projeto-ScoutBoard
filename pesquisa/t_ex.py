import soccerdata as sd
import pandas as pd
import socceraction.spadl as spadl

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

ws = sd.WhoScored(leagues="BRA-Brasileirao", seasons="2025")

print("1. Acessando calendário...")
calendario = ws.read_schedule().reset_index()

# Filtra a partida alvo e pega o ID
jogo_alvo = calendario[(calendario['home_team'] == 'Flamengo') & (calendario['away_team'] == 'Gremio')]
id_da_partida = jogo_alvo['game_id'].tolist()

print("2. Lendo eventos e traduzindo para a linguagem universal SPADL...")
eventos_spadl = ws.read_events(match_id=id_da_partida, output_fmt='spadl')

# Vamos mesclar as informações visuais (nomes de times, tipos de ação e resultados)
df_times = ws.read_schedule().reset_index()
dict_times_casa = dict(zip(df_times['home_team_id'], df_times['home_team']))
dict_times_fora = dict(zip(df_times['away_team_id'], df_times['away_team']))
dict_times = {**dict_times_casa, **dict_times_fora}

# Adicionando colunas com nomes para ficar fácil de ler
eventos_spadl['team_name'] = eventos_spadl['team_id'].map(dict_times)
# Mapeia os IDs numéricos usando a própria biblioteca do VAEP
eventos_spadl = eventos_spadl.merge(spadl.actiontypes_df(), on="type_id")
eventos_spadl = eventos_spadl.merge(spadl.results_df(), on="result_id")

# Ordena cronologicamente para não bagunçar a sequência do jogo
eventos_spadl = eventos_spadl.sort_values(by=['period_id', 'time_seconds'])

print("\n--- Lance a Lance no Formato SPADL (Em Metros) ---")
colunas_chave = ['period_id', 'time_seconds', 'team_name', 'type_name', 'result_name', 'start_x', 'start_y', 'end_x', 'end_y']
print(eventos_spadl[colunas_chave].head(15))

# Como queremos buscar o pênalti, o SPADL classifica chutes e sofrimento de pênaltis de forma específica
chutes = eventos_spadl[eventos_spadl['type_name'].isin(['shot', 'shot_penalty'])]
print("\n--- Finalizações e Pênaltis ---")
print(chutes[colunas_chave].tail())