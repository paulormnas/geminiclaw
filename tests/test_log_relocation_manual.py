import pytest
import asyncio
import os
import shutil
from pathlib import Path
from src.orchestrator import Orchestrator, AgentTask
from src.session import SessionManager
from src.runner import ContainerRunner
from src.ipc import IPCChannel
from src.output_manager import OutputManager
from src.config import SQLITE_DB_PATH

@pytest.mark.asyncio
async def test_log_relocation():
    print("--- Iniciando Teste de Relocação de Logs (Pós-Restart) ---")
    
    # Configurações para o teste
    os.environ["OUTPUT_BASE_DIR"] = "outputs/test_relocation"
    os.environ["LOGS_BASE_DIR"] = "logs/test_relocation"
    db_path = "outputs/test_relocation/test_sessions.db"
    os.environ["SQLITE_DB_PATH"] = db_path
    
    output_base = Path("outputs/test_relocation")
    logs_base = Path("logs/test_relocation")
    
    for p in [output_base, logs_base]:
        if p.exists():
            shutil.rmtree(p)
    
    # Inicializa dependências
    runner = ContainerRunner()
    ipc = IPCChannel()
    session_manager = SessionManager(db_path)
    output_manager = OutputManager(output_base, logs_base)
    
    orchestrator = Orchestrator(runner, ipc, session_manager, output_manager)
    
    # Cria uma sessão
    session = session_manager.create(agent_id="base")
    
    # Prompt simples
    prompt = "Escreva um pequeno poema sobre a Lua e salve como 'lua.md' nos artefatos (/outputs/)."
    
    print(f"Executando base agent diretamente...")
    task = AgentTask(agent_id="base", image="geminiclaw-base", prompt=prompt)
    
    result = await orchestrator._execute_agent(task, master_session_id=session.id)
    print(f"Status do agente: {result.status}")
    
    # Verificação
    unique_task_id = f"base_{result.session_id[:8]}"
    
    expected_log = logs_base / session.id / unique_task_id / "agent.log"
    expected_artifact_dir = output_base / session.id / unique_task_id / "artifacts"
    
    print("\n--- Verificação de Caminhos ---")
    if expected_log.exists():
        print(f"✅ Log encontrado no local correto: {expected_log}")
    else:
        print(f"❌ FALHA: Log não encontrado em {expected_log}")
        # Check where it might be
        print("Conteúdo de logs_base:")
        for p in logs_base.rglob("*"): print(f"  {p}")

    if expected_artifact_dir.exists():
        print(f"✅ Diretório de artefatos encontrado: {expected_artifact_dir}")
        for f in expected_artifact_dir.iterdir():
            print(f"   - Artefato: {f.name}")
    else:
        print(f"❌ FALHA: Diretório de artefatos não encontrado em {expected_artifact_dir}")

    # Verifica se NÃO há logs na pasta de outputs
    output_log_dir = output_base / session.id / unique_task_id / "logs"
    if output_log_dir.exists() and any(output_log_dir.iterdir()):
        print(f"❌ FALHA: Ainda existem logs no diretório de outputs: {output_log_dir}")
    else:
        print("✅ Confirmado: Nenhum log encontrado no diretório de outputs.")

if __name__ == "__main__":
    asyncio.run(test_log_relocation())
