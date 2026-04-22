import pytest
from src.orchestrator import AgentTask
from src.task_scheduler import TaskScheduler

def test_validate_dag_valid_linear():
    tasks = [
        AgentTask(agent_id="base", image="img", prompt="A", task_name="t1", depends_on=[]),
        AgentTask(agent_id="base", image="img", prompt="B", task_name="t2", depends_on=["t1"]),
        AgentTask(agent_id="base", image="img", prompt="C", task_name="t3", depends_on=["t2"]),
    ]
    # Não deve levantar exceção
    TaskScheduler.validate_dag(tasks)

def test_validate_dag_valid_parallel():
    tasks = [
        AgentTask(agent_id="base", image="img", prompt="A", task_name="t1", depends_on=[]),
        AgentTask(agent_id="base", image="img", prompt="B", task_name="t2", depends_on=[]),
        AgentTask(agent_id="base", image="img", prompt="C", task_name="t3", depends_on=["t1", "t2"]),
    ]
    # Não deve levantar exceção
    TaskScheduler.validate_dag(tasks)

def test_validate_dag_cycle():
    tasks = [
        AgentTask(agent_id="base", image="img", prompt="A", task_name="t1", depends_on=["t2"]),
        AgentTask(agent_id="base", image="img", prompt="B", task_name="t2", depends_on=["t1"]),
    ]
    with pytest.raises(ValueError, match="cíclicas"):
        TaskScheduler.validate_dag(tasks)

def test_validate_dag_missing_dep():
    tasks = [
        AgentTask(agent_id="base", image="img", prompt="A", task_name="t1", depends_on=["t99"]),
    ]
    with pytest.raises(ValueError, match="não existe no plano"):
        TaskScheduler.validate_dag(tasks)
