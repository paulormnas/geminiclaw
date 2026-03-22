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

async def run_reindex(domain: str):
    if not domain:
        print("Erro: Domínio não fornecido para reindexação")
        return
    
    indexer = VectorIndexer()
    await indexer.reindex(domain)
    print(f"Domínio {domain} limpo e pronto para reindexação. Execute o comando crawl para indexar novamente.")

async def main():
    parser = argparse.ArgumentParser(description="Deep Search Indexer CLI")
    parser.add_argument("command", choices=["crawl", "stats", "reindex"], help="Comando a executar")
    parser.add_argument("domain", nargs="?", help="Domínio para o comando reindex")
    
    args = parser.parse_args()
    
    if args.command == "crawl":
        await run_crawl()
    elif args.command == "stats":
        run_stats()
    elif args.command == "reindex":
        if not args.domain:
            parser.error("O comando reindex exige a especificação de um domínio (ex: reindex docs.python.org)")
        await run_reindex(args.domain)

if __name__ == "__main__":
    asyncio.run(main())
