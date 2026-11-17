# 1. Importando as bibliotecas (Essential Libraries and Tools - PAG 7)
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import mglearn
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier

print("Iniciando a aplicação de Machine Learning...")

# 2. Carregando os dados (Meet the Data - PAG 14, 15, 16, 17)
iris_dataset = load_iris()
print(f"Dataset carregado com sucesso. Classes disponíveis: {iris_dataset['target_names']}")

# 3. Dividindo os dados (Measuring Success: Training and Testing Data - PAG 17 18)
X_train, X_test, y_train, y_test = train_test_split(
    iris_dataset['data'], iris_dataset['target'], random_state=0)

# 4. Visualizando os dados (First Things First: Look at Your Data - PAG 19)
# Convertendo para DataFrame do Pandas e gerando a matriz de dispersão
print("Gerando gráfico de dispersão. Feche a janela do gráfico para continuar a execução do código.")
iris_dataframe = pd.DataFrame(X_train, columns=iris_dataset.feature_names)
pd.plotting.scatter_matrix(iris_dataframe, c=y_train, figsize=(10, 10), marker='o',
                           hist_kwds={'bins': 20}, s=60, alpha=.8, cmap=mglearn.cm3)
# Em scripts .py (fora do Jupyter), plt.show() é obrigatório para exibir a imagem
plt.show() 

# 5. Construindo e treinando o modelo k-NN (Building Your First Model: k-Nearest Neighbors - PAG 21)
print("Treinando o modelo k-NN...")
knn = KNeighborsClassifier(n_neighbors=1)
knn.fit(X_train, y_train)

# 6. Fazendo uma previsão com uma flor nova e desconhecida (Making Predictions - PAG 22)
X_new = np.array([[5, 2.9, 1, 0.2]]) 
prediction = knn.predict(X_new)

print("\n--- RESULTADO DA PREVISÃO ---")
print(f"Medidas da flor (Sépala/Pétala): {X_new}")
print(f"Classe prevista (Número): {prediction}")
print(f"Espécie prevista (Nome): {iris_dataset['target_names'][prediction]}")

# 7. Avaliando a precisão geral do modelo (Evaluating the Model - PAG 23)
print("\n----AVALIAÇÃO DO MODELO----")
score = knn.score(X_test, y_test)
print(f"Precisão do modelo de testes: {score:.2f} (ou {score*100:.0f}%)")