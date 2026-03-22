from qdrant_client import QdrantClient

def verify_qdrant():
    client = QdrantClient(url="http://localhost:6333")
    collections = client.get_collections()
    print("Conexão ao Qdrant estabelecida com sucesso!")
    print(f"Coleções disponíveis: {collections.collections}")

if __name__ == "__main__":
    verify_qdrant()
