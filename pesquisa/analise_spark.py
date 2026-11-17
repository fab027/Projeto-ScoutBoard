from pathlib import Path

from pyspark.sql import SparkSession

# 1. Inicializa o Cluster Spark Local
# Alocamos 7GB de memória RAM para aguentar os 7 anos de dados sem travar
spark = SparkSession.builder \
    .appName("Brasileirao_BigData_Analytics") \
    .config("spark.driver.memory", "7g") \
    .getOrCreate()

# Remove a poluição visual do terminal do Spark
spark.sparkContext.setLogLevel("ERROR")

print("Cluster PySpark iniciado. Ingerindo o Data Lake local...")

# 2. Leitura Distribuída (Batch Processing)
# O asterisco (*) faz o Spark ler TODOS os parquets da pasta simultaneamente
caminho_dados = str(Path(__file__).resolve().parents[1] / "dados" / "brutos" / "*.parquet")
df_spark = spark.read.parquet(caminho_dados)

# 3. Cache na memória para cálculos rápidos de Machine Learning
df_spark.cache()

# Contagem massiva de linhas
total_eventos = df_spark.count()
print(f"✅ SUCESSO! Ingestão concluída.")
print(f"Total de ações mapeadas no Brasileirão (2019-2025): {total_eventos:,} linhas.")

# Mostra as colunas padronizadas pelo SPADL que usaremos pro VAEP e PPDA
df_spark.select('game_id', 'period_id', 'time_seconds', 'team_id', 'player', 'type_name', 'result_name', 'start_x', 'start_y').show(10)