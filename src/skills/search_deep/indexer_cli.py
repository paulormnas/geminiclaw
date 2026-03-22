import asyncio
import sys
import argparse
from .crawler import DomainCrawler
from .indexer import VectorIndexer
from src.config import get_env

async def run_crawl():
    domains_str = get_env("DEEP_SEARCH_DOMAINS", "")
    if not domains_str:
        print("Erro: DEEP_SEARCH_DOMAINS não configurado no .env")
        return

    domains = [d.strip() for d in domains_str.split(",") if d.strip()]
    max_pages = int(get_env("DEEP_SEARCH_MAX_PAGES_PER_DOMAIN", "10"))

    print(f"Iniciando crawl de {len(domains)} domínios (max {max_pages} páginas por domínio)...")
    
    crawler = DomainCrawler()
    indexer = VectorIndexer()
    
    try:
        pages = await crawler.crawl(domains, max_pages)
        print(f"Crawl concluído: {len(pages)} páginas coletadas.")
        
        if pages:
            print(f"Iniciando indexação no Qdrant...")
            await indexer.index_pages(pages)
            print("Indexação concluída com sucesso.")
        else:
            print("Nenhuma página nova para indexar.")
            
    finally:
        await crawler.close()

def run_stats():
    indexer = VectorIndexer()
    stats = indexer.get_stats()
    print(f"Estatísticas do índice Deep Search:")
    print(f"  Pontos (chunks): {stats['points_count']}")
    print(f"  Status: {stats['status']}")

async def main():
    parser = argparse.ArgumentParser(description="Deep Search Indexer CLI")
    parser.add_argument("command", choices=["crawl", "stats"], help="Comando a executar")
    
    args = parser.parse_args()
    
    if args.command == "crawl":
        await run_crawl()
    elif args.command == "stats":
        run_stats()

if __name__ == "__main__":
    asyncio.run(main())
