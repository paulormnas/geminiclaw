from collections import deque
from src.orchestrator import AgentTask

class TaskScheduler:
    """Valida um plano de execução garantindo que não existam dependências cíclicas."""

    @staticmethod
    def validate_dag(tasks: list[AgentTask]) -> None:
        """Verifica se o plano contém ciclos ou dependências inválidas.
        
        Args:
            tasks: Lista de tarefas propostas pelo planner.
            
        Raises:
            ValueError: Se houver ciclo ou dependência para uma tarefa não existente.
        """
        task_names = {t.task_name for t in tasks if t.task_name}
        
        # Validação de dependências perdidas
        for t in tasks:
            if not t.task_name:
                continue
            for dep in t.depends_on:
                if dep not in task_names:
                    raise ValueError(f"Tarefa '{t.task_name}' depende de '{dep}', que não existe no plano.")

        # Detecção de ciclo (Kahn's algorithm)
        in_degree = {t.task_name: 0 for t in tasks if t.task_name}
        graph = {t.task_name: [] for t in tasks if t.task_name}
        
        for t in tasks:
            if not t.task_name:
                continue
            for dep in t.depends_on:
                graph[dep].append(t.task_name)
                in_degree[t.task_name] += 1
                
        queue = deque([node for node, degree in in_degree.items() if degree == 0])
        visited_count = 0
        
        while queue:
            node = queue.popleft()
            visited_count += 1
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    
        if visited_count != len(task_names):
            raise ValueError("O plano contém dependências cíclicas entre as tarefas.")
