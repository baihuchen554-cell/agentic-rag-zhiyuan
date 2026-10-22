from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode
from functools import partial
import logging

from .graph_state import State, AgentState
from core.execution_logger import logged_node
from .nodes import (
    aggregate_answers,
    collect_answer,
    compress_context,
    fallback_response,
    orchestrator,
    request_clarification,
    rewrite_query,
    should_compress_context,
    summarize_history,
    web_fallback,
    retrieve_documents,
    conversation_answer,
)
from .edges import route_after_orchestrator_call, route_after_rewrite, route_after_local_answer


def create_agent_graph(llm, tools_list):
    # 让大语言模型具备工具调用能力，并创建工具执行节点
    llm_with_tools = llm.bind_tools(tools_list)
    tool_node = ToolNode(tools_list)

    # 创建内存检查点保存器，用于保存和恢复工作流状态
    checkpointer = InMemorySaver()

    logging.getLogger(__name__).info("正在构建智能体工作流...")

    # ==================== 构建子智能体工作流 ====================
    # 使用 AgentState 管理单个子智能体的问题、上下文和执行状态
    agent_builder = StateGraph(AgentState)
    search_tool = next(tool for tool in tools_list if tool.name == "search_child_chunks")
    agent_builder.add_node("retrieve_documents", logged_node("agent.retrieve_documents", partial(retrieve_documents, search_tool=search_tool)))

    # 调度器：决定是否调用工具，以及如何继续处理问题
    agent_builder.add_node(
        "orchestrator",
        logged_node(
            "agent.orchestrator",
            partial(orchestrator, llm_with_tools=llm_with_tools)
        )
    )

    # 工具节点：执行大语言模型请求调用的工具
    agent_builder.add_node("tools", tool_node)

    # 上下文压缩节点：压缩检索上下文，控制上下文长度
    agent_builder.add_node(
        "compress_context",
        logged_node(
            "agent.compress_context",
            partial(compress_context, llm=llm)
        )
    )

    # 备用回答节点：达到执行限制等条件时，生成备用回答
    agent_builder.add_node(
        "fallback_response",
        logged_node(
            "agent.fallback_response",
            partial(fallback_response, llm=llm)
        )
    )

    # 判断工具执行后是否需要压缩上下文
    agent_builder.add_node(
        "should_compress_context",
        logged_node("agent.should_compress_context", should_compress_context)
    )

    # 收集当前子智能体的最终答案
    agent_builder.add_node(
        "collect_answer",
        logged_node("agent.collect_answer", collect_answer)
    )
    agent_builder.add_node(
        "web_fallback",
        logged_node("agent.web_fallback", partial(web_fallback, llm=llm))
    )

    # 设置子智能体的执行顺序和条件路由
    agent_builder.add_edge(START, "retrieve_documents")
    agent_builder.add_edge("retrieve_documents", "should_compress_context")

    # 根据调度器的判断结果，选择执行工具、生成备用回答或收集答案
    agent_builder.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator_call,
        {
            "tools": "tools",
            "fallback_response": "fallback_response",
            "collect_answer": "collect_answer",
            "web_fallback": "web_fallback",
        }
    )

    # 工具执行完成后，判断是否需要压缩上下文
    agent_builder.add_edge("tools", "should_compress_context")

    # 压缩上下文后，返回调度器继续处理
    agent_builder.add_edge("compress_context", "orchestrator")

    # 备用回答生成后，进入答案收集节点
    agent_builder.add_conditional_edges("fallback_response", route_after_local_answer)
    agent_builder.add_edge("web_fallback", "collect_answer")

    # 答案收集完成，结束子智能体工作流
    agent_builder.add_edge("collect_answer", END)

    # 编译子智能体工作流，供主工作流调用
    agent_subgraph = agent_builder.compile()

    # ==================== 构建主智能体工作流 ====================
    # 使用 State 管理整个对话过程中的状态
    graph_builder = StateGraph(State)
    graph_builder.add_node("conversation_answer", logged_node("main.conversation_answer", partial(conversation_answer, llm=llm)))
    graph_builder.add_edge("conversation_answer", END)

    # 总结历史对话，减少冗余信息对后续处理的影响
    graph_builder.add_node(
        "summarize_history",
        logged_node(
            "main.summarize_history",
            partial(summarize_history, llm=llm)
        )
    )

    # 分析并改写用户问题，判断问题是否清晰
    graph_builder.add_node(
        "rewrite_query",
        logged_node(
            "main.rewrite_query",
            partial(rewrite_query, llm=llm)
        )
    )

    # 当问题不明确时，请求用户补充信息
    graph_builder.add_node(
        "request_clarification",
        logged_node(
            "main.request_clarification",
            request_clarification
        )
    )

    # 将子智能体工作流注册为主工作流中的一个节点
    graph_builder.add_node("agent", agent_subgraph)

    # 汇总各个子智能体的答案，生成最终回复
    graph_builder.add_node(
        "aggregate_answers",
        logged_node(
            "main.aggregate_answers",
            partial(aggregate_answers, llm=llm)
        )
    )

    # 设置主工作流的基本执行顺序
    graph_builder.add_edge(START, "summarize_history")
    graph_builder.add_edge("summarize_history", "rewrite_query")

    # 根据问题改写结果，决定请求澄清还是启动子智能体
    graph_builder.add_conditional_edges(
        "rewrite_query",
        route_after_rewrite
    )

    # 用户补充信息后，重新进行问题分析与改写
    graph_builder.add_edge("request_clarification", "rewrite_query")

    # 子智能体执行完成后，进入答案汇总节点
    graph_builder.add_edge(["agent"], "aggregate_answers")

    # 汇总完成，结束主工作流
    graph_builder.add_edge("aggregate_answers", END)

    # 编译主工作流：
    # 保存会话状态，并在请求用户澄清之前暂停执行
    agent_graph = graph_builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["request_clarification"]
    )

    logging.getLogger(__name__).info("✓ 智能体工作流编译成功。")
    return agent_graph
