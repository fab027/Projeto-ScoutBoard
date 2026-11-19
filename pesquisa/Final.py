# Databricks notebook source
import pyspark.sql.functions as F
from pyspark.sql.window import Window
from functools import reduce

print("1. Carregando dados do Data Lake...")
arquivos = dbutils.fs.ls("/Volumes/workspace/default/parquet/")
lista_dfs = [spark.read.parquet(f.path) for f in arquivos if f.name.startswith("BRA-")]
df_spark = reduce(lambda df1, df2: df1.unionByName(df2, allowMissingColumns=True), lista_dfs)

print("2. Mapeamento SPADL e Correção de Minutos...")
# Ações e posições
df_acoes = df_spark.withColumn('is_desarme', F.when((F.col('type_id') == 9) & (F.col('result_id') == 1), 1).otherwise(0)) \
                   .withColumn('is_driblado', F.when((F.col('type_id') == 9) & (F.col('result_id') == 0), 1).otherwise(0)) \
                   .withColumn('is_interceptacao', F.when((F.col('type_id') == 10) & (F.col('result_id') == 1), 1).otherwise(0)) \
                   .withColumn('is_corte', F.when(F.col('type_id') == 18, 1).otherwise(0)) \
                   .withColumn('is_falta', F.when(F.col('type_id') == 8, 1).otherwise(0)) \
                   .withColumn('is_keeper', F.when(F.col('type_id').between(14, 17), 1).otherwise(0)) \
                   .withColumn('is_chute', F.when(F.col('type_id') == 11, 1).otherwise(0))

# Granularidade por Jogo
df_scout_jogo = df_acoes.groupBy('game_id', 'player', 'team_id').agg(
    F.sum('is_desarme').alias('desarmes'), F.sum('is_interceptacao').alias('interceptacoes'),
    F.sum('is_corte').alias('cortes'), F.sum('is_falta').alias('faltas'),
    F.sum('is_driblado').alias('driblado'), F.sum('is_keeper').alias('acoes_goleiro'),
    F.sum('is_chute').alias('finalizacoes')
)

# Correção de Minutos e Posse de Bola
janela_jogo = Window.partitionBy('game_id')
df_posse = df_spark.filter(F.col('type_id') == 0).groupBy('game_id', 'team_id').count().withColumnRenamed('count', 'passes_time') \
                   .withColumn('passes_totais', F.sum('passes_time').over(janela_jogo)) \
                   .withColumn('posse_bola', (F.col('passes_time') / F.col('passes_totais')) * 100)

df_minutos_jogo = df_spark.groupBy('game_id', 'player', 'team_id', 'period_id') \
                          .agg((F.max('time_seconds') / 60).alias('min'), F.max('player_id').cast('long').alias('player_id')) \
                          .groupBy('game_id', 'player', 'team_id').agg(F.sum('min').alias('minutos_jogados'), F.max('player_id').alias('player_id'))

df_game_log = df_minutos_jogo.join(df_scout_jogo, on=['game_id', 'player', 'team_id'], how='inner') \
                              .join(df_posse.select('game_id', 'team_id', 'posse_bola'), on=['game_id', 'team_id'], how='left')

# Injeção da Temporada (Extraída dos metadados)
df_caminhos = reduce(lambda df1, df2: df1.unionByName(df2, allowMissingColumns=True),
    [spark.read.parquet(f.path).select('game_id', F.col('_metadata.file_path').alias('file_path'))
     for f in arquivos if f.name.startswith("BRA-")]) \
    .withColumn('temporada', F.regexp_extract(F.col('file_path'), r'_(\d{4})', 1)) \
    .select('game_id', 'temporada').distinct()
df_game_log_temp = df_game_log.join(df_caminhos, on='game_id', how='inner')

print("3. Construindo Features de Contexto para ML...")
janela_estado_jogo = Window.partitionBy('game_id', 'period_id').orderBy('time_seconds')
df_ml_contexto = df_spark.withColumn('acao_anterior_id', F.lag('type_id', 1).over(janela_estado_jogo)) \
                         .withColumn('x_origem_anterior', F.lag('start_x', 1).over(janela_estado_jogo)) \
                         .withColumn('y_origem_anterior', F.lag('start_y', 1).over(janela_estado_jogo)) \
                         .withColumn('x_destino_anterior', F.lag('end_x', 1).over(janela_estado_jogo)) \
                         .withColumn('y_destino_anterior', F.lag('end_y', 1).over(janela_estado_jogo)) \
                         .withColumn('time_anterior_id', F.lag('team_id', 1).over(janela_estado_jogo)) \
                         .withColumn('delta_tempo_segundos', F.col('time_seconds') - F.lag('time_seconds', 1).over(janela_estado_jogo)) \
                         .withColumn('recuperou_posse', F.when(F.col('team_id') != F.col('time_anterior_id'), 1).otherwise(0))

display(
    df_game_log_temp.filter(F.col('player').contains('Thiago Maia'))
    .select('temporada', 'game_id','player','player_id', 'team_id')
)



# COMMAND ----------

# DBTITLE 1,Cell 2
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.classification import GBTClassifier
from pyspark.ml.regression import GBTRegressor
from pyspark.ml import Pipeline
from pyspark.sql import Window
import pyspark.sql.functions as F

print("00. Preparando os Rótulos (Labels) para a IA com Lookahead (k=10)...")

# Define a janela cronológica olhando para a ação atual e as 10 ações seguintes
janela_k10 = Window.partitionBy('game_id', 'period_id') \
                   .orderBy('time_seconds') \
                   .rowsBetween(0, 10)

# Identifica o milissegundo exato do gol
df_ml_treino = df_ml_contexto.withColumn(
    'evento_gol_exato', 
    F.when((F.col('type_id') == 11) & (F.col('result_id') == 1), 1).otherwise(0)
)

# Se houver gol em qualquer uma das próximas 10 ações, a ação atual recebe o rótulo 1
df_ml_treino = df_ml_treino.withColumn(
    'is_gol', 
    F.max('evento_gol_exato').over(janela_k10)
).fillna(0)

print("0.5 Normalizando a Direção de Ataque (Sempre atacando para X = 105)...")

# 1. Identifica a direção de ataque usando os chutes (type_id == 11)
df_chutes = df_ml_contexto.filter(F.col('type_id') == 11)

# Calcula a coordenada X média dos chutes de cada time por jogo
df_direcao = df_chutes.groupBy('game_id', 'team_id').agg(
    F.avg('start_x').alias('x_medio_chutes')
)

# Se a média dos chutes for menor que 52.5 (meio de campo), o time está atacando para o X=0.
df_direcao = df_direcao.withColumn(
    'ataca_para_esquerda',
    F.when(F.col('x_medio_chutes') < 52.5, 1).otherwise(0)
)

# 2. Cruza a flag de direção com a base completa de matrizes
df_ml_contexto_corrigido = df_ml_treino.join(
    df_direcao.select('game_id', 'team_id', 'ataca_para_esquerda'),
    on=['game_id', 'team_id'],
    how='left'
).fillna({'ataca_para_esquerda': 0}) 

# 3. Espelha as coordenadas (X e Y) para o time que está atacando "invertido"
# O campo SPADL tem 105m de comprimento por 68m de largura
df_ml_treino_norm = df_ml_contexto_corrigido.withColumn(
    'start_x_norm', 
    F.when(F.col('ataca_para_esquerda') == 1, 105.0 - F.col('start_x')).otherwise(F.col('start_x'))
).withColumn(
    'start_y_norm', 
    F.when(F.col('ataca_para_esquerda') == 1, 68.0 - F.col('start_y')).otherwise(F.col('start_y'))
).withColumn(
    'x_destino_anterior_norm', 
    F.when(F.col('ataca_para_esquerda') == 1, 105.0 - F.col('x_destino_anterior')).otherwise(F.col('x_destino_anterior'))
).withColumn(
    'y_destino_anterior_norm', 
    F.when(F.col('ataca_para_esquerda') == 1, 68.0 - F.col('y_destino_anterior')).otherwise(F.col('y_destino_anterior'))
)

# O VectorAssembler agora usa as coordenadas purificadas e orientadas direcionalmente
features_cols = [
    'start_x_norm', 'start_y_norm', 
    'x_destino_anterior_norm', 'y_destino_anterior_norm', 
    'delta_tempo_segundos', 'recuperou_posse'
]

assembler = VectorAssembler(inputCols=features_cols, outputCol="features")

# O restante do pipeline pipeline.fit() segue inalterado, 
# mas usando o df_ml_treino_norm como base.

print("1. Treinando Rede Neural de Risco de Gol (dVAEP & oVAEP)...")
gbt = GBTClassifier(labelCol="is_gol", featuresCol="features", maxIter=20)
modelo_treinado = Pipeline(stages=[assembler, gbt]).fit(df_ml_treino_norm)

extrair_prob = F.udf(lambda v: float(v[1]), "double")
df_previsoes = modelo_treinado.transform(df_ml_treino_norm)
df_probabilidades = df_previsoes.withColumn("probabilidade_gol", extrair_prob(F.col("probability"))) \
                                .withColumn("dvaep_lance", F.col("probabilidade_gol") * F.when(F.col("recuperou_posse") == 1, 1.5).otherwise(-0.5))

print("2. Treinando Regressor de Ameaça Impedida (DAxT)...")
janela_jogo_ml = Window.partitionBy('game_id', 'period_id').orderBy('time_seconds')
df_ovaep = df_probabilidades.withColumn("prob_gol_atual", F.col("probabilidade_gol")) \
                            .withColumn("prob_gol_anterior", F.lag("probabilidade_gol", 1).over(janela_jogo_ml)).fillna({"prob_gol_anterior": 0.0}) \
                            .withColumn("ovaep_lance", F.when(F.col('type_id').isin([0, 1, 11, 21]), (F.col("prob_gol_atual") - F.col("prob_gol_anterior"))).otherwise(0.0))

df_daxt_contexto = df_ovaep.withColumn('xT_anterior_1', F.lag('prob_gol_atual', 1).over(janela_jogo_ml)) \
                           .withColumn('xT_anterior_2', F.lag('prob_gol_atual', 2).over(janela_jogo_ml)) \
                           .withColumn('x_anterior_1', F.lag('start_x', 1).over(janela_jogo_ml)) \
                           .withColumn('x_anterior_2', F.lag('start_x', 2).over(janela_jogo_ml)).fillna(0.0)

is_acao_defensiva = F.col('type_id').isin([8, 17])
assembler_daxt = VectorAssembler(inputCols=['xT_anterior_1', 'xT_anterior_2', 'x_anterior_1', 'x_anterior_2'], outputCol="features_daxt")
gbt_regressor = GBTRegressor(featuresCol="features_daxt", labelCol="prob_gol_atual", predictionCol="prediction_daxt", lossType="absolute", maxIter=20)

df_treino_daxt = assembler_daxt.transform(df_daxt_contexto)
modelo_daxt = gbt_regressor.fit(df_treino_daxt.filter(~is_acao_defensiva))
df_daxt_final = modelo_daxt.transform(df_treino_daxt).withColumn("daxt_lance", F.when(is_acao_defensiva, F.col("prediction_daxt")).otherwise(0.0))

print("Auditoria Célula 2: Avaliação de Risco Lance a Lance")
display(
    df_daxt_final.filter(F.col('game_id').contains('1889883'))
    .select('game_id','player', 'period_id', 'time_seconds', 'type_id', 'probabilidade_gol', 'ovaep_lance', 'start_x','start_y','end_x','end_y','daxt_lance')
    .orderBy('game_id', 'period_id', 'time_seconds')
)

# COMMAND ----------

import pyspark.sql.functions as F
from pyspark.sql.window import Window

print("1. Calculando Multiplicadores PADJ e P90 no Nível da Partida...")
# Filtra quem jogou pelo menos 15 minutos para evitar distorções estatísticas extremas (ex: 1 desarme em 1 minuto virar 90 no P90)
df_base_jogo = df_game_log_temp.filter(F.col('minutos_jogados') >= 15)

df_padj_jogo = df_base_jogo.withColumn('padj_des', ((F.col('desarmes') / F.col('minutos_jogados')) * 90) * (50 / (100 - F.col('posse_bola')))) \
                           .withColumn('padj_int', ((F.col('interceptacoes') / F.col('minutos_jogados')) * 90) * (50 / (100 - F.col('posse_bola')))) \
                           .withColumn('p90_cor', (F.col('cortes') / F.col('minutos_jogados')) * 90) \
                           .withColumn('p90_fal', (F.col('faltas') / F.col('minutos_jogados')) * 90) \
                           .withColumn('p90_dri', (F.col('driblado') / F.col('minutos_jogados')) * 90).fillna(0)

print("2. Calculando o Score 0-100 (Z-Score por Partida)...")
janela_global = Window.partitionBy()
df_impacto_jogo = df_padj_jogo.withColumn('z_des', (F.col('padj_des') - F.mean('padj_des').over(janela_global)) / F.stddev('padj_des').over(janela_global)) \
                              .withColumn('z_int', (F.col('padj_int') - F.mean('padj_int').over(janela_global)) / F.stddev('padj_int').over(janela_global)) \
                              .withColumn('z_cor', (F.col('p90_cor') - F.mean('p90_cor').over(janela_global)) / F.stddev('p90_cor').over(janela_global)) \
                              .withColumn('z_fal', (F.col('p90_fal') - F.mean('p90_fal').over(janela_global)) / F.stddev('p90_fal').over(janela_global)) \
                              .withColumn('z_dri', (F.col('p90_dri') - F.mean('p90_dri').over(janela_global)) / F.stddev('p90_dri').over(janela_global)) \
                              .withColumn('impacto_bruto_jogo', F.col('z_des') + F.col('z_int') + F.col('z_cor') - F.col('z_fal') - F.col('z_dri'))

janela_ranking_jogo = Window.orderBy('impacto_bruto_jogo')

# Aqui a mágica acontece: O Score é atrelado ao game_id específico!
df_score_100 = df_impacto_jogo.withColumn('score_defesa_100', F.round(F.percent_rank().over(janela_ranking_jogo) * 100, 1)) \
                              .select('game_id', 'player', 'team_id', 'score_defesa_100')

print("Auditoria Célula 3: Score Defensivo por Partida (Arrascaeta)")
display(
    df_score_100
    .filter(F.col('team_id').contains('1239'))
    .select('game_id', 'player', 'team_id', 'score_defesa_100')
    .orderBy('player', ascending=True)
)

# COMMAND ----------

import pyspark.sql.functions as F
from pyspark.sql.window import Window

print("1. Recalculando Usage Rate (Regra de Finalizações e Perdas de Posse)...")

# Define a nova regra de Uso: Finalizações (11) + Passes errados (type_id 0, result_id 0) + Dribles perdidos (21, result_id 0)
df_uso_regras = df_ml_contexto.withColumn(
    'is_acao_uso', 
    F.when(
        (F.col('type_id') == 11) | 
        ((F.col('type_id').isin([0, 21])) & (F.col('result_id') == 0)), 
        1
    ).otherwise(0)
).withColumn(
    'is_passe', F.when(F.col('type_id') == 0, 1).otherwise(0) # Mapeia os passes para a tabela do Front-End
)

# Calcula o volume total de "uso" do time para gerar o percentual do jogador
janela_time_jogo = Window.partitionBy('game_id', 'team_id')

df_uso_jogo = df_uso_regras.withColumn(
    'uso_total_time', F.sum('is_acao_uso').over(janela_time_jogo)
).groupBy('game_id', 'player', 'team_id', 'uso_total_time').agg(
    F.sum('is_acao_uso').alias('uso_jogador'),
    F.sum('is_passe').alias('passes')
).withColumn(
    'usage_rate',
    F.when(F.col('uso_total_time') > 0, F.round((F.col('uso_jogador') / F.col('uso_total_time')) * 100, 2)).otherwise(0)
).select('game_id', 'player', 'team_id', 'usage_rate', 'passes')

print("2. Consolidando Dados e Blindando o oVAEP...")

# Constrói o dashboard consolidado a partir dos resultados das células anteriores
df_ovaep_partida = df_ovaep.groupBy('game_id', 'player', 'team_id').agg(F.sum('ovaep_lance').alias('ovaep_partida'))

df_dashboard = df_game_log_temp.join(
    df_score_100, on=['game_id', 'player', 'team_id'], how='left'
).join(
    df_ovaep_partida, on=['game_id', 'player', 'team_id'], how='left'
).withColumnRenamed('score_defesa_100', 'score_defensivo_global') \
 .withColumn('usage_rate', F.lit(0))

# Atualiza a base principal removendo o usage_rate antigo e acoplando a nova regra e os passes
df_dashboard_corrigido = df_dashboard.drop('usage_rate').join(
    df_uso_jogo, on=['game_id', 'player', 'team_id'], how='left'
).fillna({'usage_rate': 0, 'passes': 0})

df_dashboard_corrigido = df_dashboard_corrigido.dropDuplicates(['game_id', 'player', 'team_id'])

print("3. Exportando o JSON Definitivo...")
df_pandas = df_dashboard_corrigido.toPandas()
# Certifique-se de apontar para a mesma pasta onde seu HTML está sendo servido
df_pandas.to_json("/Volumes/workspace/default/parquet/dados_reais_brasileirao.json", orient="records")
print("✅ JSON exportado com sucesso! Passe, Usage Rate e Goleiros corrigidos.")

# Visualiza o resultado (Validando o Usage Rate e Score)
display(
    df_dashboard_corrigido
    .filter(F.col('team_id').contains('1239'))
    .select('temporada', 'game_id','team_id', 'player', 'ovaep_partida', 'usage_rate', 'score_defensivo_global')
    .orderBy('score_defensivo_global', ascending=True)
)

print("3. Exportando o Banco Consolidado...")
caminho_exportacao = "/Volumes/workspace/default/parquet/dashboard_final.parquet"
df_final_pandas = df_dashboard_corrigido.toPandas()
df_final_pandas.attrs = {}
df_final_pandas.to_parquet(caminho_exportacao, index=False)
print(f"✅ EXPORTAÇÃO CONCLUÍDA! Pronto para o download.")

# COMMAND ----------

import pyspark.sql.functions as F

print("Otimizando Eventos Táticos para Performance Web...")

caminho_exportacao = "/Volumes/workspace/default/parquet/dashboard_mapa.parquet"
df_eventos_mapa = df_daxt_final.select(
        'game_id', 
        'player', 
        'type_id', 
        'result_id', 
        F.round('start_x', 1).alias('start_x'),
        F.round('start_y', 1).alias('start_y'),
        F.round('end_x', 1).alias('end_x'),
        F.round('end_y', 1).alias('end_y'),
        F.round('ovaep_lance', 3).alias('ovaep_lance'),
        F.round('dvaep_lance', 3).alias('dvaep_lance')
    ).filter(F.col('start_x').isNotNull())

# Now convert to pandas and export
caminho_exportacao = "/Volumes/workspace/default/parquet/dashboard_mapa.parquet"
df_eventos_pandas = df_eventos_mapa.toPandas()
df_eventos_pandas.attrs = {}
df_eventos_pandas.to_parquet(caminho_exportacao, index=False)
print(f"✅ EXPORTAÇÃO CONCLUÍDA! Pronto para o download.")

# 1. Filtramos apenas as temporadas recentes para o mapa não congelar o navegador
# 2. Arredondamos as coordenadas para 1 casa decimal (corta o tamanho do JSON em 60%)
df_eventos_mapa = df_daxt_final.join(df_caminhos, on='game_id', how='inner') \
    .filter(F.col('temporada').isin(['2019', '2020', '2025'])) \
    .select(
        'game_id', 
        'player', 
        'type_id', 
        'result_id', 
        F.round('start_x', 1).alias('start_x'),
        F.round('start_y', 1).alias('start_y'),
        F.round('end_x', 1).alias('end_x'),
        F.round('end_y', 1).alias('end_y'),
        F.round('ovaep_lance', 3).alias('ovaep_lance'),
        F.round('dvaep_lance', 3).alias('dvaep_lance')
    ).filter(F.col('start_x').isNotNull())

# Exporta o JSON comprimido
df_eventos_mapa.toPandas().to_json("/Volumes/workspace/default/parquet/eventos_taticos.json", orient="records")

print("✅ JSON de Eventos Táticos otimizado e exportado!")